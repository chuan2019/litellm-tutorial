"""custom_auth that gives every IdP user a personal spend cap, provisioned from their group on first sign-in."""
import asyncio
import os

import httpx
from fastapi import HTTPException, Request

from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.auth_checks import get_user_object
from litellm.types.proxy.auth.auth_checks import UserNotFoundError
from oidc_auth import user_api_key_auth as verify_oidc

PROXY_SELF_URL = os.environ.get("PROXY_SELF_URL", "http://127.0.0.1:4103")
MASTER_KEY = os.environ["LITELLM_MASTER_KEY"]

# The cap each group's members start with. An admin can change one person's cap later with /user/update.
GROUP_BUDGETS = {
    "ml-eng": {"max_budget": 0.00003, "budget_duration": "2m"},
    "support": {"max_budget": 0.00002, "budget_duration": "2m"},
}

_provision_lock = asyncio.Lock()


async def _user_exists(user_id: str) -> bool:
    from litellm.proxy.proxy_server import prisma_client, proxy_logging_obj, user_api_key_cache

    try:
        await get_user_object(user_id=user_id, prisma_client=prisma_client, user_api_key_cache=user_api_key_cache,
                              user_id_upsert=False, proxy_logging_obj=proxy_logging_obj)
    except UserNotFoundError:
        return False
    return True


async def _provision(user_id: str, email: str | None, group: str) -> None:
    """Create the user row with the group's budget, through the same /user/new an admin would call."""
    async with _provision_lock:
        if await _user_exists(user_id):
            return
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{PROXY_SELF_URL}/user/new", headers={"Authorization": f"Bearer {MASTER_KEY}"},
                                  json={"user_id": user_id, "user_email": email, "user_role": "internal_user",
                                        "auto_create_key": False, **GROUP_BUDGETS[group]})
        if r.status_code != 200:
            raise HTTPException(status_code=503, detail={"error": f"budget: could not provision {user_id}"})


async def user_api_key_auth(request: Request, api_key: str) -> UserAPIKeyAuth:
    """Validate the IdP token, make sure the person has a budgeted user row, then attribute spend to them."""
    auth = await verify_oidc(request, api_key)
    if auth.user_role == LitellmUserRoles.PROXY_ADMIN:
        return auth
    group = auth.team_id
    if group not in GROUP_BUDGETS:
        raise HTTPException(status_code=403, detail={"error": f"budget: no budget policy for group '{group}'"})
    # The proxy treats a missing user row as "no user limits", so a user without a row would spend uncapped.
    if not await _user_exists(auth.user_id):
        await _provision(auth.user_id, auth.user_email, group)
    # team_id names an IdP group, not a LiteLLM team row; leaving it set makes the proxy look the team up.
    return auth.model_copy(update={"team_id": None})
