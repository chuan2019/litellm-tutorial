"""custom_auth for the proxy: accept OIDC tokens from your identity provider and map groups to access."""
import asyncio
import hmac
import os

import httpx
import jwt
from fastapi import HTTPException, Request

from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.common_utils.http_parsing_utils import _read_request_body

ISSUER = os.environ["OIDC_ISSUER"]
AUDIENCE = os.environ["OIDC_AUDIENCE"]
MASTER_KEY = os.environ["LITELLM_MASTER_KEY"]

# First matching group wins, so list the most privileged group first.
GROUP_POLICY = [
    ("llm-admins", {"user_role": LitellmUserRoles.PROXY_ADMIN, "models": []}),
    ("ml-eng", {"user_role": LitellmUserRoles.INTERNAL_USER, "models": ["chat", "chat-cheap"], "rpm_limit": 60}),
    ("support", {"user_role": LitellmUserRoles.INTERNAL_USER, "models": ["chat-cheap"], "rpm_limit": 20}),
]

_jwks: jwt.PyJWKClient | None = None


def _jwks_client() -> jwt.PyJWKClient:
    """Discover the IdP's signing keys once; PyJWKClient caches them and refetches on an unknown kid."""
    global _jwks
    if _jwks is None:
        config = httpx.get(f"{ISSUER}/.well-known/openid-configuration", timeout=5).json()
        _jwks = jwt.PyJWKClient(config["jwks_uri"], cache_keys=True, lifespan=600)
    return _jwks


def _deny(reason: str) -> HTTPException:
    return HTTPException(status_code=401, detail={"error": f"oidc: {reason}"})


async def user_api_key_auth(request: Request, api_key: str) -> UserAPIKeyAuth:
    """Validate the bearer token's signature, issuer, audience and expiry, then grant by group."""
    # custom_auth replaces the proxy's own key check, so the master key must be let through here.
    if hmac.compare_digest(api_key.encode(), MASTER_KEY.encode()):
        return UserAPIKeyAuth(api_key=api_key, user_role=LitellmUserRoles.PROXY_ADMIN)
    try:
        signing_key = await asyncio.to_thread(_jwks_client().get_signing_key_from_jwt, api_key)
        claims = jwt.decode(api_key, signing_key.key, algorithms=["RS256"], audience=AUDIENCE, issuer=ISSUER,
                            options={"require": ["exp", "iat", "sub", "aud", "iss"]}, leeway=30)
    except jwt.ExpiredSignatureError as e:
        raise _deny("token expired") from e
    except jwt.InvalidAudienceError as e:
        raise _deny("token was issued for another application") from e
    except (jwt.PyJWKClientError, jwt.InvalidTokenError) as e:
        raise _deny(f"invalid token ({type(e).__name__})") from e

    groups = set(claims.get("groups", []))
    group, grant = next(((g, p) for g, p in GROUP_POLICY if g in groups), (None, None))
    if grant is None:
        raise HTTPException(status_code=403, detail={"error": f"oidc: no LLM access for groups {sorted(groups)}"})
    # The proxy does not check the models of a custom_auth token against the request, so check here.
    model = (await _read_request_body(request)).get("model")
    if model and grant["models"] and model not in grant["models"]:
        raise HTTPException(status_code=403, detail={"error": f"oidc: model '{model}' not allowed for your group"})
    # A per-user api_key makes rpm_limit and spend apply per person, not per token.
    return UserAPIKeyAuth(api_key=f"oidc:{claims['sub']}", user_id=claims["sub"], user_email=claims.get("email"),
                          team_id=group, **grant)
