# Exercises: local setup for calling Bedrock models

Practice scripts in this folder call LLMs on AWS Bedrock through LiteLLM. They use the same setup as the notebooks:

- `_env.py` loads settings from `.env.local`, refuses long-lived AWS keys, and switches between fake and real calls.
- `.env.local` holds your profile, region and mode. It contains no secrets.

## Setup steps

**1. Python environment** (once, or after changing `pyproject.toml`)

```bash
uv sync --group notebooks    # adds python-dotenv, boto3, botocore[crt]
```

**2. Sign in to AWS** (whenever your session expires, usually daily)

```bash
aws sso login --profile <your-profile>                 # or: aws login --profile <name> for console-login profiles
aws sts get-caller-identity --profile <your-profile>   # sanity check
```

Use a profile from `~/.aws/config` whose role has Bedrock access. If you need a new one, run `aws configure sso`.

**3. Configure `.env.local`** in this folder (`cp .env.local.example .env.local` first if it doesn't exist). No secrets go in this file:

```ini
AWS_PROFILE=<your-profile>
AWS_REGION=us-west-2
LIVE=1          # 1 = real Bedrock calls (costs money); 0 = fake (mock) replies, no AWS needed
```

`_env.py` won't load if this file contains `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY`. Credentials always come from your SSO login.

**4. Write a script.** Import `_env` first, because it must set environment variables before LiteLLM is imported:

```python
# ex01_hello.py
import _env
import litellm

_env.status()  # prints mode, region and models, never credentials
resp = litellm.completion(
    model=_env.FAST,   # or _env.SMART / _env.ALT, or any "bedrock/..." model string
    messages=[{"role": "user", "content": "Say hi in five words."}],
    **_env.mock("hi from the mock"),   # used only when LIVE != 1
)
print(resp.choices[0].message.content)
```

**5. Run it**

```bash
cd exercises
uv run python ex01_hello.py
```

`uv run` finds the project's `.venv` automatically. `import _env` works because Python adds the script's own folder to its import path.

## Things to know

- **Check model access first.** Open `../notebooks/00_credentials.ipynb` with `LIVE=1`. It confirms your profile works and lists which of the configured models your region and role can use. It then makes one tiny paid call per model, so expect a few cents. If a model shows as not found, change `MODEL_FAST`, `MODEL_SMART` or `MODEL_ALT` in `.env.local`.
- **Role permissions.** Your role needs `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`, and each model must be enabled in the account. If you get access denied, ask the account admin.
- **Troubleshooting.** `../notebooks/AWS_SIGN_IN.md` explains the sign-in flow in full and has a table of common errors and fixes, such as expired sessions or a missing `botocore[crt]`.
- **Your exercises stay local.** This folder's `.gitignore` tracks only `README.md`, `_env.py`, `.env.local.example`, `exam.html` and itself, so your scripts and `.env.local` are never committed. To keep a script in git, add a `!<name>` line to it.
- **The semantic router exercises (14b) need an overlay.** Run them with `uv run --with semantic-router==0.1.16 --with openai==2.54.0 python ex14b_1_routes.py`. The package isn't in the project because its `openai<3` requirement conflicts with the project's `openai` pin.
- **Shell variables win.** An `AWS_PROFILE` already exported in your shell overrides `.env.local`. Run `unset AWS_PROFILE` if calls go to the wrong account.

## What to write here

The exercise problems are at the end of each section of [`../TUTORIAL.md`](../TUTORIAL.md), numbered by section (exercise 7.2 is the second exercise for section 7). Sections 14, 16, 19 and 22 have lettered subsections, so their exercises are numbered by subsection (14c.1 is the first exercise for the quality router, in `ex14c_1_tier_ties.py`; 16b.2 is the second agent-gateway exercise; 19c.1 is the Lens investigation exercise; 22c.1 is the first memory exercise). Each one names the script to create, such as `ex07_2_group_fallbacks.py`, and lists the checks to write as `assert`s. "Exercises and the self-test" in the tutorial's Setup section has the ground rules. For the patterns, start from `../examples/01_*.py` to `11_*.py`, `14a_*.py` to `22d_*.py`, `../examples/mcp/`, `../examples/agents/`, `../examples/lens/`, `../examples/memory/` and `../examples/security/`. Exercises 15.1, 15.2, 16a.2 and 16b.2–16b.4 need a running proxy (16a.2 and 16b.2–16b.4 also need section 13's database, and 16b.2–16b.4 need `examples/agents/fake_agents.py` on port 4016); Exercise 22c.2 needs the proxy from `../examples/memory/memory_config.yaml` with the database. The tutorial says how to start them.

Section 19's exercises need Lens running (see "Starting Lens" in section 19, and export `LENS_ADMIN_TOKEN`) and import the helpers in `../examples/lens/` by putting that folder on `sys.path`, not `_env`:

- 19a.1 and 19a.2 need only Lens; 19a.1 starts the fake support model itself.
- 19b.1, 19b.2 and 19c.1 need the proxy from `../examples/lens/lens_config.yaml`, connected to Lens, with section 13's database and `fake_support_llm.py` running.
- 19c.1 calls the `analysis` model on Bedrock through the proxy (about $0.12 a run), so sign in to AWS first.

Exercises 12.3–12.5 cover AWS Bedrock. They run against `../examples/bedrock/fake_bedrock.py 4015` with fake signing keys, so they need no AWS access; each hint says how to go live. Exercises 12.6–12.8 cover Azure, Google Vertex AI and all three clouds behind one alias, against the fakes in `../examples/azure/` and `../examples/vertex/`. Exercise 12.9 needs Ollama in Docker (about 400 MB for the model).

Sections 20 and 21 are about running the proxy safely, so most of their exercises talk to a proxy over HTTP and don't import `_env`:

- 20.1 and 20.4 need your `proxy_config.yaml` from 12.1 with `DATABASE_URL` set (section 13's Postgres). 20.2 runs its own fake identity provider; 20.3 runs offline.
- 21.1 and 21.2 use `../examples/security/echo_upstream.py 4012` as a fake provider, so they never call Bedrock.
- 21.4 needs the Docker stack in `../examples/security/prod/`. On a umask of `077`, `chmod 644` the files you mount into it, because the proxy image runs as a non-root user.

## Self-test

Open [`exam.html`](exam.html) in a browser (`explorer.exe exam.html` from WSL, or double-click it). It works offline and holds 281 questions across 22 domains of LiteLLM. Practice mode shows the answer and explanation after each question, for the domains you choose. Exam mode draws 50 questions evenly from all domains, with 75 minutes and a 75% pass mark. Your exam scores are kept in that browser only.
