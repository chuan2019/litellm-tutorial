# When LiteLLM needs a commercial licence

*For LiteLLM 1.110.2, checked against its installed source and the [LiteLLM Enterprise page](https://docs.litellm.ai/docs/enterprise) in November 2026. Licensing terms change between versions, so check again before you rely on this. This report is not legal advice.*

## Summary

LiteLLM is open core. The SDK and the proxy are MIT-licensed, so you can run them in production, commercially, for any number of people, at no cost. You need a commercial licence only when you turn on a feature from the Enterprise tier. The licence is a key (`LITELLM_LICENSE`) for the same Docker image and version, so adding one later needs no migration.

No user-count limit applies to the free proxy, with one exception: Admin UI sign-in through SSO creates at most 5 users.

## What stays free

- The SDK: 100+ providers, the router and fallbacks, cost per call, logging callbacks.
- In the proxy:
  - the master key, virtual keys, teams, users and their roles
  - key types, per-key `allowed_routes` and key expiry
  - your own auth function (`custom_auth`)
  - budgets and rate limits per key, user and team
  - spend tracking and the Admin UI
  - load balancing, guardrails (PII masking, prompt injection, Bedrock Guardrails, the content filter) and the MCP gateway
- Observability: OpenTelemetry, Prometheus and spend logs, plus logging to S3.
- Secret managers: AWS Secrets Manager, Azure Key Vault and a custom secret manager. The docs list these as Enterprise, but 1.110.2 has no licence check for them.

## When you need a licence

### Identity and access

| Feature | Without a licence (1.110.2) |
| --- | --- |
| Admin UI SSO for more than 5 users | The 6th SSO user is not created. All users count toward the 5, including ones an admin created by hand |
| JWT auth with your identity provider's tokens (`enable_jwt_auth`) | 403 on every JWT request |
| OAuth2 token introspection (`enable_oauth2_auth`) | 403 |
| SCIM v2 user provisioning (`/scim/v2`) | 403 |
| Organizations and the `org_admin` role | 403 from `/organization/*` |
| Making a team member an `admin` | Refused |
| `custom_auth_settings.mode: auto` (your auth function first, falling back to the proxy's key checks) | Not available; `custom_auth` replaces the proxy's key checks entirely |

### Network and route security

| Feature | Without a licence (1.110.2) |
| --- | --- |
| IP allowlist (`allowed_ips`) | The proxy refuses to start |
| Proxy-wide `allowed_routes` | Logs an error, but is still enforced |
| Proxy-wide `admin_only_routes` and `public_routes` | Ignored |
| Request and response size limits (`max_request_size_mb`) | Logged and ignored |

### Virtual keys

| Feature | Without a licence (1.110.2) |
| --- | --- |
| `/key/regenerate` (automated key rotation) | 500. Rotating the master key is free |
| `enforced_params` on a key | The key is created, then every call with it returns 500 |
| Key `tags`, per-key `guardrails`, per-model budgets (`model_max_budget`) | `/key/generate` refuses the request |

### Cost governance

- Tag-based budgets.
- Temporary budget increases.
- Soft-budget email alerts.
- Programmatic spend reports (`/global/spend/report`) by key, team, tag or model.

### Logging and audit

| Feature | Without a licence (1.110.2) |
| --- | --- |
| Audit log of admin changes (`store_audit_logs`) | Silently writes nothing |
| Logging to GCS buckets, GCS Pub/Sub or Azure Blob Storage | Not available |
| Per-team logging destinations, turning logging off per team | Not available |

### Guardrails

- Guardrails set per key or per team.
- Built-in integrations listed as Enterprise:
  - `llmguard_moderations`, `llamaguard_moderations`, `hide_secrets`, `openai_moderations`, `google_text_moderation`: in 1.110.2 these five check for a licence at startup.
  - `lakera_prompt_injection`, `aporia_prompt_injection`: no licence check in the 1.110.2 source, but the Enterprise page lists them.

### Secret managers

- HashiCorp Vault, Google Secret Manager and CyberArk: a startup error without a licence.
- KMS-encrypted environment values (`LITELLM_SECRET_AWS_KMS_*`).

### Operations and support

- Multi-region deployment.
- Custom Swagger and email branding.
- Some options of the complexity router.
- Support SLAs.

## Free workarounds

| Licensed feature | Free alternative |
| --- | --- |
| JWT auth, SSO beyond 5 users | Validate your identity provider's tokens in a `custom_auth` function. It can also create a user row with a spend cap on first sign-in. Or put an identity-aware proxy (oauth2-proxy, Pomerium) in front with `enable_oauth2_proxy_auth` |
| SCIM | Keep authentication in your own service, and have it issue or map LiteLLM virtual keys through the API |
| `/key/regenerate` | Issue a new key with the same scope, switch the caller, then block and delete the old key |
| `allowed_ips`, `max_request_size_mb` | Filter addresses and cap the body size at the load balancer or reverse proxy (for example nginx `client_max_body_size`) |
| HashiCorp Vault | A short `CustomSecretManager` that reads Vault's KV v2 API |
| Audit log of admin changes | No free equivalent inside the proxy. Use database or infrastructure audit trails |

## Watch for late failures

Several licensed features don't fail at startup. JWT auth and `enforced_params` fail on the first request, and `store_audit_logs` silently writes nothing. Test each feature with a real request before you rely on it.

## Licence terms

The repository's top-level `LICENSE` applies MIT to everything except the `enterprise/` directory. On PyPI that code ships as a separate package, `litellm-enterprise`, and `litellm[proxy]` installs it (version 0.1.83.post1 with 1.110.2). Its licence is proprietary. It allows production use only under BerriAI's Enterprise terms, with a valid licence "for the correct number of user seats". It allows copying and modifying for development and testing without a subscription.

Removing the licence check to use Enterprise features without a key falls outside the MIT grant. Have your legal team review both licence files for the version you deploy.

## Buying

There is no public price list: sales quotes based on deployment size. A 30-day trial is available through sales. You can buy through AWS Marketplace, Azure Marketplace, or directly by invoice. To check that a key is active, open the proxy's root URL: with a valid licence, the API docs page says **Enterprise Edition**.

## Further reading

Section 20 of *LiteLLM by Worked Example* (`TUTORIAL.md`) has the runs behind this table, the `custom_auth` and spend-cap examples, and the Vault secret manager.
