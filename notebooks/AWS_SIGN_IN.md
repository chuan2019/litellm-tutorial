# How the notebooks sign in to AWS Bedrock

The notebooks in this folder call every model through AWS Bedrock, and none of them holds a credential. They never sign in themselves. They pass a profile name to boto3, the AWS SDK for Python, which reuses the login session you started in a terminal, the same way the AWS CLI does.

## The chain, step by step

```
aws sso login ──► ~/.aws/sso/cache/ (token)
                         │
.env.local ──► AWS_PROFILE ──► boto3.Session() ──► temporary role credentials ──► signed Bedrock calls
```

1. **You log in once, in a terminal.** `aws sso login --profile <name>` opens a browser, you sign in, and the CLI caches a short-lived SSO token under `~/.aws/sso/cache/`. Profiles set up for console login use `aws login --profile <name>` instead, which caches under `~/.aws/login/`. This is the only step that involves a password or a browser.
2. **The notebook loads the profile name.** Each notebook's first cell imports [`_env.py`](_env.py), which copies `.env.local` into the environment. Two of its values matter here, and neither is a secret:
   - `AWS_PROFILE`: which profile in `~/.aws/config` to use
   - `AWS_REGION`: which Bedrock regional endpoint to call (default `us-west-2`)
3. **LiteLLM hands the work to boto3.** A call such as `litellm.completion(model="bedrock/...")` that passes no credentials makes LiteLLM create a plain `boto3.Session()` (in `litellm/llms/bedrock/base_aws_llm.py`). boto3 reads `AWS_PROFILE` and looks that profile up in `~/.aws/config`, where `sso_account_id` and `sso_role_name` name the account and role.
4. **boto3 exchanges the token for temporary credentials.** It sends the cached token to AWS IAM Identity Center and gets back temporary credentials for that role: an access key, a secret and a session token, usually valid for about an hour. boto3 keeps them in memory and refreshes them before they expire, for as long as the login session is valid.
5. **Every Bedrock request is signed.** LiteLLM signs each request with those credentials (AWS Signature Version 4) and sends it to the Bedrock endpoint in `AWS_REGION`.

## What this means in practice

- **No secret is in the notebooks or in `.env.local`.** The token and the temporary credentials stay in `~/.aws/` and in memory. `_env.py` refuses to load if `.env.local` contains `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` or `AWS_SESSION_TOKEN`, because long-lived access keys are not allowed.
- **A variable exported in your shell wins over `.env.local`.** If `AWS_PROFILE` is already set in the shell that started Jupyter, that profile is used.
- **When the login session expires, live calls fail** with an authentication or expired-session error. Run `aws sso login` (or `aws login`) again and re-run the cell. No notebook changes are needed.
- **To switch account or role,** change `AWS_PROFILE` in `.env.local` and restart the kernel. The file is read once per kernel.
- **Offline mode (`LIVE=0`) skips all of this.** Mock responses never contact AWS, so you need no login.

## What the role needs

Signing in only proves who you are. The role behind the profile must also be allowed to use the models:

| Need | For |
| --- | --- |
| `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` on the models and inference profiles used | Every live call (streaming uses the second) |
| Model access enabled for each model in the account | Bedrock refuses models that haven't been enabled |
| `bedrock:ListInferenceProfiles` and `bedrock:ListFoundationModels` | Only the availability check in `00_credentials.ipynb` |

The default models use `us.` cross-region inference profiles. Requests sent through one can be served in any US region the profile covers, so the role needs permission on the inference profile and on the model in each of those regions.

## Checking it works

Open [`00_credentials.ipynb`](00_credentials.ipynb) with `LIVE=1` in `.env.local`. It:

1. calls STS `GetCallerIdentity` to confirm the profile resolves to working credentials, without printing the identity (the result contains your account ID);
2. lists the inference profiles and models available in your region, and marks each configured model as available or not found (free);
3. makes one tiny paid call per configured model.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Error saying the SSO token or session has expired | The SSO login session ended | `aws sso login --profile <name>`, then re-run the cell |
| `LoginRefreshRequired: Your session has expired...` | Console-login (`aws login`) session ended | `aws login --profile <name>` |
| `Missing Dependency: ... requires ... "botocore[crt]"` | The profile uses `aws login`, which needs the CRT extra | `uv sync --group notebooks` in the repository root (the group pins `botocore[crt]`) |
| `RuntimeError: remove AWS_ACCESS_KEY_ID from .env.local` | Long-lived keys in `.env.local` | Delete them and set `AWS_PROFILE` instead |
| Access denied on a model call | The role lacks Bedrock permissions, or the model isn't enabled for the account | Ask the account admin; check with `00_credentials.ipynb` |
| `NOT FOUND in this region` in `00_credentials.ipynb` | The model ID isn't offered in `AWS_REGION` | Change `AWS_REGION`, or set `MODEL_FAST` / `MODEL_SMART` / `MODEL_ALT` to a model that is |
| Calls go to the wrong account | `AWS_PROFILE` exported in the shell overrides `.env.local` | `unset AWS_PROFILE` before starting Jupyter, or fix the shell's value |
