"""Fake OIDC identity provider: discovery document, JWKS and a token endpoint, like Okta, Entra ID or Keycloak."""
import json
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4013
ISSUER = f"http://127.0.0.1:{PORT}"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = "demo-key-1"
JWK = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key())) | {"kid": KID, "use": "sig", "alg": "RS256"}


def issue(sub: str, groups: list[str], aud: str, ttl: int, email: str | None = None) -> str:
    """Sign an ID-token-shaped JWT for a user."""
    now = int(time.time())
    claims = {"iss": ISSUER, "sub": sub, "aud": aud, "iat": now, "exp": now + ttl, "jti": str(uuid.uuid4()),
              "email": email or f"{sub}@example.com", "groups": groups}
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": KID})


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/.well-known/openid-configuration":
            return self._send({"issuer": ISSUER, "jwks_uri": f"{ISSUER}/keys", "token_endpoint": f"{ISSUER}/token",
                               "id_token_signing_alg_values_supported": ["RS256"]})
        if self.path == "/keys":
            return self._send({"keys": [JWK]})
        self.send_error(404)

    def do_POST(self) -> None:
        # Stands in for a real login or client-credentials grant: the caller states who it is.
        req = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)))
        token = issue(req["sub"], req.get("groups", []), req.get("aud", "litellm-proxy"), req.get("ttl", 300))
        self._send({"id_token": token, "token_type": "Bearer", "expires_in": req.get("ttl", 300)})

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
