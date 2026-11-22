"""A custom secret manager: resolve os.environ/NAME references from a Vault KV v2 store."""
import os

import httpx

from litellm.integrations.custom_secret_manager import CustomSecretManager


class VaultSecretManager(CustomSecretManager):
    """Read secrets from Vault; NAME maps to path secret/data/<name-in-kebab-case>."""

    def __init__(self) -> None:
        super().__init__(secret_manager_name="vault-kv")
        self.addr = os.environ["VAULT_ADDR"]
        # In Kubernetes, exchange the pod's service-account token for this via Vault's kubernetes auth.
        self.headers = {"X-Vault-Token": os.environ["VAULT_TOKEN"]}

    def _url(self, secret_name: str) -> str:
        return f"{self.addr}/v1/secret/data/{secret_name.lower().replace('_', '-')}"

    def _value(self, r: httpx.Response) -> str | None:
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()["data"]["data"]["value"]

    def sync_read_secret(self, secret_name, optional_params=None, timeout=None) -> str | None:
        return self._value(httpx.get(self._url(secret_name), headers=self.headers, timeout=timeout or 5))

    async def async_read_secret(self, secret_name, optional_params=None, timeout=None) -> str | None:
        async with httpx.AsyncClient(timeout=timeout or 5) as client:
            return self._value(await client.get(self._url(secret_name), headers=self.headers))
