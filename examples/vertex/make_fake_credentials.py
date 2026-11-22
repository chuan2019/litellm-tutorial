"""Write fake Google credential files whose token endpoints point at the fake Vertex, for offline runs."""
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

FAKE = os.environ.get("FAKE_VERTEX", "http://127.0.0.1:4019")
out = Path(sys.argv[1] if len(sys.argv) > 1 else ".creds")
out.mkdir(exist_ok=True)

# A service-account key file has the same fields as a real one; token_uri is where google-auth trades
# the signed JWT for an access token, so pointing it at the fake keeps the exchange offline.
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption()).decode()
(out / "service-account.json").write_text(json.dumps({
    "type": "service_account", "project_id": "acme-ml-prod", "private_key_id": "fake-key-id",
    "private_key": pem, "client_email": "litellm-proxy@acme-ml-prod.iam.gserviceaccount.com",
    "client_id": "100000000000000000001", "token_uri": f"{FAKE}/token"}, indent=2))

# Workload identity federation: a token from another identity provider (here a file) is exchanged
# at Google's STS for a Google access token. No Google key exists anywhere.
(out / "subject-token.jwt").write_text("eyJ.fake-oidc-token-from-another-cloud.sig")
(out / "workload-identity.json").write_text(json.dumps({
    "type": "external_account",
    "audience": "//iam.googleapis.com/projects/123456789/locations/global/workloadIdentityPools/litellm/providers/eks",
    "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
    "token_url": f"{FAKE}/v1/token",
    "credential_source": {"file": str((out / "subject-token.jwt").resolve())}}, indent=2))
for f in ("service-account.json", "workload-identity.json", "subject-token.jwt"):
    (out / f).chmod(0o600)
print(f"wrote {out}/service-account.json and {out}/workload-identity.json")
