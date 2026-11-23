# Tutorial: LiteLLM by Worked Example

Nov 22, 2026 · Tutorial version 0.2.1 · written for LiteLLM 1.110.2

## What LiteLLM is

### The problem it solves

Every LLM provider has its own API. Anthropic, OpenAI, Google, AWS Bedrock and Azure differ in request fields, message and tool-call formats, streaming events, error types, authentication and pricing. Code written against one provider's SDK is tied to that provider. An app that uses three providers carries three integrations, and the cross-cutting work (retries, failover to another provider, spend tracking, rate limits, logging) has to be built once per provider.

### What it does

LiteLLM is an open-source Python project, maintained by BerriAI, that puts one interface in front of more than 100 LLM providers. That interface is the OpenAI chat-completions format, which most tools already speak. You send an OpenAI-shaped request, and LiteLLM translates it for whichever provider the model string names (`anthropic/...`, `gemini/...`, `bedrock/...`, `ollama/...`). The reply comes back in OpenAI shape, along with token usage and cost.

On top of the translation, it adds the cross-cutting pieces you would otherwise build yourself: retries and fallbacks, load balancing across deployments (a deployment is one model at one endpoint with one set of credentials; deployments that share a name form a model group), cost tracking and budgets, caching, and logging callbacks.

It comes in two forms, and this tutorial covers both:

| Form | What it is | Who calls it | Sections |
| --- | --- | --- | --- |
| Python SDK (`import litellm`) | A library: `completion()`, `acompletion()`, `Router` | Your Python code, in-process | 1–11, 14, 16–19 |
| Proxy server (`litellm --config`) | An OpenAI-compatible HTTP gateway with virtual keys, budgets and rate limits | Any app or tool, in any language, that can talk to the OpenAI API | 12–13, 15–22 |

The proxy runs the SDK inside it, so everything the SDK does, the proxy does too.

### SDK vs proxy: what actually differs

Both forms run the same translation code. The difference is where that code runs, and so who holds the provider keys and who sees all the traffic.

With the **SDK**, LiteLLM is a library inside your program. Your process reads the provider key from its environment and calls the provider directly over HTTPS:

```python
import litellm  # needs ANTHROPIC_API_KEY in this process's environment
litellm.completion(model="anthropic/claude-haiku-5-5", messages=[{"role": "user", "content": "hi"}])
```

With the **proxy**, LiteLLM is a separate server that you start and keep running. It holds the provider keys, and your program sends it ordinary OpenAI API requests with a virtual key the proxy issued. The program does not import LiteLLM, and it names a model alias from the proxy's config rather than a provider string:

```python
from openai import OpenAI  # any OpenAI client, in any language, or curl
client = OpenAI(base_url="http://localhost:4000", api_key="sk-<virtual key>")
client.chat.completions.create(model="chat", messages=[{"role": "user", "content": "hi"}])
```

| | SDK | Proxy |
| --- | --- | --- |
| Where LiteLLM runs | Inside your Python process | In its own server process, which many apps share |
| Path of a request | Your app → provider | Your app → proxy → provider (one extra network hop) |
| Who holds the provider keys | Every app that uses it | Only the proxy; apps get virtual keys that can be revoked, budgeted and rate-limited |
| Which apps can use it | Python code only | Anything that speaks the OpenAI API |
| How the model is named | Provider string, `anthropic/...` | Alias from the proxy config, so the provider can change without touching the app |
| Spend, rate limits, cache, cooldowns (the time-outs that take a failing deployment out of rotation) | Per process by default, so each app counts only its own calls (a `Router` or a cache can be pointed at Redis to share them) | Shared across all callers, kept in Postgres and Redis |
| Configuration | Arguments in your code | A `config.yaml` plus an admin API and UI |
| What you operate | Nothing beyond your app | A service to deploy, secure and monitor, plus its database |

In short: the SDK makes your one Python app provider-agnostic. The proxy makes a whole organization provider-agnostic, and gives it one place to control keys, spend and policy. Features that need a central view of every caller (virtual keys, team budgets, the MCP gateway, guardrails applied to all apps) exist only in the proxy.

#### What only the proxy adds

The SDK makes one program provider-agnostic. The proxy is a separate service that a whole organisation shares, and that is what makes the following possible. They all need one place that sees every caller, holds shared state, and enforces policy before a request reaches a model, a tool or an agent.

| Capability | What it gives you | Why it needs the proxy | Section |
| --- | --- | --- | --- |
| **Virtual keys, teams and budgets** | A revocable key per app or person, with its own models, spend cap and rpm/tpm limits | Spend and limits must be counted across every caller, in Postgres and Redis | 13 |
| **Access control and sign-in** | Roles, teams and organisations; people sign in with your identity provider; provider keys come from a secret manager | Provider keys stay in one service, and apps only ever get virtual keys | 20 |
| **Guardrails** | Mask or block personal data, secrets and prompt injection, in requests and in replies | One policy, declared once, applies to every app, including tools you can't modify | 21 |
| **MCP gateway** | One `/mcp` endpoint in front of many MCP tool servers, with tools allowed per key and every tool call logged | Clients connect once with their LiteLLM key, never with each server's credentials | 15 |
| **Skills store** | Skills hosted for any model, searchable, and (opt-in) published at a public discovery index | The skills live in the proxy's database and are injected into requests on the way through | 16a |
| **Agent gateway (A2A)** | A2A agents registered once, discovered through their cards, called with the same keys, limits and spend tracking as models | The proxy rewrites each agent's URL to itself, so every call passes its checks | 16b |
| **Prompt registry** | Versioned prompts that every app fetches by `prompt_id`; editors change them without a deploy | The SDK can render prompt files itself; the proxy serves one registry to every app | 17 |
| **Central observability** | Spend logs per key, team, user and agent; Prometheus metrics; one place to attach logging platforms | Every call passes one point, so nothing has to be instrumented app by app | 13, 18 |
| **Memory and sessions** | `/v1/memory` for long-term entries, and Responses API sessions with `previous_response_id` | Both are state stored in the proxy's database | 22 |
| **Admin UI and API** | Manage models, keys, teams and the registries above without restarting | The configuration lives in the running service and its database | 13, 20 |

How these fit together when the proxy is the gateway of a microservice system:

```mermaid
%% fig: proxy-features
flowchart LR
    SVC["Your services"] --> POL
    AG["AI agents"] --> POL
    TL["Tools"] --> POL
    ADM["Admins"] --> POL
    subgraph PX["LiteLLM proxy (several replicas)"]
        POL["Keys, teams, SSO → budgets, limits → guardrails"]
        POL --> GW["LLM API · MCP gateway · Agent gateway<br/>Prompt registry · Skills store · Memory, sessions"]
        GW --> LOG["Spend logs, metrics, callbacks"]
    end
    GW --> LLM["LLM providers"]
    GW --> MCP["MCP tool servers"]
    GW --> A2A["A2A agents"]
    PX -.- PG[("Postgres")]
    PX -.- RD[("Redis")]
    PX -.- SM["Secret manager"]
    LOG -.- OBS["Observability"]
```

- **One policy layer in front of everything.** Whether a request is a chat completion, an MCP tool call or an A2A message, it carries a LiteLLM key, and the same checks run first: who the caller is, what it may use, whether it is within budget and rate limits, and whether the content passes the guardrails.
- **Several gateways behind it.** Models, tool servers and agents are all registered in the proxy and reached through it, so clients need one URL and one key, and the upstream credentials never leave the proxy.
- **Shared state, not shared code.** The proxy runs as several stateless replicas. Keys, spend, registries and memory live in Postgres; counters, cooldowns and the cache are shared through Redis; provider keys come from a secret manager (sections 20c and 21b show this).
- **Each capability has its own section.** This overview is only the map; the sections in the table show each one working.

The internals (how a request moves through the proxy, the router and the SDK, and where state lives) are in "How it works", in Setup, after the quick start. Run something first; the diagrams make more sense afterwards.

### Open-source LLM gateways

An LLM gateway is a service that sits between your apps and the model providers. Apps call one endpoint, usually OpenAI-compatible, and the gateway holds the provider keys and handles routing, retries and failover, spend tracking, rate limits and logging in one place. Several open-source gateways exist, and they differ mainly in what they are built on:

- **LiteLLM** (Python) is a gateway and a Python library in one, and supports more than 100 providers.
- **Portkey AI Gateway** (TypeScript) and **Bifrost** (Go) are standalone gateways built for low overhead.
- **Kong AI Gateway** and **Envoy AI Gateway** add LLM features to an existing API gateway or proxy, so they suit teams that already run Kong, or Envoy on Kubernetes.

Several have a paid hosted or enterprise edition, so check which features the open-source edition includes. Published performance numbers mostly come from the vendors themselves, so measure on your own traffic before choosing.

### What it is not

LiteLLM is plumbing between your code and the model providers. It does not host or serve models (for that, see vLLM or Ollama, which LiteLLM can call). It is not an agent or prompt framework like LangChain, and it is not an evaluation or observability platform, though it can send its logs to one.

### Where to use it

| Situation | Form | What LiteLLM gives you |
| --- | --- | --- |
| You call several providers, or want to keep the option to switch | SDK | One code path; switching is a string change |
| You compare models on your own task | SDK | The same eval loop runs against every model (section 11) |
| A provider outage or rate limit must not take your app down | SDK `Router` or proxy | Retries and fallbacks to another model, region or provider (sections 6–7) |
| Easy requests should go to a cheap model and hard ones to a strong model | SDK `Router` or proxy | Smart routers that pick the model per request (section 14) |
| Many agents share MCP tool servers, agent skills or each other | Proxy | One MCP endpoint with per-key access, a skills store, and an A2A agent gateway (sections 15–16) |
| Prompts should change without a code change | Either | Versioned prompt templates (section 17) |
| Long conversations or agents outgrow the context window, or should remember users | Either | Token counting, trimming, provider context editing and caching, window fallbacks, and the proxy's session and memory stores (section 22) |
| LLM calls should show up in your tracing and metrics tools | Either | OpenTelemetry, Prometheus and logging platforms (section 18) |
| You need to know and cap what each app or team spends | Proxy | Per-key spend tracking, budgets and rate limits (section 13) |
| Many teams, services or tools need LLM access | Proxy | One gateway that holds the provider keys; teams get revocable virtual keys, and people sign in with your identity provider (section 20) |
| Prompts may carry personal data or credentials, or attempts to subvert the model | Proxy | Guardrails that mask or block before the provider sees anything, and check replies (section 21) |
| Agents run in production and nobody can read every run | Either | Lens records each run's steps and the proxy's cost, and an analysis model reviews the runs against the expected behaviour (section 19) |
| Your app isn't Python, or it's an off-the-shelf tool | Proxy | Anything that speaks the OpenAI API works by changing its base URL |
| Local models in development, cloud models in production | Either | The same code, with a different model string per environment |

### Where to think twice

- **One provider, newest features.** If you use one provider and depend on its latest features (beta tools, new caching controls, new content-block types), call its native SDK. LiteLLM's translation can lag behind the provider, and the native SDK gets new features first.
- **One more service to run.** The proxy holds every provider key, so it is a high-value target that has to be patched, monitored and kept available (sections 20 and 21 cover what that takes). If you only need the SDK's features, the SDK alone adds no service.
- **Some controls need a licence.** JWT auth, SCIM, `/key/regenerate`, IP allowlists, per-key guardrails, request-size limits and several secret managers are LiteLLM Enterprise features. The next subsection explains the licence; section 20 lists what is free in 1.110.2 and the free workarounds.
- **Fast-moving dependency.** LiteLLM releases very often. Pin the exact version (as [`pyproject.toml`](pyproject.toml) does) and re-test when you upgrade.

### Open source vs. Enterprise

LiteLLM is open core. The SDK and the proxy are MIT-licensed and free to run in production, commercially too; that covers virtual keys, teams, budgets, rate limits, spend tracking, the Admin UI, routing, guardrails and the MCP gateway. A commercial licence is a key (`LITELLM_LICENSE`) for the same image, and you need it only for Enterprise-tier features such as JWT auth, SCIM, SSO beyond 5 users, organizations, audit logs, IP allowlists and per-key guardrails. Section 20 opens with the full breakdown: what is free, what is licensed, how 1.110.2 actually enforces it, and the free workarounds. Nothing in sections 1–19 needs a licence.

## What you will learn

Each section is one practical use case with a runnable script in [`examples/`](examples/):

| Sections | What they cover |
| --- | --- |
| 1–11 | The SDK: calls and provider adapters (AWS Bedrock, Amazon Bedrock Mantle, Ollama and vLLM in detail, the other major providers in brief), streaming, async, structured output, tools, errors and fallbacks, the `Router`, cost, caching, callbacks, comparing models |
| 12–13 | The proxy, run with `uv` or from the official Docker image; reaching models through AWS Bedrock and Bedrock Mantle, Microsoft Azure and Google Vertex AI, and directly through OpenAI, Anthropic, Ollama and vLLM; virtual keys, budgets and rate limits |
| 14 | Smart routers that choose a model per request |
| 15–18 | The MCP gateway, the skills and agent (A2A) gateways, prompt management, observability |
| 19 | Lens, which records and reviews agent runs |
| 20–21 | The licence breakdown, access control, identity providers, secret handling, guardrails and a hardened production deployment |
| 22 | Context and memory management |
| 23 | Other providers, for reference |

**Which version this covers.** This is version 0.2.1 of the tutorial (the `version` in [`pyproject.toml`](pyproject.toml)), and it is written for LiteLLM 1.110.2. The same file pins `litellm[proxy,extra_proxy]==1.110.2`, and the Docker commands use the matching image tag, `ghcr.io/berriai/litellm:v1.110.2`. Every output, signature, licence check and gotcha below describes that release. LiteLLM releases often, so on any other version expect some of them to differ, most of all where the text says "in 1.110.2". When the tutorial moves to a newer LiteLLM release, the examples are run again and the pin, this paragraph and the tutorial's version change together.

**What changed since the 1.109.1 edition.** Most behaviour in this tutorial is the same on 1.110.2. These are the differences that show up in it:

- **The router core runs in Rust** (since 1.110.0). The `Router` API is unchanged, and so is every routing output in sections 6, 7, 12 and 14; log lines now name the Rust core's modules, such as `registry.py` (How it works, 20c).
- **The proxy leaves out `x-litellm-response-cost` for a call it has no price for,** instead of sending `0.0`. Local Ollama models are the example in section 12.
- **Bedrock Converse bodies ask for the output-token breakdown** (`additionalModelResponseFieldPaths`) for models that think by default (12).
- **A per-call `azure_ad_token=` no longer leaks into the request body** of an `azure_ai/` Claude call; 1.109.1's workaround is no longer needed.
- **A rate-limited request no longer writes a warning to the proxy log,** only the `429` in the access log (21b).
- **Shared rate limits take longer to recover after a Redis outage:** up to about three minutes instead of one (21b).
- **New, and not covered here:** a fifth smart router, Switchyard (14), and the Skills Hub (16a).

This edition also adds to the tutorial itself. Section 1 now explains the provider adapters from the SDK: AWS Bedrock, Amazon Bedrock Mantle, Ollama and vLLM in detail, and the other major providers in brief, with exercises 1.4–1.11. Section 12 adds Bedrock Mantle behind the proxy, with exercise 12.10.

**How this was verified.** The outputs in this tutorial are pasted from real runs. The tutorial was first written and run on LiteLLM 1.109.1; for 1.110.2 every script was run again under both versions side by side, and only what changed was rewritten (the scripts are in [`build/compare/`](build/compare/)):

- **Sections 1–11, 14, 17, 18a and the SDK parts of 16 and 22:** offline, on Python 3.13 in the uv environment. Their output was the same on both versions, apart from timings, IDs and random load-balancing splits.
- **Section 1's provider subsections (added in 1.110.2's edition):** the Bedrock and Bedrock Mantle examples both offline and against real AWS (us-west-2 and us-east-1, through an SSO profile); the Ollama example against a real Ollama in Docker (`qwen2.5:0.5b` and `qwen3:0.6b` on CPU); the vLLM example against a fake vLLM server, because I had no GPU. The short table of other providers comes from requests captured offline, not from calls to those providers. They were run on 1.110.2 only.
- **Setup's proxy quick start and the notebooks:** against real Bedrock, the quick start both with `uv` and with the `v1.110.2` image.
- **Section 12:** the proxy with `uv` and from the official image; the AWS Bedrock, Azure, Google Vertex AI and direct-provider subsections against local fakes of those services, and against a real Ollama in Docker (`qwen2.5:0.5b` on CPU). The Bedrock Mantle proxy example ran against real AWS, since there is no fake Mantle, and the service-tier part both against the fake and against real Bedrock. I had no Azure or Google Cloud account to run them live.
- **Sections 13, 15, 16 and 18:** against a local proxy, with Postgres where noted; section 13 also with Docker Compose.
- **Section 19:** against the Lens 0.1.0 release bundle (Lens and ClickHouse in Docker) and a local proxy with Postgres, with a fake model for the agent. Only its investigations call a real model (Claude Haiku 5.5 on Bedrock, $0.05 to $0.13 per run).
- **Sections 20–21:** against local proxies, Postgres, Redis and nginx in Docker, with a fake identity provider, a fake Vault and a fake LLM provider. Nothing in them calls a real provider.
- **Section 22:** the SDK scripts offline with mocks and local fakes of the Anthropic API and Bedrock, and the proxy script against a local proxy with Postgres.
- **Exercises:** the reference solutions in [`solutions/`](solutions/) pass on 1.110.2, including those for exercises 1.4–1.11 and 12.10, which are new in this edition. The other exercises were written and solved on 1.109.1; for 1.110.2 their text was checked against the changes listed above, not solved again.

Where a claim comes from the source or the docs and was not run, the text says so.

## Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/). [`pyproject.toml`](pyproject.toml) pins `litellm[proxy,extra_proxy]==1.110.2`, `openai`, `pydantic` and the OpenTelemetry SDK and OTLP exporter (section 18), and installs them from PyPI:

```bash
uv sync                                  # creates .venv with the pinned versions
cd examples
export LITELLM_LOCAL_MODEL_COST_MAP=True # use the bundled price table instead of fetching it at import
uv run python 01_first_call.py
```

The script prints one mocked reply per model, with its token counts and cost; section 1 shows the output. Every `cd` in this tutorial is written from the repository root, so start each block from there.

`uv run` runs a command inside the project's `.venv` without activating it. Commands in this tutorial that use the installed packages (`python`, `litellm`, `prisma`) are written with `uv run`. `prisma` is Prisma Client Python, a database toolkit installed by the `litellm[extra_proxy]` extra, which the proxy needs to read and write the Postgres database that stores section 13's virtual keys, budgets and spend. You can instead activate the environment once with `. .venv/bin/activate` and drop the prefix.

### Quick start: a proxy in front of AWS Bedrock

Most of this tutorial calls models from Python with the SDK. The proxy is the other half of LiteLLM: a server that any OpenAI client can call. This quick start runs it with one model on AWS Bedrock and makes one real call through it, in about five minutes. Section 12 explains everything used here.

You need an AWS profile that can call Bedrock in your region, with Claude Haiku 5.5 enabled for the account (Bedrock console → Model access). No AWS account? Uncomment the `mock_response` line in `quickstart.yaml`, skip the `aws sso login` line, and the proxy answers "Hi from the proxy" without calling Bedrock. Otherwise sign in first:

```bash
aws sso login --profile <profile>
export AWS_PROFILE=<profile> AWS_REGION=us-west-2
export LITELLM_MASTER_KEY=sk-master-demo        # the proxy's admin key; pick your own
```

The whole configuration is one alias. [`examples/proxy/quickstart.yaml`](examples/proxy/quickstart.yaml):

```yaml
model_list:
  - model_name: claude                    # the alias your apps ask for
    litellm_params:
      model: bedrock/us.anthropic.claude-haiku-5-5
      aws_region_name: os.environ/AWS_REGION
      # mock_response: "Hi from the proxy"   # uncomment to try it without AWS

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

There is no AWS key in the file. The proxy signs each Bedrock request with whatever identity boto3 finds in its environment, here your SSO profile. `os.environ/NAME` reads a value from the proxy's environment.

**Start it locally** from the uv environment:

```bash
cd examples/proxy
LITELLM_LOCAL_MODEL_COST_MAP=True uv run litellm --config quickstart.yaml --port 4000
```

**Or start it in Docker** from the official image, which needs no Python. Mount your AWS config read-only so the container can use the same SSO session:

```bash
cd examples/proxy
docker run -d --name litellm-quickstart -p 127.0.0.1:4000:4000 \
  -v "$PWD/quickstart.yaml:/app/config.yaml:ro" \
  -v "$HOME/.aws:/root/.aws:ro" \
  -e AWS_PROFILE -e AWS_REGION -e LITELLM_MASTER_KEY \
  ghcr.io/berriai/litellm:v1.110.2 --config /app/config.yaml --port 4000
docker logs -f litellm-quickstart                  # Ctrl-C to stop following
```

`-e NAME` with no value copies that variable from your shell into the container. `127.0.0.1:4000:4000` keeps the port on your machine only.

**Call it** from a second terminal, with `LITELLM_MASTER_KEY` exported there as well. Wait for `curl -s localhost:4000/health/liveliness` to print `"I'm alive!"`, then send a chat request:

```bash
curl -s localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"model":"claude","messages":[{"role":"user","content":"Name the capital of France in one word."}]}'
```

```json
{
    "id": "chatcmpl-3173be7d-997a-4506-b3b2-2c6cae953042",
    "model": "claude",
    "object": "chat.completion",
    "choices": [{"finish_reason": "stop", "index": 0,
                 "message": {"content": "Paris", "role": "assistant"}}],
    "usage": {"completion_tokens": 5, "prompt_tokens": 19, "total_tokens": 24, ...}
}
```

Any OpenAI client works the same way. [`examples/proxy/quickstart_client.py`](examples/proxy/quickstart_client.py) uses the `openai` package and no LiteLLM import:

```python
client = OpenAI(base_url="http://localhost:4000", api_key=os.environ["LITELLM_MASTER_KEY"])
raw = client.chat.completions.with_raw_response.create(model="claude", messages=msgs)
raw.headers.get("x-litellm-response-cost")
```

```bash
uv run python quickstart_client.py
```

```text
models: ['claude']
reply: 'Paris'  tokens=19/5  cost=$0.000005
stream: 3 chunks -> '1 2 3 4 5'
```

I ran both ways against real Bedrock in us-west-2 through an SSO profile, and both gave this output. The calls cost well under a cent. What happened:

- The app asked for `claude` and never saw a Bedrock model ID, an AWS region or a credential. To change the model or provider, edit the config and restart the proxy; the app doesn't change.
- The proxy priced the call ($0.000005) and returned the cost in the `x-litellm-response-cost` header.
- Only the master key works for now. Any other key gets `{"error":{"message":"No connected db.", ...,"code":"400"}}`. Per-app virtual keys need a database (section 13).
- `docker rm -f litellm-quickstart` removes the container; Ctrl-C stops the local proxy.

Where to go next: section 12 covers the proxy config in depth. It also covers Bedrock regions, identities and failover, Azure and Google Vertex AI, and providers called directly (OpenAI, Anthropic, Ollama, vLLM). Section 13 adds virtual keys, budgets and rate limits. To run this proxy on a server that a team can share, see the next subsection.

### Running the proxy on an EC2 instance

The quick start runs the proxy on your own machine. To share one proxy with a team, run it on a server. This subsection puts the quick start's Bedrock proxy, plus the Postgres database that section 13's virtual keys need, on one EC2 instance with Docker Compose. It is a setup for trying the proxy out, not a production deployment: one instance, no load balancer, no TLS.

The design keeps the instance closed:

- **No AWS keys.** The instance has an IAM role (an *instance profile*), and boto3 inside the container picks up its temporary credentials, just as the quick start picks up your SSO session.
- **No SSH and no inbound ports.** You open a shell with AWS Systems Manager (SSM) Session Manager, and reach the proxy through an SSM port-forward. The security group allows no inbound traffic, and the proxy listens on the instance's `127.0.0.1` only.

You need console access to an AWS account where Bedrock is enabled. The files are in [`examples/ec2/`](examples/ec2/).

**Step 0: check Bedrock.** In the Bedrock console, in us-west-2, send one message to Claude Haiku 5.5 in the chat playground. If that fails, fix model access first; the proxy can't work around it.

**Step 1: create the instance role.** IAM → Roles → Create role, with trusted entity *AWS service* and use case *EC2*.

- Attach the AWS-managed policy `AmazonSSMManagedInstanceCore`, which lets the SSM agent on the instance register and carry sessions.
- Add an inline policy from [`examples/ec2/bedrock-invoke-policy.json`](examples/ec2/bedrock-invoke-policy.json), with your account ID in place of `<account-id>`. The region in each ARN is `*` on purpose: a `us.` inference profile can serve a request from any US region, and the role needs permission in whichever one answers.

**Step 2: create a security group** with no inbound rules and the default outbound rule. The instance needs outbound HTTPS to reach SSM and Bedrock and to pull the images.

**Step 3: launch the instance.** EC2 → Launch instances, in any region (the Bedrock region is set separately, in the proxy's environment):

| Setting | Value |
| --- | --- |
| AMI and type | Amazon Linux 2023, x86_64, `t3.medium` |
| Key pair | Proceed without a key pair |
| Network | A private subnet with a NAT gateway, or a public subnet with a public IP. Either is safe with no inbound rules |
| Security group | The one from step 2 |
| Storage | 20 GiB gp3, encrypted |
| Advanced → IAM instance profile | The role from step 1 |
| Advanced → Metadata version | V2 only (token required) |
| Advanced → Metadata response hop limit | **2** |
| Advanced → User data | [`examples/ec2/user-data.sh`](examples/ec2/user-data.sh), which installs Docker, the Compose plugin and git |

The hop limit is the setting that is easy to miss. A container reaches the instance metadata service through one more network hop than the host does, and with the default limit of 1 the proxy can't get the role's credentials.

**Step 4: connect and check the role.** After a few minutes, select the instance and choose Connect → Session Manager. The shell runs as `ssm-user`, so the commands below use `sudo`:

```bash
aws sts get-caller-identity          # the Arn names the role from step 1
aws bedrock-runtime converse --region us-west-2 \
  --model-id us.anthropic.claude-haiku-5-5 \
  --messages '[{"role":"user","content":[{"text":"hi"}]}]'
```

If `converse` returns a reply, the instance can call Bedrock.

**Step 5: start the proxy.** Clone this edition, write the secrets and start the stack:

```bash
sudo git clone --depth 1 --branch litellm-1.110.2 https://github.com/chuan2019/litellm-tutorial.git /opt/litellm-tutorial
cd /opt/litellm-tutorial/examples/ec2
sudo ./make_env.sh                                 # writes .env: master key, salt key, Postgres password
sudo docker compose up -d --wait                   # returns once Postgres and the proxy are healthy
curl -s localhost:4000/health/readiness
# {"status":"healthy","db":"connected"}
```

[`make_env.sh`](examples/ec2/make_env.sh) writes three random values to a `.env` file (git-ignored, readable by root only), and Compose reads them from there. [`docker-compose.yml`](examples/ec2/docker-compose.yml) is section 13's stack with three changes: the secrets come from `.env`, both containers restart with the instance, and the proxy gets the quick start's Bedrock model ([`config.yaml`](examples/ec2/config.yaml)) instead of mocked ones.

Then create a virtual key for the team, so the master key stays on the instance:

```bash
set -a; . <(sudo cat .env); set +a                 # loads LITELLM_MASTER_KEY into this shell
curl -s localhost:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"models":["claude"],"max_budget":1}'        # prints {"key":"sk-...", ...}
```

**Step 6: reach it from your machine.** Install the [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) for the AWS CLI, then forward a local port to the instance:

```bash
aws ssm start-session --profile <profile> --region <instance region> \
  --target <instance id> \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["4000"],"localPortNumber":["4000"]}'
```

Leave it running; it prints `Waiting for connections...`. `--region` is the **instance's** region, which is not necessarily the Bedrock one. While the session is open, `http://localhost:4000` on your machine is the proxy on the instance, so the quick start's client works unchanged, given the virtual key:

```bash
cd examples/proxy
export LITELLM_MASTER_KEY=sk-...                   # the virtual key from step 5; the script reads this variable
uv run python quickstart_client.py
```

The admin UI is at `http://localhost:4000/ui`; sign in as `admin` with the master key from the instance's `.env`.

Points to note:

- **The instance's region and the Bedrock region are independent.** The proxy calls Bedrock in `AWS_REGION` (`BEDROCK_REGION`, default us-west-2) wherever the instance runs. Only the SSM commands need the instance's region.
- **Compose fills in `${...}` from `.env` before it creates the containers**, and a variable exported in your shell overrides `.env` (`sudo` drops most of the shell's variables, so here `.env` wins). Each `${NAME:?run make_env.sh first}` makes Compose refuse to start when a value is missing, instead of starting with an empty one. `docker compose config` prints the file with every value filled in.
- **Editing `.env` needs `docker compose up -d`, not `restart`.** The values are written into each container when it is created; `up -d` recreates the containers whose values changed, `restart` reuses them as they are.
- **Postgres keeps its first password.** `POSTGRES_PASSWORD` is read only when the `pgdata` volume is created. With a new password in `.env`, the proxy fails with *"password authentication failed"*; `docker compose down -v` deletes the volume, and every key with it. That is why `make_env.sh` refuses to overwrite `.env`. The same goes for `LITELLM_SALT_KEY` once a credential is stored (section 20c).
- **Stop the instance when you're not using it.** Keys and spend survive in the volume, and both containers come back when the instance starts.

| Symptom | Cause | Fix |
| --- | --- | --- |
| Session Manager can't connect; the instance's system log shows *"Systems Manager's instance management role is not configured for account"* | The SSM agent got no credentials from an instance role | Attach the role (Actions → Security → Modify IAM role), check it has `AmazonSSMManagedInstanceCore`, reboot |
| `start-session` fails with `TargetNotConnected` | `--region` is not the instance's region, or the agent isn't online yet | Use the instance's region; wait until Systems Manager → Fleet Manager shows it online |
| `SessionManagerPlugin is not found` | The plugin isn't installed on your machine | Install it (link in step 6) |
| Proxy log: *"Unable to locate credentials"* | Metadata hop limit is 1 | Actions → Instance settings → Modify instance metadata options, set it to 2, then `sudo docker compose restart proxy` |
| *"P1001 ... fe_sendauth: no password supplied"* | `DATABASE_URL` reached the proxy without a password, from a misspelled variable or hidden characters pasted into the file | `sudo docker compose config \| grep -E 'DATABASE_URL\|POSTGRES_PASSWORD'` shows both resolved values; they must match |
| *"password authentication failed"* | `.env` changed after Postgres first started | `sudo docker compose down -v`, then `up -d --wait` |
| Bedrock `AccessDeniedException` | Model access not enabled, the inline policy is missing, or the account's quota for the model is 0 | Test in the Bedrock playground; check the role; ask AWS support to raise the quota |
| `docker compose up` can't pull an image | No route to the internet | Public subnet with a public IP, or a private subnet with a NAT gateway |

Clean up, from the instance and then the console:

```bash
cd /opt/litellm-tutorial/examples/ec2
sudo docker compose down -v                        # containers, network and the pgdata volume
```

Then terminate the instance, and delete the security group and the IAM role.

### How it works

LiteLLM's own [architecture document](https://github.com/BerriAI/litellm/blob/v1.110.2/ARCHITECTURE.md) sums it up in one sentence: the proxy (which the project also calls the AI gateway) uses the SDK for every LLM call. The proxy adds authentication, rate limits, budgets and routing. The SDK makes the provider calls, translates requests and responses, and handles streaming. This subsection is a simplified version of that document and of the docs page [Life of a Request](https://docs.litellm.ai/docs/proxy/architecture). Names and numbers are checked against the installed 1.110.2.

```mermaid
%% fig: overview
flowchart LR
    C1["OpenAI or Anthropic SDK,<br/>curl, any HTTP client"] --> GW
    PY["Your Python code"] --> RT
    subgraph GW["LiteLLM proxy (AI gateway)"]
        AUTH["Virtual keys<br/>budgets, rate limits"] --> HOOKS["Hooks<br/>guardrails, skills"]
    end
    HOOKS --> RT
    subgraph SDK["LiteLLM SDK"]
        RT["Router<br/>load balancing, retries, fallbacks"] --> CORE["completion()<br/>provider adapters"]
    end
    CORE --> P["Providers<br/>Anthropic, OpenAI, Bedrock, ..."]
    GW -.- DB[("Redis + Postgres")]
```

A request passes through up to three layers. Code that uses the SDK directly starts at the second:

| Layer | What it does | Where it lives in the source |
| --- | --- | --- |
| **Proxy** (optional) | Checks the virtual key and its budget, applies rate limits and hooks such as guardrails, then hands the request to the router. After the reply it records spend and logs. | `proxy/`: `proxy_server.py` for the endpoints, `auth/` for keys, `hooks/` |
| **Router** (optional in the SDK) | Picks one deployment from a model group, spreads load, retries, and falls back to another group when a call fails. | `router.py` is the Python `Router` API. Since 1.110.0 the registry, selection, retries, fallbacks and cooldowns run in a Rust core (`router_rust/`, compiled into `rust_bridge/_native`); the strategies are still Python, in `router_strategy/` |
| **SDK core and provider adapters** | `completion()` works out the provider from the model string, the provider's adapter translates the OpenAI-shaped request, httpx sends it (OpenAI and Azure OpenAI go through the `openai` SDK instead), the adapter translates the reply back, and the core prices it. Callbacks (logging, metrics) run afterwards, off the request path. | `main.py`, `llms/<provider>/chat/transformation.py`, `integrations/` |

The provider adapters are LiteLLM's **translation layer**. Each provider has a config class with `transform_request()` (OpenAI format to the provider's format) and `transform_response()` (back again), and a handler calls them: many providers share one HTTP handler (`BaseLLMHTTPHandler`), while Anthropic, Bedrock, Azure and Vertex AI each have their own. The next subsection, "How LiteLLM reaches a provider", follows one call through the adapter step by step.

#### The life of a request through the proxy

```mermaid
%% fig: life
sequenceDiagram
    participant C as Client
    participant PX as Proxy
    participant RT as Router
    participant S as SDK + adapter
    participant P as Provider
    participant ST as Redis / Postgres
    C->>PX: POST /v1/chat/completions, Bearer virtual key
    PX->>ST: key valid and under budget? (cache first)
    PX->>PX: rate limits, pre-call hooks
    PX->>RT: model group "chat"
    RT->>S: one deployment
    S->>P: provider's own format
    P-->>S: reply
    S-->>PX: OpenAI shape + cost
    PX-->>C: response + x-litellm-response-cost
    PX--)ST: after the reply: spend, logs, counters
```

1. **The client sends an OpenAI-style request** with a virtual key the proxy issued.
2. **The key is checked**: does it exist, is it under budget, may it use this model? The proxy looks in its in-memory cache, then Redis, and reads Postgres only on a cache miss. That lookup is the only database access on the request path.
3. **Rate limits and hooks.** The rpm/tpm limits for the key, user, team and the whole proxy are checked (in Redis when several proxies share the limits, section 21). Pre-call hooks such as guardrails and skill injection run next.
4. **The router** picks a deployment of the requested model group, as described below.
5. **The SDK** translates the request, calls the provider, translates the reply and works out its cost.
6. **The client gets the reply**, with the cost in the `x-litellm-response-cost` header.
7. **After the reply, in the background**, callbacks send logs to their destinations, the rate-limit counters are updated, and spend is queued and written to Postgres in batches, every 10–15 seconds in 1.110.2 (`proxy_batch_write_at`). That is why `/key/info` can lag a few seconds behind (section 13).

#### Inside the router: fallbacks wrap retries

```mermaid
%% fig: router
flowchart LR
    IN["router.acompletion()"] --> FB["with fallbacks<br/>on failure: next model group"]
    FB --> RE["with retries<br/>on failure: another deployment<br/>in the same group"]
    RE --> CALL["litellm.acompletion()<br/>one deployment"]
    CALL --> PR["Provider"]
```

A **model group** is every deployment that shares one `model_name`, for example the same model in two regions. Each call is wrapped twice. The inner wrapper retries a failed call on a healthy deployment in the same group. The outer wrapper, once the retries are used up, moves to the next group in `fallbacks`. Sections 6 and 7 show both, and section 14 adds routers that choose the group itself.

#### Where the state lives

The SDK keeps its state in your process's memory unless you point a `Router` or cache at Redis. The proxy shares state between its replicas through two stores:

| Store | What the proxy keeps there |
| --- | --- |
| **In memory** | A first-level cache of keys, counters and cooldowns, per process. Enough for a single proxy without Redis. |
| **Redis** (optional) | Rate-limit counters, a key cache, tpm/rpm per deployment, deployment cooldowns, the response cache, and queued spend. Needed when several proxy replicas must agree. |
| **Postgres** (needed for keys) | Virtual keys, users, teams, budgets and spend logs, plus everything registered at runtime: models, MCP servers, skills and agents. |

### How LiteLLM reaches a provider

LiteLLM holds no models. For most providers it builds the provider's own HTTP request itself, sends it with `httpx`, and turns the reply back into OpenAI shape. The exceptions are OpenAI and Azure OpenAI, which go through the `openai` SDK; `boto3` and `google-auth` are used only to obtain credentials. One `completion()` call goes through these steps:

| Step | What happens | Example: `anthropic/claude-haiku-5-5` | Example: `bedrock/us.anthropic.claude-haiku-5-5` | Example: `azure_ai/claude-haiku-5-5` (Microsoft Foundry) | Example: `vertex_ai/claude-haiku-5-5` (Google Vertex AI) |
| --- | --- | --- | --- | --- | --- |
| 1. Parse the model string | The prefix picks the provider adapter; the rest is the provider's model ID (`litellm.get_llm_provider()` does this) | Provider `anthropic`, ID `claude-haiku-5-5` | Provider `bedrock`, ID `us.anthropic.claude-haiku-5-5` | Provider `azure_ai`, ID `claude-haiku-5-5`; `claude` in the ID selects the Anthropic-on-Azure adapter | Provider `vertex_ai`, ID `claude-haiku-5-5`; `claude` in the ID selects the Anthropic-on-Vertex adapter |
| 2. Map the parameters | OpenAI parameters are renamed to the provider's; one the model doesn't accept raises `UnsupportedParamsError`, or is dropped with `drop_params=True` | `max_tokens` stays `max_tokens` | `max_tokens` becomes `inferenceConfig.maxTokens` | `max_tokens` stays `max_tokens`: Foundry serves Claude with Anthropic's Messages API | `max_tokens` stays `max_tokens`: Vertex takes Anthropic's Messages body, plus `anthropic_version: vertex-2023-10-16`; the model ID moves from the body into the URL |
| 3. Build the request | Messages, system prompt and tools are rewritten into the provider's body, and the URL is the provider's base plus its own path | `POST https://api.anthropic.com/v1/messages` | `POST https://bedrock-runtime.<region>.amazonaws.com/model/<id>/converse` | `POST https://<resource>.services.ai.azure.com/anthropic/v1/messages`; `api_base` or `AZURE_AI_API_BASE` names your resource | `POST https://<location>-aiplatform.googleapis.com/v1/projects/<project>/locations/<location>/publishers/anthropic/models/claude-haiku-5-5:rawPredict` (`:streamRawPredict` when streaming; location `global` uses `aiplatform.googleapis.com`) |
| 4. Authenticate | The adapter finds the credential and attaches it the way the provider expects | `x-api-key: <ANTHROPIC_API_KEY>` | An AWS SigV4 signature, made with boto3 credentials for the region | A Foundry API key (sent as `api-key` and `x-api-key`), or a Microsoft Entra ID token as `Authorization: Bearer` | A short-lived Google OAuth2 access token as `Authorization: Bearer`, minted by `google-auth` from Application Default Credentials or `vertex_credentials` |
| 5. Send | One HTTPS request (or a stream) to the provider | Anthropic's public API | Bedrock in your AWS account and region | Your Claude deployment in your Azure subscription and region | Vertex AI in your Google Cloud project, in the location you choose (`vertex_location`, default `us-central1`) |
| 6. Translate the reply | The body becomes an OpenAI `ModelResponse` with `usage`; provider errors become OpenAI-style exceptions (`RateLimitError`, `AuthenticationError`, ...) | Anthropic content blocks → `choices[0].message` | Converse output → `choices[0].message`; `ThrottlingException` → `RateLimitError` | Anthropic content blocks → `choices[0].message`; Azure's 429 → `RateLimitError` | Anthropic content blocks → `choices[0].message`; Vertex's 429 → `RateLimitError` |
| 7. Price and report | Token counts × the price table (bundled with LiteLLM; `LITELLM_LOCAL_MODEL_COST_MAP=True` keeps it offline) give `response_cost`; callbacks run | Anthropic's list price | Bedrock's price for that ID form (`us.` costs more than `global.`) | The same as Anthropic's list price in LiteLLM's 1.110.2 price table | A regional location costs 10% more than `global` in LiteLLM's 1.110.2 price table, as with Bedrock's `us.` and `global.` profiles |

Steps 1, 5 and 7 are the same for every provider and belong to the SDK core. Steps 2, 3, 4 and 6 are the **provider adapter**: code in `litellm/llms/<provider>/`, one adapter per provider (and per route, such as Bedrock's Converse and Invoke). Each adapter implements the same methods: `map_openai_params` (step 2), `get_complete_url` and `transform_request` (step 3), `validate_environment` or `sign_request` (step 4), and `transform_response` and `get_error_class` (step 6). Adding a provider to LiteLLM means writing an adapter; nothing else changes. In 1.110.2:

| | Anthropic adapter | Bedrock adapter (Converse route) | Azure adapter (Claude in Foundry) | Google adapter (Claude on Vertex AI) |
| --- | --- | --- | --- | --- |
| Code | `AnthropicConfig` in `llms/anthropic/chat/transformation.py` | `AmazonConverseConfig` in `llms/bedrock/chat/converse_transformation.py` | `AzureAnthropicConfig` in `llms/azure_ai/anthropic/transformation.py`, a subclass of `AnthropicConfig` | `VertexAIAnthropicConfig` in `llms/vertex_ai/vertex_ai_partner_models/anthropic/transformation.py`, a subclass of `AnthropicConfig` |
| Run by | `AnthropicChatCompletion` in `llms/anthropic/chat/handler.py`, Anthropic's own handler (many other providers share `BaseLLMHTTPHandler`) | `BedrockConverseLLM`, Bedrock's own handler, which inherits AWS credential lookup and SigV4 signing from `BaseAWSLLM` | `AzureAnthropicChatCompletion`, its own handler | `VertexAIPartnerModels`, which gets the Google access token and builds the Vertex URL, then hands the call to Anthropic's own handler, `AnthropicChatCompletion` |
| Credential | Reads `api_key` or `ANTHROPIC_API_KEY`, sends it as `x-api-key` | Gets credentials from boto3 (profile, role, STS) and signs each request for its region | Reads `api_key` or `AZURE_AI_API_KEY`, or an Entra ID token (`azure_ad_token` or `AZURE_AD_TOKEN`) | `vertex_credentials` or `VERTEXAI_CREDENTIALS` (service-account JSON or a workload identity federation config); otherwise Application Default Credentials: `GOOGLE_APPLICATION_CREDENTIALS`, `gcloud auth application-default login`, or the workload's service account (GKE Workload Identity, Cloud Run). Project and location come from `vertex_project`/`VERTEXAI_PROJECT` and `vertex_location`/`VERTEXAI_LOCATION` |

The **proxy** runs the same seven steps, with its own work around them. It first checks the caller's key (master key or virtual key), looks up the requested alias in its `model_list`, and lets its Router pick one deployment of that alias. That deployment's `litellm_params` (`model`, `api_key`, `aws_region_name`, ...) become the arguments of the call above. Afterwards it records spend against the key, team and user, and returns the reply with `x-litellm-*` headers.

The sequence below follows one request through the proxy to Bedrock, the setup with the most moving parts:

```mermaid
sequenceDiagram
    participant App as Any app (OpenAI client)
    participant PX as Proxy server
    participant AD as Bedrock adapter (inside the litellm SDK)
    participant CR as AWS credentials (boto3 chain / STS)
    participant BR as AWS Bedrock
    App->>PX: POST /v1/chat/completions, model=chat, Bearer sk-...
    Note over PX: check the key, alias → deployment (Router)
    PX->>AD: completion(model="bedrock/us.anthropic...", aws_region_name="us-west-2")
    Note over AD: map params, build the Converse body
    AD->>CR: get credentials
    CR-->>AD: temporary keys (cached until they expire)
    AD->>BR: POST /model/us.anthropic.claude-haiku-5-5/converse, SigV4 for us-west-2
    BR-->>AD: Converse reply, or ThrottlingException
    Note over AD: OpenAI shape, or RateLimitError
    AD-->>PX: ModelResponse + response_cost
    Note over PX: record spend for the key, team and user
    PX-->>App: 200 chat.completion + x-litellm-* headers
```

The other setups are this sequence with a lane removed or swapped:

- **SDK instead of proxy:** your app calls the SDK directly, so the proxy server's lane disappears. There is no key check, no alias lookup unless you use a `Router`, and no spend database. The app gets the reply as a Python object.
- **Provider directly instead of Bedrock:** the Anthropic adapter takes the Bedrock adapter's place and there is no credentials call. It reads `ANTHROPIC_API_KEY` from the environment, or `api_key` from the deployment, and sends `POST https://api.anthropic.com/v1/messages` with an `x-api-key` header.

So **direct provider vs cloud platform** is decided by the model string, which selects the adapter and therefore which credential LiteLLM looks for. **SDK vs proxy** decides where steps 1–7 run, and so where that credential has to be. That gives four setups:

```mermaid
flowchart LR
    subgraph SDKAPP["Your Python app (SDK): holds the API key or AWS identity"]
        CORE["litellm core<br/>completion(), Router<br/>cost, callbacks"] --> A1["Anthropic adapter<br/>AnthropicConfig"]
        CORE --> B1["Bedrock adapter<br/>AmazonConverseConfig"]
    end
    CL["Any app<br/>OpenAI client + virtual key"] --> SRV
    subgraph PROXY["LiteLLM proxy: holds the API key or AWS identity"]
        SRV["Proxy server<br/>key check, alias → deployment<br/>record spend"] --> A2["Anthropic adapter<br/>AnthropicConfig"]
        SRV --> B2["Bedrock adapter<br/>AmazonConverseConfig"]
    end
    A1 -->|"x-api-key"| AN["Anthropic API"]
    A2 -->|"x-api-key"| AN
    B1 -->|"SigV4"| BR["AWS Bedrock<br/>in your account and region"]
    B2 -->|"SigV4"| BR
```

**SDK, provider directly.** Your process needs the vendor's API key. Each adapter reads its own environment variable (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, ...), or takes `api_key=` per call:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

```python
litellm.completion(model="anthropic/claude-haiku-5-5", messages=msgs)
```

**SDK, through AWS Bedrock.** There is no API key. Your process needs AWS credentials that boto3 can find, a region, and an AWS account where the model is enabled:

```bash
aws sso login --profile <profile>                   # or a workload role on EKS / ECS / EC2
export AWS_PROFILE=<profile> AWS_REGION=us-west-2
```

```python
litellm.completion(model="bedrock/us.anthropic.claude-haiku-5-5", messages=msgs)
```

In AWS, also enable access to the model in the Bedrock console for each region it can run in, and give the identity `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`. LiteLLM 1.110.2 installs `boto3` itself and needs it to sign Bedrock requests. The notebooks and exercises use this setup.

**Proxy, provider directly.** The vendor key moves from the app to the proxy. The proxy's `config.yaml` maps an alias to the provider model and reads the key from the proxy's environment; the app holds only a key the proxy issued:

```yaml
model_list:
  - model_name: chat
    litellm_params:
      model: anthropic/claude-haiku-5-5
      api_key: os.environ/ANTHROPIC_API_KEY       # read from the proxy's environment
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

```bash
export ANTHROPIC_API_KEY=sk-ant-... LITELLM_MASTER_KEY=sk-master-...
uv run litellm --config config.yaml --port 4000
```

**Proxy, through AWS Bedrock.** The AWS identity moves from the app to the proxy. The config names the Bedrock model and region, and the proxy process gets AWS credentials the same way the SDK does: an SSO profile on a laptop, Pod Identity or IRSA on EKS, a task role on ECS:

```yaml
model_list:
  - model_name: chat
    litellm_params:
      model: bedrock/us.anthropic.claude-haiku-5-5
      aws_region_name: us-west-2                   # no key: the proxy's AWS identity signs the request
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

```bash
export AWS_PROFILE=<profile> LITELLM_MASTER_KEY=sk-master-...
uv run litellm --config config.yaml --port 4000
```

In both proxy setups, the app's side is identical, and it can't tell which one is behind the alias:

```python
client = OpenAI(base_url="http://localhost:4000", api_key="sk-<virtual or master key>")
client.chat.completions.create(model="chat", messages=msgs)
```

| | Provider directly | Through AWS Bedrock |
| --- | --- | --- |
| Model string | `anthropic/<model id>` | `bedrock/<model id or inference profile>` |
| Credential | Vendor API key | AWS identity (profile, role, workload identity), signed per region |
| Also required | An account with the vendor | Model access enabled in Bedrock, and IAM permission to invoke it |
| SDK: the credential lives in | Every app process | Every app process |
| Proxy: the credential lives in | The proxy only | The proxy only |
| Covered in | Sections 1 and 12, "Directly to a model provider" | Setup's quick start, section 1's "AWS Bedrock from the SDK" and "Amazon Bedrock Mantle", section 12's Bedrock subsection, and the notebooks; Azure and Google Vertex AI have their own subsections in section 12 |

### Offline by default

The examples run offline with no API keys and no cost. LiteLLM has test hooks built in:

| Hook | What it does |
| --- | --- |
| `mock_response="text"` | Returns that text as the model's reply |
| `mock_response=SomeLiteLLMError(...)` | Raises that error, as if the provider had failed |
| `mock_tool_calls=[...]` | Returns those tool calls |
| `mock_delay=1.0` | Waits that many seconds before replying |
| `mock_testing_fallbacks=True` | Fails the primary model so the fallbacks run. `Router` and proxy only (section 7); plain `completion()` ignores it |

A mocked call still goes through LiteLLM's real request handling: parameter mapping, usage and cost calculation, callbacks, caching and the router. The only part skipped is the HTTP call to the provider. The hooks are also useful in your own unit tests.

The helper in [`examples/_mock.py`](examples/_mock.py) adds the mock argument unless `LIVE=1` is set:

```python
LIVE = os.environ.get("LIVE") == "1"

def mock(text):
    return {} if LIVE else {"mock_response": text}
```

To call real models, set the provider keys and `LIVE=1`:

```bash
export ANTHROPIC_API_KEY=... OPENAI_API_KEY=... GEMINI_API_KEY=...
LIVE=1 uv run python 01_first_call.py
```

I ran everything offline; I did not run the `LIVE=1` path. Real answers will differ from the mocked ones shown here, and so will token counts and costs.

### Running the SDK sections as notebooks

Sections 1–11 are also available as Jupyter notebooks in [`notebooks/`](notebooks/). Unlike the scripts, the notebooks call every model through **AWS Bedrock**, using your AWS profile's temporary credentials. A git-ignored `.env.local` holds only settings (profile name, region, model IDs, the `LIVE` switch), so there is no secret in the notebooks or in that file:

```bash
uv sync --group notebooks                # adds python-dotenv, jupyterlab, ipykernel, pandas, and pins boto3
cd notebooks
cp .env.local.example .env.local         # set AWS_PROFILE; set LIVE=1 for real calls
aws sso login --profile <profile>        # or `aws login --profile <profile>` for console-login profiles
uv run jupyter lab
```

| Notebook | Sections |
| --- | --- |
| [`00_credentials.ipynb`](notebooks/00_credentials.ipynb) | How `.env.local` is loaded; live check that the profile works and the models are enabled in your region |
| [`01_basics.ipynb`](notebooks/01_basics.ipynb) | 1–3: one call, streaming, async batches. Section 1's provider subsections are scripts only (`examples/01c`–`01f`) |
| [`02_structured_output_and_tools.ipynb`](notebooks/02_structured_output_and_tools.ipynb) | 4–5 |
| [`03_errors_fallbacks_router.ipynb`](notebooks/03_errors_fallbacks_router.ipynb) | 6–7, with the Router spreading one model across two AWS regions |
| [`04_cost_caching_callbacks.ipynb`](notebooks/04_cost_caching_callbacks.ipynb) | 8–10 |
| [`05_compare_models.ipynb`](notebooks/05_compare_models.ipynb) | 11, with the results in a pandas table |

The notebooks use three Bedrock models, set in `.env.local`: `MODEL_FAST` (default `bedrock/us.anthropic.claude-haiku-5-5`), `MODEL_SMART` (`bedrock/us.anthropic.claude-opus-5-5`) and `MODEL_ALT` (`bedrock/us.amazon.nova-2-lite-v1:0`, a non-Anthropic model to show that one call shape covers different model families). The `us.` prefix makes them cross-region inference profiles; section 12's "Through a cloud platform: AWS Bedrock" explains model IDs, routes, credentials and pricing.

Each notebook's first cell imports [`notebooks/_env.py`](notebooks/_env.py). It loads `.env.local` into the environment, where boto3 finds `AWS_PROFILE` and LiteLLM finds `AWS_REGION`. It refuses to start if `.env.local` contains AWS access keys. [`notebooks/AWS_SIGN_IN.md`](notebooks/AWS_SIGN_IN.md) explains how the sign-in works and how to troubleshoot it. Variables already exported in your shell take precedence. Restart the kernel after editing the file. The notebooks are saved with outputs from an offline run; clear the outputs after a `LIVE=1` run before committing.

### Exercises and the self-test

Every section from 1 to 23 ends with exercises. Each one is a Python script that you write in [`exercises/`](exercises/). They use the same AWS Bedrock setup as the notebooks; [`exercises/README.md`](exercises/README.md) covers sign-in and `.env.local`. The ground rules:

- Start each script with `import _env`, before `import litellm`. Use `_env.FAST`, `_env.SMART` and `_env.ALT` as the models.
- Scripts that only talk to a running proxy over HTTP (most exercises in sections 12, 13, 15, 16, 19, 20 and 21) don't need `_env`; the proxy's config decides between mocked and live models.
- Each script must run offline (`LIVE=0`, the default) using the mock hooks above, and also with `LIVE=1`. Use `**_env.mock("...")` for a plain reply (`_env` is the exercises' helper; the example scripts use a separate, smaller `_mock.py`). When a turn needs a fake tool call or a fake error, build the per-turn fake arguments yourself, as [`examples/05_tool_calling.py`](examples/05_tool_calling.py) does.
- Write each **Check** as an `assert` in the script, so a clean run means the exercise is done. Some checks only hold offline because the mocked reply is fixed, and some only hold live; guard those with `if _env.LIVE:` or `if not _env.LIVE:`.
- ★ exercises practise what the section shows. ★★ exercises go further, and may need the [LiteLLM docs](https://docs.litellm.ai/) or the installed source in `.venv/lib/python3.*/site-packages/litellm/`.
- Most exercises have only a collapsed hint. Verified reference solutions for exercises 12.6–12.9, 19a.1–19c.1, 20.5 and 20.6 are in [`solutions/`](solutions/); try the exercise first. Your own scripts are git-ignored (see the exercises README).

```bash
cd exercises
uv run python ex01_1_three_models.py            # offline, free
LIVE=1 uv run python ex01_1_three_models.py     # real Bedrock calls, usually under a cent
```

When you have worked through the sections, test yourself with [`exercises/exam.html`](exercises/exam.html). Open it in a browser; it needs no server and no network. It holds 284 certification-style questions across 22 domains of LiteLLM, including AWS Bedrock, Azure, Google Vertex AI and local models (section 12), the smart routers, MCP gateway, skills and agent (A2A) gateways, prompt management and observability integrations of sections 14–18, Lens (section 19), access control, identity providers and secrets (section 20), guardrails and production hardening (section 21), context and memory management (section 22), and topics this tutorial only mentions (embeddings, pass-through routes). Practice mode explains each answer as you go. Exam mode draws 50 questions, gives you 75 minutes and needs 75% to pass, then breaks your score down by domain.

---

## 1. One call, any provider

**Use case:** write the code once and switch providers by changing a string.

### The `completion()` signature

Every SDK section calls `litellm.completion()` (or `acompletion()`, which takes the same arguments). This is its signature in LiteLLM 1.110.2, from `inspect.signature(litellm.completion)`, grouped and with long type hints shortened:

```python
def completion(
    # Required
    model: str,                          # "<provider>/<model id>", e.g. "anthropic/claude-sonnet-5-5"
    messages: list = [],                 # OpenAI-style [{"role": ..., "content": ...}]

    # Sampling and length
    temperature: float | None = None,
    top_p: float | None = None,
    n: int | None = None,
    stop=None,
    max_tokens: int | None = None,
    max_completion_tokens: int | None = None,
    presence_penalty: float | None = None,
    frequency_penalty: float | None = None,
    logit_bias: dict | None = None,
    seed: int | None = None,
    logprobs: bool | None = None,
    top_logprobs: int | None = None,
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max", "default"] | None = None,
    thinking: AnthropicThinkingParam | None = None,
    verbosity: Literal["low", "medium", "high"] | None = None,

    # Streaming (section 2)
    stream: bool | None = None,
    stream_options: dict | None = None,

    # Structured output and tools (sections 4 and 5)
    response_format: dict | type[BaseModel] | None = None,
    tools: list | None = None,
    tool_choice: str | dict | None = None,
    parallel_tool_calls: bool | None = None,
    web_search_options: OpenAIWebSearchOptions | None = None,
    functions: list | None = None,       # legacy OpenAI form of tools
    function_call: str | None = None,

    # Where the request goes and how it authenticates
    api_key: str | None = None,          # overrides the provider's env var
    base_url: str | None = None,         # same as api_base= (see below)
    api_version: str | None = None,      # Azure and similar
    extra_headers: dict | None = None,
    timeout: float | str | httpx.Timeout | None = None,

    # Other OpenAI parameters passed through where the provider supports them
    modalities=None, audio=None, prediction=None, user: str | None = None,
    safety_identifier=None, service_tier=None, store=None,
    prompt_cache_key=None, prompt_cache_retention=None, deployment_id=None,
    model_list: list | None = None, shared_session=None,
    include_server_side_tool_invocations=None, enable_json_schema_validation=None,

    **kwargs,                            # LiteLLM-specific options, below
) -> ModelResponse | CustomStreamWrapper   # CustomStreamWrapper when stream=True
```

Several options this tutorial uses are not named parameters; they arrive through `**kwargs`:

| Keyword | What it does | Section |
| --- | --- | --- |
| `api_base` | Base URL of the provider endpoint (`base_url` is an alias) | 1 |
| `custom_llm_provider` | Picks the provider when the model string has no prefix | 1 |
| `mock_response`, `mock_tool_calls`, `mock_delay` | Test hooks (see Setup). `mock_testing_fallbacks` is a `Router` hook, not a `completion()` one (section 7) | all |
| `num_retries`, `fallbacks` | Retries and fallback models | 6 |
| `caching` | Turns the cache on or off for this call | 9 |
| `metadata` | Free-form dict passed to callbacks | 10 |

Parameters that a provider does not support raise `UnsupportedParamsError` unless you set `litellm.drop_params = True` or pass `drop_params=True`.

**`max_tokens` vs `max_completion_tokens`.** Both cap the tokens the model generates; neither limits the input. `max_tokens` is OpenAI's original name. OpenAI added `max_completion_tokens` for its reasoning models, and it counts hidden reasoning tokens as well as the visible reply. OpenAI's reasoning models reject `max_tokens`. Anthropic has a single field, `max_tokens`, which already includes extended-thinking tokens. This is what LiteLLM sends, captured with the fake server from [`01b_api_key_and_base.py`](examples/01b_api_key_and_base.py):

| You pass | `openai/gpt-4o-mini` | `openai/o3-mini` (reasoning) | `anthropic/claude-sonnet-5-5` |
| --- | --- | --- | --- |
| `max_tokens=100` only | `max_tokens: 100` | `max_completion_tokens: 100` | `max_tokens: 100` |
| `max_completion_tokens=100` only | `max_completion_tokens: 100` | `max_completion_tokens: 100` | `max_tokens: 100` |
| `max_tokens=300, max_completion_tokens=100` | both, unchanged | `max_completion_tokens: 100` | `max_tokens: 100` |

When you pass both, `max_completion_tokens` wins for o3-mini and Anthropic, whichever value is larger. `max_tokens` is dropped without a warning. Only gpt-4o-mini receives both values, and then OpenAI decides which one applies. Pass one of them; `max_completion_tokens` means "all generated tokens" for every provider. With reasoning or thinking on, set the cap well above the reply length you expect, or the thinking can use it all up and the reply comes back cut short with `finish_reason == "length"`.

[`01_first_call.py`](examples/01_first_call.py)

```python
from litellm import completion, completion_cost

MODELS = [
    "anthropic/claude-sonnet-5-5",
    "openai/gpt-4o-mini",
    "gemini/gemini-2.5-flash",
]
messages = [{"role": "user", "content": "Say hello in French, in three words."}]

for model in MODELS:
    resp = completion(model=model, messages=messages, max_tokens=50,
                      **mock("Bonjour à tous !"))
    print(f"{model:30} -> {resp.choices[0].message.content!r}")
    print(f"{'':30}    tokens in/out={resp.usage.prompt_tokens}/"
          f"{resp.usage.completion_tokens}  cost=${completion_cost(resp):.8f}")
```

```text
anthropic/claude-sonnet-5-5    -> 'Bonjour à tous !'
                                  tokens in/out=10/20  cost=$0.00022000
openai/gpt-4o-mini             -> 'Bonjour à tous !'
                                  tokens in/out=10/20  cost=$0.00001350
gemini/gemini-2.5-flash        -> 'Bonjour à tous !'
                                  tokens in/out=10/20  cost=$0.00005300
```

What to notice:

- **The prefix picks the provider.** In `anthropic/claude-sonnet-5-5`, `anthropic/` selects the adapter and the rest is the provider's own model ID. LiteLLM reads that provider's standard env var for the key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`). You can also pass `api_key=` and `api_base=` per call; see the worked example below.
- **The response is always OpenAI-shaped:** `resp.choices[0].message.content` and `resp.usage`, whichever provider answered.
- **Cost is computed for you** from LiteLLM's price table. By default LiteLLM downloads the current table from GitHub when it is imported and falls back to the copy bundled with the package; `LITELLM_LOCAL_MODEL_COST_MAP=True` (set in Setup) pins it to the bundled copy. Mocked calls report a fixed 10 tokens in and 20 out, so here the cost differences come from price alone.
- **Translation goes both ways.** Anthropic's API takes the system prompt as a separate field, and `max_tokens` is required. LiteLLM moves a `{"role": "system"}` message into that field for you. The required `max_tokens` is filled from whichever of `max_tokens` or `max_completion_tokens` you pass (see the table above). If you pass neither, LiteLLM sends the model's maximum output from its bundled model table (128000 for `claude-sonnet-5-5`). For a model missing from that table, it sends `DEFAULT_ANTHROPIC_CHAT_MAX_TOKENS`, an env var that defaults to 128000. Both are high enough that a runaway reply can be very long and expensive, so set a cap yourself.

### Per-call `api_key=` and `api_base=`

**Use case:** one process talks to several accounts or endpoints: a key per team or customer, a self-hosted vLLM server, a company gateway, or a regional endpoint. Env vars hold one key per provider; per-call arguments let each request choose.

- `api_key=` replaces the env var for that call only.
- `api_base=` (or `base_url=`) replaces the provider's default URL. LiteLLM still appends the provider's own path (`/chat/completions` for OpenAI, `/v1/messages` for Anthropic), so give the base, not the full path.

The mock hooks skip the HTTP call, so they can't show where a request goes. [`01b_api_key_and_base.py`](examples/01b_api_key_and_base.py) instead starts a small fake provider on `127.0.0.1` that prints each request it receives, then answers in OpenAI or Anthropic format. It needs no keys and calls no provider (with `LITELLM_LOCAL_MODEL_COST_MAP=True` set, as in Setup, it uses no network at all), and `LIVE` has no effect on it.

The server uses only Python's standard library: `HTTPServer` and `BaseHTTPRequestHandler` from `http.server`, run on a background thread. `FakeProvider` is the request handler: its `do_POST` prints the path, the auth header and the model it received, then returns a canned reply in OpenAI or Anthropic format, chosen by the path. Port `0` lets the OS pick a free port.

```python
"""Per-call api_key= and api_base=: where the request goes and which key it carries."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from litellm import completion

OPENAI_REPLY = {
    "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "fake",
    "choices": [{"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": "Bonjour à tous !"}}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
}
ANTHROPIC_REPLY = {
    "id": "msg_1", "type": "message", "role": "assistant", "model": "fake",
    "content": [{"type": "text", "text": "Bonjour à tous !"}],
    "stop_reason": "end_turn", "usage": {"input_tokens": 12, "output_tokens": 5},
}


class FakeProvider(BaseHTTPRequestHandler):
    """Answer like OpenAI or Anthropic, depending on the path, and print what arrived."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        auth = self.headers.get("Authorization") or f"x-api-key: {self.headers.get('x-api-key')}"
        print(f"  server got  POST {self.path}  auth={auth!r}  model={body['model']!r}")
        reply = ANTHROPIC_REPLY if self.path.endswith("/messages") else OPENAI_REPLY
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), FakeProvider)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_port}"
messages = [{"role": "user", "content": "Say hello in French, in three words."}]

os.environ["OPENAI_API_KEY"] = "sk-from-env"

print("1. Key from the env var, base URL per call")
completion(model="openai/gpt-4o-mini", messages=messages, api_base=f"{BASE}/v1")

print("2. Key per call overrides the env var")
completion(model="openai/gpt-4o-mini", messages=messages,
           api_base=f"{BASE}/v1", api_key="sk-team-a")

print("3. Any OpenAI-compatible server (vLLM, LM Studio, a gateway), model ID passed through")
resp = completion(model="openai/meta-llama/Llama-3.1-8B-Instruct", messages=messages,
                  api_base=f"{BASE}/v1", api_key="local-anything")
print(f"  reply={resp.choices[0].message.content!r}  usage={resp.usage.prompt_tokens}/"
      f"{resp.usage.completion_tokens}")

print("4. Same arguments, Anthropic adapter: different path and auth header")
resp = completion(model="anthropic/claude-sonnet-5-5", messages=messages, max_tokens=50,
                  api_base=BASE, api_key="sk-ant-per-call")
print(f"  reply={resp.choices[0].message.content!r}  (OpenAI-shaped response)")

server.shutdown()
```

```text
1. Key from the env var, base URL per call
  server got  POST /v1/chat/completions  auth='Bearer sk-from-env'  model='gpt-4o-mini'
2. Key per call overrides the env var
  server got  POST /v1/chat/completions  auth='Bearer sk-team-a'  model='gpt-4o-mini'
3. Any OpenAI-compatible server (vLLM, LM Studio, a gateway), model ID passed through
  server got  POST /v1/chat/completions  auth='Bearer local-anything'  model='meta-llama/Llama-3.1-8B-Instruct'
  reply='Bonjour à tous !'  usage=12/5
4. Same arguments, Anthropic adapter: different path and auth header
  server got  POST /v1/messages  auth='x-api-key: sk-ant-per-call'  model='claude-sonnet-5-5'
  reply='Bonjour à tous !'  (OpenAI-shaped response)
```

What to notice:

- **Case 1 vs 2:** same env var, but the per-call key wins. Nothing global changes, so the next call without `api_key=` goes back to the env var.
- **Case 3:** the `openai/` prefix means "speak the OpenAI protocol", not "call OpenAI". With `api_base=` it points at any compatible server. The provider strips only the prefix, so the model ID keeps its inner `/`. The usage (12/5) is the server's own count, not the mock's fixed 10/20.
- **Case 4:** the same two arguments, but the Anthropic adapter sends `x-api-key` instead of `Authorization: Bearer` and posts to `/v1/messages`. You don't handle that difference, and the response comes back OpenAI-shaped.
- **Keep keys out of source code.** The literal keys here are fake and only show where the value ends up. In real code, read each key from a secrets manager or an env var with a different name, and pass it in: `api_key=os.environ["TEAM_A_OPENAI_KEY"]`.
- The Router (section 7) and the proxy config (section 12) take the same `api_key` and `api_base` per deployment, so you set them once there instead of on every call.

### Provider adapters in detail

**Use case:** you call a provider from your own Python code and need to know what it accepts, what it actually receives, and what you get back.

`completion()` takes the same arguments for every provider, but four things still change from one provider to the next, and your code sees all four:

| What changes | Why it matters | How to see it |
| --- | --- | --- |
| The model string and the credential | They pick the adapter, the URL and what LiteLLM looks for in the environment | `litellm.get_llm_provider()` and `litellm.validate_environment()` (exercise 1.2) |
| Which OpenAI parameters a model accepts | One it doesn't accept raises `UnsupportedParamsError` before anything is sent, unless you set `drop_params` | `litellm.get_supported_openai_params(model=..., custom_llm_provider=...)` |
| Where an accepted parameter lands | The same `response_format` becomes a native JSON-schema setting for one model and a forced tool call for another, with a different token bill | The request body |
| What comes back | Reasoning text, reasoning tokens and cost are only as good as what the provider reports and what LiteLLM's price table knows | `message.reasoning_content`, `usage`, `response._hidden_params["response_cost"]` |

The next four subsections take four adapters in detail. AWS Bedrock and Amazon Bedrock Mantle are cloud platforms; Ollama and vLLM run models you host yourself. The fifth covers the other major providers more briefly. Section 12 covers the same providers from the proxy's side. It has the wire-level details: Bedrock's model ID forms, request signing and assumed roles, and the identities for Azure and Vertex AI.

**Seeing the request without sending it.** The four examples share a small helper, [`examples/_wire.py`](examples/_wire.py). It registers a callback (section 10) whose `log_pre_api_call` hook receives the URL, headers and body LiteLLM is about to send. `send()` makes a call and returns the response, or the exception, together with that request:

```python
class WireTap(CustomLogger):
    """Keep the URL, headers and body of the last request LiteLLM was about to send."""

    def log_pre_api_call(self, model, messages, kwargs):
        extra = kwargs.get("additional_args") or {}
        body = extra.get("complete_input_dict") or {}
        self.last = {"url": extra.get("api_base") or "",
                     "headers": {k.lower(): str(v) for k, v in (extra.get("headers") or {}).items()},
                     "body": json.loads(body) if isinstance(body, (str, bytes)) else dict(body)}
```

Offline, `_wire.py` also points `HTTPS_PROXY` at a closed local port. The request is built and signed for real, then fails to connect, so nothing leaves your machine; the output says `not sent (offline)`. With `LIVE=1`, the requests go out and you see the real replies next to what was sent. `auth()` prints how a request authenticates (`SigV4 <region>/<service>`, `Bearer`, `x-api-key`), never the credential itself.

Import `_wire` before `litellm`: it sets `LITELLM_LOCAL_MODEL_COST_MAP` (Setup), and LiteLLM reads that variable when it is imported. My first version imported it second. LiteLLM then downloaded the current price table from GitHub, and Claude Haiku 4.5 on Mantle was priced 10% higher than in the table bundled with 1.110.2.

### AWS Bedrock from the SDK

Section 12's Bedrock subsection explains the model string (`bedrock/[route/]<model id>`), the model ID forms (base IDs, `us.`, `eu.` and `global.` inference profiles, ARNs), the Converse and Invoke routes, and the AWS identity LiteLLM signs with. This part covers what you write in Python.

**Credentials in code.** With no `aws_*` arguments, LiteLLM uses boto3's default chain: environment variables, `AWS_PROFILE`, then the workload's role. Each row of section 12's identity table can also be passed per call, so one process can use several identities and regions:

```python
completion(model="bedrock/us.anthropic.claude-haiku-5-5", messages=msgs)              # default chain
completion(model="bedrock/eu.anthropic.claude-haiku-5-5", messages=msgs,
           aws_region_name="eu-west-1")                                               # another region
completion(model="bedrock/us.anthropic.claude-haiku-5-5", messages=msgs,
           aws_role_name="arn:aws:iam::<account>:role/team-b", aws_session_name="team-b")  # another account
completion(model="bedrock/us.anthropic.claude-haiku-5-5", messages=msgs,
           aws_profile_name="<profile>")                                              # a named profile
```

A Bedrock API key goes in as `api_key=` or `AWS_BEARER_TOKEN_BEDROCK`. It is sent as a bearer token instead of a signature.

**OpenAI parameters become Converse fields.** LiteLLM sends most chat models to Bedrock's Converse API. This is where each parameter ends up, from the example below and its live run:

| You pass | In the Converse request | Notes |
| --- | --- | --- |
| A `system` message | Top-level `system`, a list of text blocks | Other messages become content blocks |
| `max_tokens` or `max_completion_tokens` | `inferenceConfig.maxTokens` | |
| `stop`, `temperature`, `top_p` | `inferenceConfig.stopSequences`, `.temperature`, `.topP` | Claude Haiku 5.5 accepts only `temperature=1` and no `top_p`: `UnsupportedParamsError` |
| `tools`, `tool_choice` | `toolConfig.tools[].toolSpec`, `toolConfig.toolChoice` | `"required"` becomes `{"any": {}}` |
| `response_format` with a JSON schema | Claude: `outputConfig.textFormat`, Bedrock's native structured output. Nova: a forced tool named `json_tool_call` | Either way the JSON comes back in `message.content` |
| `reasoning_effort` | Claude Haiku 5.5: `additionalModelRequestFields.thinking = {"type": "adaptive", "display": "summarized"}` plus `output_config.effort`. Nova: `additionalModelRequestFields.reasoningConfig.maxReasoningEffort` | |
| `thinking={"type": "enabled", "budget_tokens": N}` | Claude Haiku 5.5: adaptive thinking with `effort: "low"` | The budget is not sent |
| `service_tier` | `serviceTier.type` | Only `priority`, `flex`, `default` and `auto` (sent as `default`), in lower case; any other value is dropped without an error (section 12, "Service tiers") |
| `stream=True` | `POST /model/<id>/converse-stream` | |
| `seed` | Nothing | `UnsupportedParamsError`, or dropped with `drop_params=True` |
| `user` | Nothing | Dropped without a warning |
| `requestMetadata`, `performanceConfig`, `guardrailConfig` | Top-level fields of the same name | Bedrock's own parameters, passed through; Bedrock decides whether the model supports them. `guardrailConfig` is in section 12 |
| Any other keyword | `additionalModelRequestFields` | Nova's `top_k` becomes `additionalModelRequestFields.inferenceConfig.topK` |

[`examples/01c_bedrock.py`](examples/01c_bedrock.py) makes one call per row and prints the outcome, the Bedrock path and the body fields other than the messages:

```python
CLAUDE = "bedrock/us.anthropic.claude-haiku-5-5"
NOVA = "bedrock/us.amazon.nova-2-lite-v1:0"


def show(label, model, **kwargs):
    """Make one call; print the outcome, the Bedrock path and the body fields other than the messages."""
    resp, req = send(litellm.completion, model=model, messages=kwargs.pop("messages", MSGS), **kwargs)
    print(f"{label:36} {outcome(resp)}")
    if req:
        body = {k: v for k, v in req["body"].items() if k not in SAME}
        print(f"    POST {req['url'].split('amazonaws.com')[-1]}\n    {json.dumps(body)}")
    return resp


show("response_format: Claude", CLAUDE, max_tokens=200, response_format=CITY)
show("response_format: Nova", NOVA, max_tokens=200, response_format=CITY)
show("reasoning_effort='low': Nova", NOVA, max_tokens=2000, reasoning_effort="low")
show("seed, drop_params=True", CLAUDE, max_tokens=100, seed=7, drop_params=True)
show("top_k=5: Nova", NOVA, max_tokens=100, top_k=5)
...
```

```bash
cd examples
uv run python 01c_bedrock.py                    # offline: requests are built, not sent
LIVE=1 uv run python 01c_bedrock.py             # live: needs AWS credentials, as in Setup's quick start
```

This is the live run, in us-west-2 through an SSO profile. Offline, every request was identical and the outcome column read `not sent (offline)`, except for the three refusals, which happen before sending:

```text
== the same OpenAI parameters, two model families
max_completion_tokens, stop: Claude  'Paris.' tokens=20/6 cost=5.5e-06
    POST /model/us.anthropic.claude-haiku-5-5/converse
    {"inferenceConfig": {"stopSequences": ["END"], "maxTokens": 100}}
... and temperature: Nova            'The capital of France is **Paris**. \n\ tokens=53/57 cost=0.00017423999999999999
    POST /model/us.amazon.nova-2-lite-v1%3A0/converse
    {"inferenceConfig": {"temperature": 0.2, "stopSequences": ["END"], "maxTokens": 100}}
temperature: Claude Haiku 5.5        UnsupportedParamsError: us.anthropic.claude-haiku-5-5 does not support temperature=0.2. Only temperature
top_p: Claude Haiku 5.5              UnsupportedParamsError: us.anthropic.claude-haiku-5-5 does not support top_p=0.9. To drop unsupported pa
response_format: Claude              '{"city": "Paris"}' tokens=204/12 cost=2.9040000000000003e-05
    POST /model/us.anthropic.claude-haiku-5-5/converse
    {"inferenceConfig": {"maxTokens": 200}, "outputConfig": {"textFormat": {"type": "json_schema", "structure": {"jsonSchema": {"schema": "{\"type\": \"object\", \"properties\": {\"city\": {\"type\": \"string\"}}, \"required\": [\"city\"], \"additionalProperties\": false}", "name": "city"}}}}}
response_format: Nova                '{"city": "Paris"}' tokens=912/26 cost=0.00037246
    POST /model/us.amazon.nova-2-lite-v1%3A0/converse
    {"inferenceConfig": {"maxTokens": 200}, "toolConfig": {"tools": [{"toolSpec": {"inputSchema": {"json": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}, "name": "json_tool_call", "description": "json_tool_call"}}], "toolChoice": {"tool": {"name": "json_tool_call"}}}}
tools, tool_choice='required'        'tool call get_weather' tokens=494/40 cost=7.634e-05
    POST /model/us.anthropic.claude-haiku-5-5/converse
    {"inferenceConfig": {"maxTokens": 200}, "toolConfig": {"tools": [{"toolSpec": {"inputSchema": {"json": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}, "name": "get_weather", "description": "Weather for a city"}}], "toolChoice": {"any": {}}}}
reasoning_effort='low': Nova         '### Capital of France\n\nThe **capital  tokens=103/534 cost=0.00150249
    POST /model/us.amazon.nova-2-lite-v1%3A0/converse
    {"inferenceConfig": {"maxTokens": 2000}, "additionalModelRequestFields": {"reasoningConfig": {"type": "enabled", "maxReasoningEffort": "low"}}}
reasoning_effort='low': Claude       'The capital of France is **Paris**.' tokens=20/14 cost=9.9e-06
    POST /model/us.anthropic.claude-haiku-5-5/converse
    {"inferenceConfig": {"maxTokens": 2000}, "additionalModelRequestFields": {"thinking": {"type": "adaptive", "display": "summarized"}, "output_config": {"effort": "low"}}}
thinking budget_tokens=1024: Claude  'Paris.' tokens=20/6 cost=5.5e-06
    POST /model/us.anthropic.claude-haiku-5-5/converse
    {"inferenceConfig": {"maxTokens": 2000}, "additionalModelRequestFields": {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}}}
seed                                 UnsupportedParamsError: bedrock does not support parameters: ['seed'], for model=us.anthropic.claude-hai
seed, drop_params=True               'Paris.' tokens=20/6 cost=5.5e-06
    POST /model/us.anthropic.claude-haiku-5-5/converse
    {"inferenceConfig": {"maxTokens": 100}}
user                                 'The capital of France is **Paris**. \n\ tokens=53/59 cost=0.00017973999999999998
    POST /model/us.amazon.nova-2-lite-v1%3A0/converse
    {"inferenceConfig": {"maxTokens": 100}}
== Bedrock's own parameters
service_tier='flex'                  'The capital of France is **Paris**. \n\ tokens=53/56 cost=8.5745e-05
    POST /model/us.amazon.nova-2-lite-v1%3A0/converse
    {"inferenceConfig": {"maxTokens": 100}, "serviceTier": {"type": "flex"}}
requestMetadata                      'The capital of France is **Paris**. \n\ tokens=53/57 cost=0.00017423999999999999
    POST /model/us.amazon.nova-2-lite-v1%3A0/converse
    {"inferenceConfig": {"maxTokens": 100}, "requestMetadata": {"team": "search"}}
performanceConfig                    BadRequestError: {"message":"Latency performance configuration is not supported for amazon.nova-2
    POST /model/us.amazon.nova-2-lite-v1%3A0/converse
    {"inferenceConfig": {"maxTokens": 100}, "performanceConfig": {"latency": "optimized"}}
top_k=5: Nova                        'The capital of France is **Paris**. \n\ tokens=53/57 cost=0.00017423999999999999
    POST /model/us.amazon.nova-2-lite-v1%3A0/converse
    {"inferenceConfig": {"maxTokens": 100}, "additionalModelRequestFields": {"inferenceConfig": {"topK": 5}}}
any other keyword                    BadRequestError: {"message":"The model returned the following errors: Malformed input request: #:
    POST /model/us.amazon.nova-2-lite-v1%3A0/converse
    {"inferenceConfig": {"maxTokens": 100}, "additionalModelRequestFields": {"some_new_field": {"on": true}}}
additionalModelRequestFields=        BadRequestError: {"message":"The model returned the following errors: Malformed input request: #:
    POST /model/us.amazon.nova-2-lite-v1%3A0/converse
    {"inferenceConfig": {"maxTokens": 100}, "additionalModelRequestFields": {"additionalModelRequestFields": {"inferenceConfig": {"topK": 5}}}}
== what comes back
reasoning_effort='medium': anthropic '1001 is not prime; it equals 7 × 11 × 1 tokens=24/24 cost=1.584e-05
    POST /model/us.anthropic.claude-haiku-5-5/converse
    {"inferenceConfig": {"maxTokens": 4000}, "additionalModelRequestFields": {"thinking": {"type": "adaptive", "display": "summarized"}, "output_config": {"effort": "medium"}}}
    reasoning_content=None  reasoning_tokens=0 of 24
reasoning_effort='medium': amazon    'No, 1001 is not prime because it factor tokens=92/587 cost=0.00164461
    POST /model/us.amazon.nova-2-lite-v1%3A0/converse
    {"inferenceConfig": {"maxTokens": 4000}, "additionalModelRequestFields": {"reasoningConfig": {"type": "enabled", "maxReasoningEffort": "medium"}}}
    reasoning_content='[REDACTED].'  reasoning_tokens=6 of 587
stream=True posts to converse-stream
  3 chunks -> 'Paris.', usage 20/6
```

What to notice:

- **The same parameter can cost very different amounts.** One `response_format` became Bedrock's native structured output for Claude (204 input tokens) and a forced tool call for Nova (912 input tokens). The tool definition and the instructions Bedrock adds for it count as input. Both replies came back as the same JSON string in `message.content`.
- **Refusals happen inside LiteLLM, before anything is sent.** `temperature=0.2` and `top_p` on Claude Haiku 5.5, and `seed`, raised `UnsupportedParamsError` offline too. `drop_params=True` (per call, or `litellm.drop_params = True`) removes the parameter instead. `user` was dropped without a warning even without `drop_params` (the `user` line has no such field in its body), so don't rely on it reaching Bedrock.
- **Unknown keywords are sent to the model, unchecked.** LiteLLM puts any keyword it doesn't recognise into `additionalModelRequestFields`, so a misspelt parameter reaches Bedrock, and Nova rejected it with `Malformed input request`. Pass Bedrock's own top-level fields by name (`requestMetadata`, `serviceTier` through `service_tier`, `guardrailConfig`), and model-specific fields as plain keywords. Don't pass `additionalModelRequestFields=` itself: LiteLLM wrapped it in a second `additionalModelRequestFields`, and Bedrock rejected the request. `performanceConfig={"latency": "optimized"}` was passed through too, and Bedrock answered that latency optimisation is not supported for Nova 2 Lite: passing a field through doesn't mean the model accepts it.
- **`reasoning_effort` turns on adaptive thinking for Claude Haiku 5.5: the model decides whether to think.** For the 1001 question, it thought in one of my six runs (18 reasoning tokens; `reasoning_content` was "1001 factors as 7×11×13, so it's not prime.") and answered straight away in the other five. A `thinking` budget is not sent at all for this model. If your code needs reasoning text, check that `reasoning_content` is not `None`.
- **Nova returns its reasoning as `[REDACTED].`** Bedrock gave no breakdown of Nova's output tokens. LiteLLM then estimates `reasoning_tokens` by counting the reasoning text, which here was the 6 tokens of `[REDACTED].`, while the 587 completion tokens included all the hidden reasoning. Use `completion_tokens` for Nova's cost; `reasoning_tokens` is wrong for it.
- **Bedrock's options change the price.** `service_tier="flex"` was priced at half the standard per-token rate in LiteLLM's 1.110.2 table: $0.0000857 for 53 tokens in and 56 out, against $0.000174 for 53 in and 57 out at the standard tier.
- **Streaming uses its own endpoint, `converse-stream`.** LiteLLM decodes AWS's event stream into OpenAI-style chunks. With `stream_options={"include_usage": True}`, the last chunk carries the usage (section 2).

### Amazon Bedrock Mantle

Mantle is a second inference endpoint in Amazon Bedrock, at `https://bedrock-mantle.<region>.api.aws`. Bedrock's usual endpoint, bedrock-runtime, speaks Bedrock's own Converse and Invoke APIs. Mantle speaks OpenAI's Chat Completions and Responses APIs, plus Anthropic's Messages API for Claude. It uses the same AWS identities, and it bills to the same AWS account. Two things set it apart:

- **Tools written for OpenAI's API can call it,** with a Bedrock API key as the bearer token and Mantle's URL as the base URL. I had no Bedrock API key, so I only saw Mantle reject a made-up one.
- **Its model catalogue differs from bedrock-runtime's, and from region to region.** In my account, the full lists showed 49 models in us-west-2: OpenAI's gpt-oss and several GPT-5 and GPT-6 models, Qwen, Gemma, Mistral, DeepSeek, Kimi, MiniMax, GLM, Grok, Nemotron, and one Claude model, Claude Haiku 4.5. us-east-1 offered 61, including Claude Opus 5.5, Claude Sonnet 5 and GPT-5.5. Claude Haiku 5.5, this tutorial's default Bedrock model, was in neither. Ask the region for its list (`GET /v1/models`, in the example below) instead of assuming a model is there.

LiteLLM 1.110.2 has a provider for it, `bedrock_mantle/<model id>`. Compared with `bedrock/`:

| | `bedrock/` | `bedrock_mantle/` |
| --- | --- | --- |
| Endpoint | `bedrock-runtime.<region>.amazonaws.com` | `bedrock-mantle.<region>.api.aws` |
| Request format | Converse, or Invoke | OpenAI Chat Completions or Responses; Anthropic Messages for Claude |
| Model IDs | Base IDs, inference profiles (`us.`, `global.`), ARNs | Plain IDs such as `openai.gpt-oss-120b`, with no profiles. A region can go in front: `bedrock_mantle/us-east-2/openai.gpt-oss-120b` |
| Authentication | SigV4 for service `bedrock`, or a Bedrock API key | The same. A key, when LiteLLM finds one, always wins over SigV4 |
| Where the key comes from | `api_key=`, `AWS_BEARER_TOKEN_BEDROCK` | `api_key=`, `BEDROCK_MANTLE_API_KEY`, `AWS_BEARER_TOKEN_BEDROCK` |
| Region, first one set | `aws_region_name`, the region in an ARN model ID, `AWS_REGION_NAME`, `AWS_REGION`, the boto3 session's region (the profile's, or `AWS_DEFAULT_REGION`), then `us-west-2` | `aws_region_name`, the region in the model string, `BEDROCK_MANTLE_REGION`, `AWS_REGION_NAME`, `AWS_REGION`, then `us-east-1`. It never reads the profile's region |
| Endpoint override | `aws_bedrock_runtime_endpoint` | `api_base` or `BEDROCK_MANTLE_API_BASE`, including the `/v1` or `/openai/v1` |
| IAM actions | `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream` | LiteLLM's web-identity session policy for Mantle allows `bedrock-mantle:CreateInference` and `bedrock-mantle:CountTokens` (from the source; I ran with an administrator role) |

**Which path a call takes.** The adapter picks the path from the model ID and LiteLLM's price table:

- A Claude model goes to `/anthropic/v1/messages`, with Anthropic's Messages body.
- A model whose table entry carries `use_openai_responses_path` (the GPT-5 and GPT-6 models, Gemma 4 and Grok in 1.110.2) goes to `/openai/v1/...`. Every other model goes to `/v1/...`.
- For a model whose table entry has `mode: "responses"` (the GPT-5 and GPT-6 models in 1.110.2), LiteLLM uses the Responses API: `completion()` sends it to `/responses` and converts the reply back into a chat completion.

`bedrock/mantle/<claude id>` is a second way to reach Mantle's Messages API, through the `bedrock/` provider.

[`examples/01d_bedrock_mantle.py`](examples/01d_bedrock_mantle.py) first lists the models of two regions, then makes the calls:

```python
def mantle_models(region):
    """List the model IDs Mantle serves in a region: GET /v1/models, signed like any Mantle request."""
    url = f"https://bedrock-mantle.{region}.api.aws/v1/models"
    request = AWSRequest(method="GET", url=url)
    SigV4Auth(boto3.Session().get_credentials().get_frozen_credentials(), "bedrock", region).add_auth(request)
    return sorted(m["id"] for m in httpx.get(url, headers=dict(request.headers)).json()["data"])


for model in (GPT_OSS, GEMMA, GPT5, CLAUDE):
    show(model, model=model)
show("region in the model string", model="bedrock_mantle/us-east-2/openai.gpt-oss-120b")
show("aws_region_name='eu-west-1'", model=GPT_OSS, aws_region_name="eu-west-1")
show("api_key= (a made-up Bedrock API key)", model=GPT_OSS, api_key="made-up-bedrock-api-key")
show("api_base without the /v1", model=GPT_OSS, api_base="https://bedrock-mantle.us-west-2.api.aws")
show("responses(): gpt-oss", fn=litellm.responses, model=GPT_OSS, input="Capital of France?", max_output_tokens=256)
show("responses(): Claude", fn=litellm.responses, model=CLAUDE, input="Capital of France?", max_output_tokens=64)
show("bedrock/mantle/anthropic.claude-haiku-4-5", model="bedrock/mantle/anthropic.claude-haiku-4-5")
show("bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0", model="bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0")
```

```bash
cd examples
uv run python 01d_bedrock_mantle.py              # offline: skips the model lists
LIVE=1 uv run python 01d_bedrock_mantle.py       # live: AWS credentials, as for Bedrock
```

The live run, through the same SSO profile; the offline run built the same requests:

```text
us-west-2: 49 models; Claude: ['anthropic.claude-haiku-4-5']; gpt-5.5: False
us-east-1: 61 models; Claude: ['anthropic.claude-fable-5', 'anthropic.claude-haiku-4-5', 'anthropic.claude-opus-4-7', 'anthropic.claude-opus-4-8', 'anthropic.claude-opus-5', 'anthropic.claude-opus-5-5', 'anthropic.claude-sonnet-5']; gpt-5.5: True
== one provider, three request formats
bedrock_mantle/openai.gpt-oss-120b                   'Paris.' tokens=78/30 cost=2.97e-05
    POST https://bedrock-mantle.us-west-2.api.aws/v1/chat/completions  SigV4 us-west-2/bedrock
    body: model='openai.gpt-oss-120b', fields=['max_tokens', 'messages']
bedrock_mantle/google.gemma-4-31b                    'Paris' tokens=41/2 cost=6.54e-06
    POST https://bedrock-mantle.us-west-2.api.aws/openai/v1/chat/completions  SigV4 us-west-2/bedrock
    body: model='google.gemma-4-31b', fields=['max_tokens', 'messages']
bedrock_mantle/openai.gpt-5.4                        'Paris.' tokens=17/6 cost=0.00014575
    POST https://bedrock-mantle.us-west-2.api.aws/openai/v1/responses  SigV4 us-west-2/bedrock
    body: model='openai.gpt-5.4', fields=['input', 'max_output_tokens']
bedrock_mantle/anthropic.claude-haiku-4-5            'Paris' tokens=14/4 cost=3.4e-05
    POST https://bedrock-mantle.us-west-2.api.aws/anthropic/v1/messages  SigV4 us-west-2/bedrock
    body: model='anthropic.claude-haiku-4-5', fields=['anthropic_version', 'max_tokens', 'messages', 'system']
== region and credentials
region in the model string                           'Paris.' tokens=78/25 cost=2.67e-05
    POST https://bedrock-mantle.us-east-2.api.aws/v1/chat/completions  SigV4 us-east-2/bedrock
    body: model='openai.gpt-oss-120b', fields=['max_tokens', 'messages']
aws_region_name='eu-west-1'                          'Paris.' tokens=78/25 cost=2.67e-05
    POST https://bedrock-mantle.eu-west-1.api.aws/v1/chat/completions  SigV4 eu-west-1/bedrock
    body: model='openai.gpt-oss-120b', fields=['max_tokens', 'messages']
api_key= (a made-up Bedrock API key)                 AuthenticationError: {"error":{"code":"invalid_api_key","message":"Invalid bearer token","param":null
    POST https://bedrock-mantle.us-west-2.api.aws/v1/chat/completions  Bearer
    body: model='openai.gpt-oss-120b', fields=['max_tokens', 'messages']
api_base without the /v1                             NotFoundError: 
    POST https://bedrock-mantle.us-west-2.api.aws/chat/completions  SigV4 us-west-2/bedrock
    body: model='openai.gpt-oss-120b', fields=['max_tokens', 'messages']
== the Responses API
responses(): gpt-oss                                 'The capital of France is **Paris**.' tokens=71/49
    POST https://bedrock-mantle.us-west-2.api.aws/v1/responses  SigV4 us-west-2/bedrock
    body: model='openai.gpt-oss-120b', fields=['input', 'max_output_tokens']
responses(): Claude                                  'Paris is the capital of France.' tokens=11/10
    POST https://bedrock-mantle.us-west-2.api.aws/anthropic/v1/messages  SigV4 us-west-2/bedrock
    body: model='anthropic.claude-haiku-4-5', fields=['anthropic_version', 'max_tokens', 'messages']
== the same Claude model, three ways
bedrock/mantle/anthropic.claude-haiku-4-5            'Paris' tokens=14/4 cost=0.0
    POST https://bedrock-mantle.us-west-2.api.aws/anthropic/v1/messages  SigV4 us-west-2/bedrock
    body: model='anthropic.claude-haiku-4-5', fields=['anthropic_version', 'max_tokens', 'messages', 'system']
bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0  'Paris' tokens=14/4 cost=3.74e-05
    POST https://bedrock-runtime.us-west-2.amazonaws.com/model/us.anthropic.claude-haiku-4-5-20251001-v1%3A0/converse  SigV4 us-west-2/bedrock
    body: model=None, fields=['inferenceConfig', 'messages', 'system']
price bedrock_mantle/anthropic.claude-haiku-4-5            $1.00 / $5.00 per million tokens in/out
price anthropic.claude-haiku-4-5-20251001-v1:0             $1.00 / $5.00 per million tokens in/out
price us.anthropic.claude-haiku-4-5-20251001-v1:0          $1.10 / $5.50 per million tokens in/out
```

What to notice:

- **One provider, three request formats, one result shape.** gpt-oss went to `/v1/chat/completions`, Gemma 4 to `/openai/v1/chat/completions`, GPT-5.4 to `/openai/v1/responses` and Claude to `/anthropic/v1/messages`. All four came back as the same OpenAI-shaped response, priced from LiteLLM's table.
- **The model ID must exist in the region you call.** My first version used `openai.gpt-5.5` and `anthropic.claude-haiku-5-5` in us-west-2, and Mantle answered `NotFoundError: The model '...' does not exist` for both. In a separate check, GPT-5.5 worked in us-east-1 and us-east-2. LiteLLM's price table lists models that a given region doesn't serve, so it can't tell you either.
- **The region moves the host and the signature together.** A region in the model string, or `aws_region_name`, changed both the URL and the SigV4 scope. LiteLLM's table prices eu-west-1 per token the same as us-west-2. Set the region explicitly: with only `AWS_PROFILE` set, `bedrock/` takes the profile's region but Mantle ignores it and falls back to `us-east-1` (from the source).
- **A key always wins over SigV4.** With a made-up `api_key=`, LiteLLM sent `Authorization: Bearer` and Mantle answered `Invalid bearer token`, although valid SSO credentials were available. The same happens with a stale `BEDROCK_MANTLE_API_KEY` or `AWS_BEARER_TOKEN_BEDROCK` in the environment, including one you exported for `bedrock/`.
- **An `api_base` replaces the whole base, so include `/v1` or `/openai/v1`.** Without it, the request went to `/chat/completions` and Mantle answered with an empty 404.
- **`responses()` is native where Mantle supports it.** For gpt-oss it went to `/v1/responses` unchanged; for Claude, LiteLLM translated it into a Messages request. gpt-oss's 71 to 78 prompt tokens for a one-line question come from its own chat format; Claude counted 11 to 14.
- **Price the route you use.** `bedrock_mantle/anthropic.claude-haiku-4-5` cost $0.000034 for 14 tokens in and 4 out. The `us.` profile on bedrock-runtime cost 10% more. The same call through `bedrock/mantle/` cost `0.0`, because LiteLLM's 1.110.2 table has no price under that name. A cost of `0.0` looks like a free call, not a missing price, so budgets and spend reports would never see it. Use `bedrock_mantle/`, or register a price (section 8).

### Ollama

[Ollama](https://ollama.com/) runs open-weight models on your own machine and serves them over HTTP. Section 12 starts one in Docker, compares its two routes, and runs tools and streaming through it. In short:

- **Two prefixes, two Ollama APIs.** `ollama_chat/<model>` posts to `/api/chat` and keeps the roles, tools and images. `ollama/<model>` posts to `/api/generate`, which takes a single prompt, so LiteLLM flattens the conversation into text. Use `ollama_chat/`.
- **The server.** `api_base=`, then `OLLAMA_API_BASE`, then `http://localhost:11434`.
- **No key.** If you put Ollama behind an authenticating reverse proxy, `api_key=` is sent as `Authorization: Bearer <key>`.
- **No price.** LiteLLM has no prices for Ollama models: `response_cost` was `0.0` for every call below. Behind the proxy, the `x-litellm-response-cost` header is left out instead (section 12).

**OpenAI parameters become Ollama options.** Ollama takes its sampling settings in an `options` object, and structured output in a top-level `format`:

| You pass | In the Ollama request | Notes |
| --- | --- | --- |
| `max_tokens` or `max_completion_tokens` | `options.num_predict` | |
| `temperature`, `top_p`, `seed`, `stop` | `options.temperature`, `.top_p`, `.seed`, `.stop` | |
| `frequency_penalty` | `options.repeat_penalty`, the same number | Not the same scale (see below) |
| `response_format` with a JSON schema | `format: <the schema>` | Ollama constrains the output to the schema |
| `response_format={"type": "json_object"}` | `format: "json"` | Valid JSON, any shape |
| `tools`, `tool_choice` | `tools` | `ollama_chat/` only (section 12) |
| `reasoning_effort` | `"low"`, `"medium"`, `"high"`: `think: true`. `"none"`, `"minimal"` and other levels: `think: false` | The level itself is not sent, except to gpt-oss models (from the source) |
| `num_ctx`, `repeat_penalty`, `num_gpu` and Ollama's other model options | `options.<name>` | |
| `keep_alive` | Top-level `keep_alive` | How long Ollama keeps the model loaded after the call |

[`examples/01e_ollama.py`](examples/01e_ollama.py) runs against section 12's Ollama container. Besides `qwen2.5:0.5b`, it uses `qwen3:0.6b`, a small model that can think:

```bash
docker start litellm-tutorial-ollama                                  # or the docker run line in section 12
docker exec litellm-tutorial-ollama ollama pull qwen3:0.6b            # about 520 MB
cd examples
uv run python 01e_ollama.py
```

```python
SMALL, THINKER = "ollama_chat/qwen2.5:0.5b", "ollama_chat/qwen3:0.6b"


def show(label, model=SMALL, **kwargs):
    """Make one call; print the reply, the Ollama path and every body field except the messages."""
    start = time.perf_counter()
    resp, req = send(litellm.completion, model=model, messages=kwargs.pop("messages", MSGS),
                     api_base=OLLAMA, timeout=120, **kwargs)
    ...


show("frequency_penalty=0.5", max_tokens=20, frequency_penalty=0.5)
show("response_format json_schema", max_tokens=40, response_format=CITY)
show("num_ctx, keep_alive (Ollama's)", max_tokens=20, num_ctx=8192, keep_alive="10m")
thought = show("reasoning_effort: qwen3", model=THINKER, max_tokens=400, reasoning_effort="low", messages=[...])
show("keep_alive=0 (unload after)", max_tokens=5, keep_alive=0)
show("next call: cold", max_tokens=5)
show("next call: warm", max_tokens=5)
```

Ollama runs on plain HTTP on your machine, so it is called even offline. On CPU, with the prompt "Capital of France? Answer in JSON.":

```text
== OpenAI parameters become Ollama options
max_tokens                      1.1s '```json\n{\n  "capital": "Paris"\n}\n`` tokens=24/14 cost=0.0
    POST /api/chat  {"options": {"num_predict": 20}}
temperature, seed, stop         0.5s '```json\n{\n  "capital": "Paris"\n' tokens=24/12 cost=0.0
    POST /api/chat  {"options": {"temperature": 0, "stop": ["}"], "num_predict": 20, "seed": 7}}
frequency_penalty=0.5           0.4s '``` JSON\n```' tokens=24/5 cost=0.0
    POST /api/chat  {"options": {"num_predict": 20, "repeat_penalty": 0.5}}
response_format json_schema     0.5s '{\n  "city": "Paris"\n}' tokens=24/10 cost=0.0
    POST /api/chat  {"options": {"num_predict": 40}, "format": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}
response_format json_object     0.4s '{\n  "capital": "Paris"\n}' tokens=24/10 cost=0.0
    POST /api/chat  {"options": {"num_predict": 40}, "format": "json"}
num_ctx, keep_alive (Ollama's)  2.1s '```json\n{\n  "capital": "Paris"\n}\n`` tokens=24/14 cost=0.0
    POST /api/chat  {"options": {"num_predict": 20, "num_ctx": 8192}, "keep_alive": "10m"}
ollama/ (the generate API)      2.2s '```json\n{\n  "capital": "Paris"\n}\n`` tokens=46/14 cost=0.0
    POST /api/generate  {"prompt": "### System:\nBe brief.\n\n### User:\nCapital of France? Answer in JSON.\n\n", "options": {"num_predict": 20}, "images": []}
== reasoning
reasoning_effort: qwen2.5       0.2s BadRequestError: {"error":"\"qwen2.5:0.5b\" does not support thinking"}
    POST /api/chat  {"options": {"num_predict": 200}, "think": true}
reasoning_effort: qwen3         7.6s '51' tokens=25/214 cost=0.0
    POST /api/chat  {"options": {"num_predict": 400}, "think": true}
    reasoning_content: "Okay, let's see. The user is asking what is 17 multiplied by 3, and they want t
== loading the model
keep_alive=0 (unload after)     0.5s '```json\n{\n ' tokens=24/5 cost=0.0
    POST /api/chat  {"options": {"num_predict": 5}, "keep_alive": 0}
next call: cold                 1.6s '```json\n{\n ' tokens=24/5 cost=0.0
    POST /api/chat  {"options": {"num_predict": 5}}
next call: warm                 0.3s '```json\n{\n ' tokens=24/5 cost=0.0
    POST /api/chat  {"options": {"num_predict": 5}}
```

What to notice:

- **Only a schema in `format` guarantees the shape.** Asked for JSON in the prompt alone, the model wrapped it in a Markdown code fence and named the key `capital`. With the schema, Ollama returned bare JSON with the key `city`. `json_object` gave valid JSON, but with a key the model chose.
- **`frequency_penalty` is passed on as `repeat_penalty` with the same number, but the scales differ.** OpenAI's `frequency_penalty` runs from -2 to 2, and 0 means no penalty. Ollama's `repeat_penalty` is a multiplier, where 1 means no penalty and a value below 1 makes repetition more likely. With 0.5, this run's reply was the fragment `` ``` JSON\n``` ``. Pass `repeat_penalty=1.1` (or so) by name instead.
- **`ollama/` costs more input tokens for the same conversation.** The generate API got a flattened prompt with `### System:` and `### User:` headings: 46 prompt tokens against 24 through `/api/chat`.
- **Thinking is on or off, and the model must support it.** `reasoning_effort="low"` became `think: true` (so do `"medium"` and `"high"`; other levels give `false`). `qwen2.5:0.5b` doesn't think, and Ollama's 400 became `BadRequestError`. `qwen3:0.6b` returned its reasoning in `reasoning_content`, and its 214 completion tokens include the thinking. That is why a two-character answer took 7.6 s on CPU. Leave enough `max_tokens` for the thinking, or the answer is cut short.
- **The first call after a model is unloaded pays for loading it.** With `keep_alive=0`, Ollama unloaded the model after the call, and the next call took 1.6 s instead of 0.3 s. For a model of several gigabytes, loading takes much longer than for this 400 MB one, so give the first call a long `timeout`, or keep the model loaded with `keep_alive`.
- **Set `num_ctx` for long prompts.** It sets the size of the context window Ollama allocates for the model. LiteLLM doesn't set it, so without it Ollama uses its own default, which is usually smaller than the model's maximum.

### vLLM

[vLLM](https://docs.vllm.ai/) serves models on GPUs. `vllm serve <model>` starts an OpenAI-compatible server, by default on port 8000, with the API under `/v1`. LiteLLM offers three prefixes for it:

| Prefix | What it does | Use it when |
| --- | --- | --- |
| `hosted_vllm/<model>` | OpenAI Chat Completions to a running vLLM server, with vLLM-specific clean-ups (below) | You run a vLLM server. The usual choice |
| `openai/<model>` + `api_base` | The generic OpenAI-compatible adapter, which knows nothing about vLLM | A server that only claims OpenAI compatibility |
| `vllm/<model>` | Loads the model into your own process with the `vllm` Python package | You want no server; needs `vllm` installed and a GPU. Not covered here |

For `hosted_vllm/`, the server is `api_base=` or `HOSTED_VLLM_API_BASE`, including the `/v1`. The key is `api_key=` or `HOSTED_VLLM_API_KEY`; with neither, LiteLLM sends the placeholder `fake-api-key`. A vLLM server started without `--api-key` ignores it. vLLM's tool calling and reasoning output depend on how the server was started. According to vLLM's documentation, tool calling needs `--enable-auto-tool-choice` and a `--tool-call-parser`, and reasoning needs a `--reasoning-parser`. I had no GPU, so I didn't run a real vLLM.

[`examples/01f_vllm.py`](examples/01f_vllm.py) runs against [`examples/_fake_vllm.py`](examples/_fake_vllm.py), a fake vLLM server on a background thread. Like vLLM with a reasoning parser, it returns a `reasoning` field unless thinking is turned off in the chat template. It answers 400 with vLLM's error text when a prompt is longer than its `max_model_len`:

```python
VLLM = start()                                             # the fake, on a free port: http://127.0.0.1:<port>/v1
MODEL = "Qwen/Qwen3-8B"

show("hosted_vllm/, no api_key")
show("openai/, no api_key", prefix="openai")
show("top_k, min_p, repetition_penalty", fields=("top_k", "min_p", "repetition_penalty"),
     top_k=20, min_p=0.05, repetition_penalty=1.1)
show("thinking budget -> reasoning_effort", fields=("reasoning_effort",),
     thinking={"type": "enabled", "budget_tokens": 1024})
show("chat_template_kwargs: no thinking", fields=("chat_template_kwargs",),
     extra_body={"chat_template_kwargs": {"enable_thinking": False}})
...
show("price per call", input_cost_per_token=0.1e-6, output_cost_per_token=0.4e-6)
litellm.register_model({f"hosted_vllm/{MODEL}": {
    "litellm_provider": "hosted_vllm", "mode": "chat", "max_input_tokens": 32768,
    "input_cost_per_token": 0.1e-6, "output_cost_per_token": 0.4e-6}})
show("price from register_model()")
```

```bash
cd examples
uv run python 01f_vllm.py
```

```text
== the key and the base URL
hosted_vllm/, no api_key           'Paris.' tokens=21/14 cost=None
    Authorization: 'Bearer fake-api-key'  {}
openai/, no api_key                InternalServerError: Missing credentials. Please pass an `api_key`, `workload_identity`, `admin_api_k
hosted_vllm/, api_key='vllm-token' 'Paris.' tokens=21/14 cost=None
    Authorization: 'Bearer vllm-token'  {}
base from HOSTED_VLLM_API_BASE     'Paris.' tokens=21/14 cost=None
    Authorization: 'Bearer fake-api-key'  {}
== vLLM's own parameters
top_k, min_p, repetition_penalty   'Paris.' tokens=21/14 cost=None
    Authorization: 'Bearer fake-api-key'  {"top_k": 20, "min_p": 0.05, "repetition_penalty": 1.1}
thinking budget -> reasoning_effort 'Paris.' tokens=21/14 cost=None
    Authorization: 'Bearer fake-api-key'  {"reasoning_effort": "low"}
default: the model thinks          'Paris.' tokens=21/14 cost=None
    Authorization: 'Bearer fake-api-key'  {}
    reasoning_content='The user wants the capital of France. That is Paris.'
chat_template_kwargs: no thinking  'Paris.' tokens=21/14 cost=None
    Authorization: 'Bearer fake-api-key'  {"chat_template_kwargs": {"enable_thinking": false}}
    reasoning_content=None
== what hosted_vllm/ changes, and openai/ doesn't
hosted_vllm/ strict tool           strict=None additionalProperties=None
openai/ strict tool                strict=True additionalProperties=False
hosted_vllm/ Claude turn in history content='Paris.' thinking_blocks=False
openai/ Claude turn in history     content=[{'type': 'text', 'text': 'Paris.'}] thinking_blocks=True
== errors and cost
prompt longer than max_model_len   ContextWindowExceededError: {"object": "error", "type": "BadRequestError", "code": 400, "message": "This mod
    Authorization: 'Bearer fake-api-key'  {}
... through openai/                ContextWindowExceededError: This model's maximum context length is 32768 tokens. However, you requested 4000
    Authorization: None  {}
no price for a self-hosted model   'Paris.' tokens=21/14 cost=None
    Authorization: 'Bearer fake-api-key'  {}
price per call                     'Paris.' tokens=21/14 cost=7.699999999999999e-06
    Authorization: 'Bearer fake-api-key'  {}
price from register_model()        'Paris.' tokens=21/14 cost=7.699999999999999e-06
    Authorization: 'Bearer fake-api-key'  {}
```

When `register_model()` runs, LiteLLM also logs a warning (to stderr, left out above): cache-token prices default to 0 for a model it doesn't know. Input and output prices are unaffected.

What to notice:

- **`hosted_vllm/` works without a key; `openai/` doesn't.** `hosted_vllm/` sent `Bearer fake-api-key`. `openai/` refused to send anything without a key, so with it you pass a dummy `api_key=` yourself. If your vLLM server has `--api-key`, pass the real one either way.
- **vLLM's extra sampling parameters go through as top-level fields.** LiteLLM doesn't check `top_k`, `min_p` or `repetition_penalty` against a list; it sends them, and vLLM accepts them. Parameters that belong inside the request's extensions, such as `chat_template_kwargs`, go in `extra_body=`.
- **Reasoning comes back in `reasoning_content`.** The fake returned vLLM's `reasoning` field, and LiteLLM moved it to `message.reasoning_content`. In a separate run where the fake returned the older field name, `reasoning_content`, the result was the same, through both `hosted_vllm/` and `openai/`. `enable_thinking: False` in the chat template (for Qwen3) turned thinking off. A `thinking` budget became `reasoning_effort="low"` for 1,024 tokens; a 100-token budget became `"minimal"` in another run.
- **`hosted_vllm/` makes requests vLLM accepts.** It removed `strict` and `additionalProperties` from tool schemas. In a history that came from Claude, it flattened the assistant turn's content blocks to a string and dropped its `thinking_blocks`. `openai/` sent both unchanged. This matters when one conversation moves between providers, for example after a fallback (section 6).
- **Context-window errors are recognised.** vLLM's 400 "maximum context length" error became `ContextWindowExceededError`, through both prefixes. Section 7's `context_window_fallbacks` can then move the call to a model with a larger window.
- **A self-hosted model has no price until you give it one.** `response_cost` was `None`, so budgets and spend reports skip these calls. Pass `input_cost_per_token` and `output_cost_per_token` per call, or register them once with `litellm.register_model()` (section 8), for example from your GPU cost per hour divided by the tokens per hour you measure. In the proxy, the same two fields go in the deployment's `model_info` (section 12).

### Other major providers

These providers follow the same pattern as the four above: a prefix, a credential, an endpoint, and a mapping of OpenAI parameters. The table shows what LiteLLM 1.110.2 sent for each, captured offline with `_wire.py` and made-up keys. Section 12 runs Azure, Vertex AI, OpenAI and Anthropic against local fakes:

| Provider | Model string | Credential (env var) | Endpoint LiteLLM calls | What changes in the request |
| --- | --- | --- | --- | --- |
| OpenAI | `openai/<model>` | `OPENAI_API_KEY`; base URL from `api_base`, `OPENAI_BASE_URL` or `OPENAI_API_BASE` | `https://api.openai.com/v1/chat/completions` | Sent through the `openai` SDK. For reasoning models, `max_tokens` becomes `max_completion_tokens` (section 1's table), and o-series models refuse `temperature` other than 1 |
| Anthropic | `anthropic/<model>` | `ANTHROPIC_API_KEY`, sent as `x-api-key` with `anthropic-version` | `https://api.anthropic.com/v1/messages` | The system prompt moves to `system`; `max_tokens` is always sent. For Claude Haiku 5.5, `reasoning_effort` becomes adaptive `thinking` plus `output_config.effort`, as on Bedrock |
| Azure OpenAI | `azure/<deployment name>` | `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION`; or Microsoft Entra ID | `https://<resource>.openai.azure.com/openai/deployments/<deployment>/chat/completions?api-version=...`, or `/openai/v1/...` with `api_version="v1"` | The name after `azure/` is your deployment, not the model. To get a cost, pass `base_model` (section 12) |
| Microsoft Foundry | `azure_ai/<model>` | `AZURE_AI_API_KEY` (sent as `api-key`, and also as `x-api-key` for Claude) and `AZURE_AI_API_BASE` | Claude: `https://<resource>.services.ai.azure.com/anthropic/v1/messages`. Other models: `.../models/chat/completions` | `claude` in the model name selects Anthropic's Messages format |
| Google AI Studio (Gemini API) | `gemini/<model>` | `GEMINI_API_KEY` or `GOOGLE_API_KEY`, sent as `x-goog-api-key` | `https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent` | The system prompt becomes `system_instruction`, `max_tokens` becomes `generationConfig.max_output_tokens`, and `reasoning_effort="low"` becomes `thinkingConfig.thinkingBudget: 1024` with `includeThoughts` |
| Google Vertex AI | `vertex_ai/<model>` | Application Default Credentials, plus `VERTEXAI_PROJECT` and `VERTEXAI_LOCATION` | `https://<location>-aiplatform.googleapis.com/v1/projects/<project>/locations/<location>/publishers/<publisher>/models/<model>:...` | Gemini takes the same body as AI Studio; Claude takes Anthropic's body (Setup's "How LiteLLM reaches a provider") |
| Mistral | `mistral/<model>` | `MISTRAL_API_KEY` | `https://api.mistral.ai/v1/chat/completions` | OpenAI format, `Authorization: Bearer` |
| Groq | `groq/<model>` | `GROQ_API_KEY` | `https://api.groq.com/openai/v1/chat/completions` | OpenAI format |
| xAI | `xai/<model>` | `XAI_API_KEY` | `https://api.x.ai/v1/chat/completions` | OpenAI format |
| DeepSeek | `deepseek/<model>` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com/beta/chat/completions` | OpenAI format, on DeepSeek's `beta` path |
| OpenRouter | `openrouter/<vendor>/<model>` | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1/chat/completions` | Adds `usage: {"include": true}`, so OpenRouter reports usage and cost |

The same pattern holds for many more: `together_ai/` (`TOGETHERAI_API_KEY`), `fireworks_ai/` (`FIREWORKS_AI_API_KEY`), `cohere/` (`COHERE_API_KEY`), `nvidia_nim/` (`NVIDIA_NIM_API_KEY`), `perplexity/` (`PERPLEXITYAI_API_KEY`), `cerebras/` (`CEREBRAS_API_KEY`) and `huggingface/` (`HUGGINGFACE_API_KEY`), among others. `litellm.validate_environment("<model string>")` names the variables a provider needs. It found none for `azure_ai/`, `databricks/` and `watsonx/`, which also accept other ways to authenticate, so read their documentation instead.

Before you rely on a parameter with a provider you haven't used, check three things:

- **Does LiteLLM accept it for this model?** `litellm.get_supported_openai_params(model=..., custom_llm_provider=...)` lists them. A parameter outside the list raises `UnsupportedParamsError`, or is dropped with `drop_params`.
- **What does it become?** Capture the request with a callback, as `_wire.py` does (exercise 1.10). Two providers can give the same parameter different meanings, as `frequency_penalty` showed with Ollama.
- **Is the model priced?** `litellm.model_cost.get("<provider>/<model>")`, or `litellm.get_model_info(...)`. A missing price means a `response_cost` of `None` or `0.0`, which budgets don't count.

### Exercises

**1.1 ★ `ex01_1_three_models.py`: one request, three model families**

Send one conversation to `_env.FAST`, `_env.SMART` and `_env.ALT`: a system message ("Answer in one sentence.") and a user question. For each model, print the reply, the token counts and the cost, then print which model was cheapest.

Checks:
- Every reply is a non-empty `str` at `choices[0].message.content`.
- `completion_cost(resp) > 0` for every model.
- `usage.total_tokens == usage.prompt_tokens + usage.completion_tokens`.

<details><summary>Hint</summary>

Claude and Nova take the system prompt in different places in their native Bedrock APIs. You don't need to handle that; LiteLLM does.
</details>

**1.2 ★ `ex01_2_model_strings.py`: how LiteLLM reads a model string**

For each of `_env.FAST`, `"anthropic/claude-sonnet-5-5"`, `"gpt-4o-mini"`, `"claude-sonnet-5-5"`, `"ollama/llama3.1"` and `"hosted_vllm/meta-llama/Llama-3.1-8B-Instruct"`, call `litellm.get_llm_provider()` and print the provider and the model ID that would be sent to that provider. Then call `litellm.validate_environment("anthropic/claude-sonnet-5-5")` and print what it reports.

Checks:
- The providers are `bedrock`, `anthropic`, `openai`, `anthropic`, `ollama` and `hosted_vllm`, in that order.
- The Bedrock model ID has no `bedrock/` prefix, and the vLLM one keeps its inner `/`.
- `validate_environment` lists `ANTHROPIC_API_KEY` as missing (unless you have it exported).

<details><summary>Hint</summary>

`get_llm_provider` returns a 4-tuple: `(model, provider, dynamic_api_key, api_base)`. A string without a prefix is matched against the bundled model list.
</details>

**1.3 ★★ `ex01_3_chat_history.py`: a multi-turn conversation**

Run a three-turn conversation with `_env.FAST`. Start `messages` with one system message, hard-code the three user turns, and give each turn its own mock reply offline. Append each assistant reply to `messages` before the next turn, then print the transcript.

Checks:
- After the loop, `len(messages) == 7`: one system message, three user and three assistant messages.
- After the system message, roles alternate user, assistant, user, ...
- Live only: the last turn's `usage.prompt_tokens` is larger than the first turn's, because the whole history is re-sent on every call.

<details><summary>Hint</summary>

You can append `resp.choices[0].message` itself, or `{"role": "assistant", "content": ...}`. Offline, a mocked non-streaming reply always reports 10 prompt tokens, which is why the last check is live only.
</details>

**1.4 ★ `ex01_4_param_map.py`: where your parameters land on Bedrock**

Capture the Converse requests LiteLLM builds for `_env.FAST` and `_env.ALT` without sending them. For each model, call `completion()` with five parameter sets: `max_completion_tokens` with `stop`; a JSON-schema `response_format`; `tools` with `tool_choice="required"`; `reasoning_effort="low"`; and `seed`. Print the top-level body fields each call adds beyond `messages`, `system` and `inferenceConfig`.

Checks:
- For `_env.FAST`, `response_format` adds `outputConfig`. For `_env.ALT`, it adds a `toolConfig` whose only tool is named `json_tool_call`.
- `tool_choice="required"` gives `toolConfig.toolChoice == {"any": {}}` for both models.
- `seed` raises `UnsupportedParamsError`, and no request is captured for it.
- Offline, nothing leaves your machine.

<details><summary>Hint</summary>

Write your own `CustomLogger` with a `log_pre_api_call` hook, like `examples/_wire.py`. For Bedrock, `complete_input_dict` arrives as a JSON string. Offline, the request still has to be signed, so set made-up static keys (only when `_env.LIVE` is false) and point `HTTPS_PROXY` at a closed port such as `http://127.0.0.1:9`. If your `exercises/.env.local` sets `LIVE=1`, run with `LIVE=0 uv run python ...` to stay offline: a variable set in the shell wins over the file.
</details>

**1.5 ★★ `ex01_5_structured_bedrock.py`: one schema, two model families**

Define a Pydantic model `Ticket` with `customer`, `order_id` and `issue`. Pass the class itself as `response_format` to `_env.FAST` and to `_env.ALT`, with a short support email to extract from. Parse each reply with `Ticket.model_validate_json()`. Print the parsed ticket, the prompt tokens and the cost for each model.

Checks:
- Both replies parse into a `Ticket`, and `order_id` is the one in your email.
- Live: `_env.ALT` used more prompt tokens than `_env.FAST` for the same email. In my run it was 989 against 349, and the Nova call cost seven times as much.

<details><summary>Hint</summary>

Offline, give `_env.mock()` a JSON string that matches the schema. The difference in prompt tokens comes from how the schema is sent (section 1's Bedrock table): a forced tool call costs input tokens that native structured output doesn't.
</details>

**1.6 ★★ `ex01_6_mantle_catalogue.py`: what Mantle serves where**

List Bedrock Mantle's models in us-west-2 and us-east-1, and print how many each region has and which ones only one of them offers. Then call `bedrock_mantle/openai.gpt-oss-120b` in each region, with both `litellm.completion()` and `litellm.responses()`, and print the replies and the cost.

Checks:
- Both lists load, with a signed `GET https://bedrock-mantle.<region>.api.aws/v1/models`.
- `openai.gpt-oss-120b` is in both lists, and all four calls answer.
- Print whether `anthropic.claude-haiku-5-5` is offered. It was offered in neither region when I ran this; the list changes over time.

<details><summary>Hint</summary>

Sign the request with botocore's `SigV4Auth` for service `bedrock`, as `mantle_models()` in `examples/01d_bedrock_mantle.py` does. This exercise needs `LIVE=1`. gpt-oss spends part of its output on reasoning, so give it at least 300 tokens, or the reply can come back empty.
</details>

**1.7 ★★ `ex01_7_price_the_route.py`: price the route you use**

Call Claude Haiku 4.5 through three routes: `bedrock_mantle/anthropic.claude-haiku-4-5`, `bedrock/mantle/anthropic.claude-haiku-4-5` and `bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0`, all in us-west-2. Print each reply, its tokens and `response_cost`. Then give the route without a price the Mantle provider's price with `litellm.register_model()`, and run the three calls again.

Checks:
- Before the fix, the `bedrock/mantle/` route costs `0.0` and the other two cost more than 0.
- After the fix, it costs the same as `bedrock_mantle/` for the same tokens.
- Live: the `us.` profile on bedrock-runtime costs more than the Mantle provider for the same tokens.

<details><summary>Hint</summary>

Register the model under the exact string you call (`bedrock/mantle/anthropic.claude-haiku-4-5`), copy the price fields from `litellm.model_cost["bedrock_mantle/anthropic.claude-haiku-4-5"]`, and set `litellm_provider` to `"bedrock"`. Offline, `_env.mock()` reports 10 tokens in and 20 out, which is enough to compare the prices.
</details>

**1.8 ★★ `ex01_8_ollama_extract.py`: a small local model and a schema**

With `ollama_chat/qwen2.5:0.5b`, extract `customer`, `order_id` and `issue` from five one-line support emails. Run the five calls twice: once asking for JSON in the system prompt only, and once also passing a JSON-schema `response_format` built from a Pydantic model. Count how many replies validate against the model in each run, and print the median latency.

Checks:
- With the schema, all five replies validate.
- Print the count without the schema too. In my run, none of the five validated: the model wrapped the JSON in a code fence or chose its own keys.

<details><summary>Hint</summary>

`Ticket.model_json_schema()` gives the schema; wrap it as `{"type": "json_schema", "json_schema": {"name": "ticket", "schema": ...}}`. Ollama runs over plain HTTP on your machine, so this exercise runs the same whether `LIVE` is set or not.
</details>

**1.9 ★★ `ex01_9_vllm_chargeback.py`: charge for a self-hosted model**

Your vLLM server runs on a GPU that costs $2.50 an hour and serves 1,500 tokens a second. Turn that into a price per token, register it for `hosted_vllm/Qwen/Qwen3-8B` with `litellm.register_model()`, and make ten calls against the fake vLLM from `examples/_fake_vllm.py`. Pass `top_k=20`, and turn off Qwen3's thinking through `chat_template_kwargs`. Print the price per token and the total cost.

Checks:
- Every call has a `response_cost` that is not `None`.
- The captured body carries `top_k: 20` and `chat_template_kwargs: {"enable_thinking": false}`.
- `reasoning_content` is `None`, because thinking was off.

<details><summary>Hint</summary>

$2.50 / (1,500 × 3,600) is about $0.00000046 per token. `chat_template_kwargs` goes inside `extra_body=`. Import `start` from `examples/_fake_vllm.py` by adding the `examples` folder to `sys.path`.
</details>

**1.10 ★ `ex01_10_provider_matrix.py`: ten providers, nothing sent**

For `openai/gpt-4o-mini`, `anthropic/claude-haiku-5-5`, `gemini/gemini-2.5-flash`, `mistral/mistral-large-latest`, `groq/llama-3.3-70b-versatile`, `azure_ai/claude-haiku-5-5`, `azure_ai/mistral-large-3`, `bedrock/us.anthropic.claude-haiku-5-5`, `bedrock_mantle/openai.gpt-oss-120b` and `hosted_vllm/Qwen/Qwen3-8B`, print:

- the provider from `litellm.get_llm_provider()`;
- the variables `litellm.validate_environment()` reports missing;
- the URL LiteLLM would call, and which authentication header it sets.

Set made-up keys after calling `validate_environment`, and stop every request before it leaves your machine.

Checks:
- Gemini authenticates with `x-goog-api-key`, Anthropic with `x-api-key`, and Mistral with `Authorization`.
- The `azure_ai/` Claude URL ends in `/anthropic/v1/messages`; the other `azure_ai/` model goes to `/models/chat/completions`.
- Groq's URL contains `/openai/v1/`.

<details><summary>Hint</summary>

OpenAI calls go through the `openai` SDK, which adds its own `Authorization` header after LiteLLM's hook runs: you see the base URL and no auth header there. `validate_environment` checks environment variables only, so it reports AWS keys missing for `bedrock/` even when an SSO profile works.
</details>

**1.11 ★★ `ex01_11_reasoning_matrix.py`: one `reasoning_effort`, seven translations**

Capture what `reasoning_effort="low"` becomes for `anthropic/claude-haiku-5-5`, `bedrock/us.anthropic.claude-haiku-5-5`, `bedrock/us.amazon.nova-2-lite-v1:0`, `gemini/gemini-2.5-flash`, `openai/gpt-5.5`, `hosted_vllm/Qwen/Qwen3-8B` (against the fake vLLM) and `ollama_chat/qwen3:0.6b` (against your Ollama). Print only the body fields that carry it.

Checks:
- Anthropic: `output_config == {"effort": "low"}` next to adaptive `thinking`. Bedrock's Claude: the same two fields, inside `additionalModelRequestFields`.
- Nova: `additionalModelRequestFields.reasoningConfig`. Gemini: `generationConfig.thinkingConfig.thinkingBudget`. OpenAI and vLLM: `reasoning_effort: "low"` unchanged. Ollama: `think: true`.
- Look at Gemini's budget next to your `max_tokens`. Which one wins?

<details><summary>Hint</summary>

Keep one list of the field names that can carry the setting (`thinking`, `output_config`, `additionalModelRequestFields`, `generationConfig`, `reasoning_effort`, `think`) and print whichever of them each body has. Only the Ollama call needs a running server.
</details>

## 2. Streaming

**Use case:** show text to a user as it is generated, and still get the full text and usage at the end.

[`02_streaming.py`](examples/02_streaming.py)

```python
stream = litellm.completion(
    model="anthropic/claude-haiku-5-5", messages=messages, stream=True,
    stream_options={"include_usage": True},
    **mock("Grey waves fold and break\nsalt wind carries gull voices\nthe tide keeps its time"),
)

chunks = []
for chunk in stream:
    chunks.append(chunk)
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="|", flush=True)

full = litellm.stream_chunk_builder(chunks, messages=messages)
print("rebuilt text:", repr(full.choices[0].message.content))
print("usage:", full.usage.prompt_tokens, "in /", full.usage.completion_tokens, "out")
```

```text
Gre|y w|ave|s f|old| an|d b|rea|k
s|alt| wi|nd |car|rie|s g|ull| vo|ice|s
t|he |tid|e k|eep|s i|ts |tim|e|

chunks received: 29
rebuilt text: 'Grey waves fold and break\nsalt wind carries gull voices\nthe tide keeps its time'
usage: 15 in / 18 out
```

The `|` marks chunk boundaries. Every provider's stream format, whether Anthropic's SSE events, Gemini's or Bedrock's, arrives as OpenAI `delta` chunks. Keep the chunks: `stream_chunk_builder` turns them back into one normal response. That gives you the text, the usage and the tool calls for logging or for the next turn of a conversation.

### Exercises

**2.1 ★ `ex02_1_stream_timing.py`: time to first token**

Stream a short story (about 100 words) from `_env.FAST` with `stream_options={"include_usage": True}`. Print each delta as it arrives. Measure the time to the first content chunk and the total time, and count the chunks.

Checks:
- The concatenated deltas equal the text that `stream_chunk_builder` rebuilds.
- The rebuilt response has `usage.completion_tokens > 0`.
- The last chunk that has `choices` has a non-`None` `finish_reason`.

<details><summary>Hint</summary>

Some chunks have empty `choices` (the usage chunk) or a `None` delta. Guard both before you read `delta.content`. Use `time.perf_counter()` for timing.
</details>

**2.2 ★★ `ex02_2_two_streams.py`: two streams at once**

Stream from `_env.FAST` and `_env.ALT` concurrently using `await litellm.acompletion(..., stream=True)` and `async for`. Prefix each printed delta with a model tag so the interleaving is visible. Keep each model's chunks in its own list and rebuild both responses.

Checks:
- Both rebuilt responses have non-empty content.
- Live only: the wall time for both streams is less than the sum of the two streams' own durations.

<details><summary>Hint</summary>

Write one `async def consume(model)` coroutine, and run two of them with `asyncio.gather`.
</details>

## 3. Async and concurrent batches

**Use case:** classify thousands of items quickly without blowing through the provider's rate limit.

[`03_async_batch.py`](examples/03_async_batch.py)

```python
MAX_CONCURRENCY = 3

async def classify(sem, review, fake):
    async with sem:
        resp = await litellm.acompletion(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Reply with one word: positive, negative or neutral."},
                {"role": "user", "content": review},
            ],
            max_tokens=3,
            **mock(fake), mock_delay=1.0,
        )
        return resp.choices[0].message.content.strip()

async def main():
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    labels = await asyncio.gather(*(classify(sem, r, f) for r, f in zip(REVIEWS, FAKE, strict=True)))
```

```text
negative  Arrived broken, support never answered.
positive  Exactly as described, fast shipping!
neutral   It works, I guess. Nothing special.
positive  Best purchase this year.
negative  Stopped working after two days.
neutral   Decent value for the price.

6 calls x 1.0s each, 3 at a time: 2.2s
```

`acompletion` is the async twin of `completion`, with the same arguments and the same response. Each call waits one second, so six calls in sequence would take 6s. Three at a time finishes in two waves, about 2.2s. The semaphore matters: an unbounded `gather` over 10,000 items fires 10,000 requests at once and comes straight back with 429s. Section 7 shows `Router`, which can enforce per-deployment limits for you.

### Exercises

**3.1 ★ `ex03_1_bounded_batch.py`: classify tickets, at most four at a time**

Classify 12 support tickets as `billing`, `bug`, `feature` or `other` with `acompletion` on `_env.FAST`, with at most 4 calls in flight. Offline, give each call a mock label and `mock_delay=0.5`. Print each ticket's label and the wall time.

Checks:
- Every label, after `.strip().lower()`, is one of the four allowed values.
- An in-flight counter, incremented and decremented inside the semaphore, never exceeds 4.
- Offline: the wall time is under 2.5 s (three waves of 0.5 s, plus overhead).

<details><summary>Hint</summary>

Use the `asyncio.Semaphore` pattern from `03_async_batch.py`. Keep the counter's maximum in a variable that you update after each increment.
</details>

**3.2 ★★ `ex03_2_partial_failures.py`: one bad call must not sink the batch**

Run the same batch, but make tickets 3 and 7 fail. Offline, pass `mock_response=litellm.RateLimitError(...)` for those two. Use `asyncio.gather(..., return_exceptions=True)`, then retry only the failures once; offline, the retry gets a normal mock reply. Finally, classify the same 12 tickets with the synchronous `litellm.batch_completion`.

Checks:
- The first pass has 10 results and 2 exceptions, both `litellm.RateLimitError`.
- After the retry, all 12 tickets have a label.
- `batch_completion` returns a list of 12 responses.

<details><summary>Hint</summary>

`batch_completion` takes `messages` as a *list of message lists*, one per request.
</details>

## 4. Structured output

**Use case:** extract fields from text into a typed object you can trust.

[`04_structured_output.py`](examples/04_structured_output.py)

```python
class Invoice(BaseModel):
    vendor: str
    total: float
    currency: str
    line_items: list[str]

print("supports json schema:", litellm.supports_response_schema(model=MODEL))

resp = litellm.completion(
    model=MODEL,
    messages=[{"role": "user", "content": f"Extract the invoice.\n\n{TEXT}"}],
    response_format=Invoice,
    **mock(json.dumps({...})),
)
invoice = Invoice.model_validate_json(resp.choices[0].message.content)
```

```text
supports json schema: True
vendor='ACME Tools Ltd.' total=55.5 currency='EUR' line_items=['2x hammer', '1x saw']

bad output is caught: 3 errors, e.g. ('total',)
```

Pass a Pydantic class (or a JSON-schema dict) as `response_format`. LiteLLM turns it into whatever the provider uses for structured output. Check `supports_response_schema(model)` before relying on it for a model. **Always validate the reply anyway.** The last line of the output shows Pydantic catching a malformed reply (wrong type, missing fields) before it reaches your data.

### Exercises

**4.1 ★ `ex04_1_extract_meetings.py`: emails to typed objects**

Define a Pydantic model `Meeting` with `title: str`, `date: datetime.date`, `attendees: list[str]` and `duration_minutes: int`, constrained with `Field(gt=0)`. Extract a `Meeting` from each of three short emails using `_env.SMART` and `response_format=Meeting`. Offline, mock a JSON reply per email.

Checks:
- `litellm.supports_response_schema(model=...)` is `True` for all three models in `_env.MODELS`.
- All three replies validate, and `isinstance(m.date, datetime.date)`.
- Feeding `Meeting.model_validate_json` a reply with `"duration_minutes": 0` raises `ValidationError`.

<details><summary>Hint</summary>

Use `json.dumps({...})` to build the mock reply. Pydantic parses an ISO string such as `"2026-11-20"` into a `date`.
</details>

**4.2 ★★ `ex04_2_repair_loop.py`: ask the model to fix its own output**

Write `extract(text, schema, model, max_attempts=3)`. On a `ValidationError`, append the bad reply as an assistant message, then append a user message containing the validation error, and call again. Offline, the first mock is `{"title": "Sync", "duration_minutes": "an hour"}` and the second is valid JSON.

Checks:
- `extract` returns a valid `Meeting` on attempt 2.
- The second request's `messages` contain the text of the validation error.
- With mocks that are always invalid, `extract` raises after exactly `max_attempts` calls.

<details><summary>Hint</summary>

To make each attempt's mock different, pass `extract` a list of fake replies and pop one per attempt when `not _env.LIVE`. `str(exc)` on a `ValidationError` names each failing field.
</details>

## 5. Tool calling

**Use case:** let the model call your functions (an agent loop) with one code path for every provider.

[`05_tool_calling.py`](examples/05_tool_calling.py)

```python
TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Current weather for a city.",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                       "required": ["city"]},
    },
}]

messages = [{"role": "user", "content": "Is it warmer in Paris or Tokyo right now?"}]
for turn in range(5):
    msg = litellm.completion(model=MODEL, messages=messages, tools=TOOLS, **fake).choices[0].message
    messages.append(msg)
    if not msg.tool_calls:
        print("final answer:", msg.content)
        break
    for call in msg.tool_calls:
        args = json.loads(call.function.arguments)
        result = get_weather(**args)
        messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})
```

```text
turn 0: model called get_weather({'city': 'Paris'}) -> {'city': 'Paris', 'temp_c': 14, 'sky': 'cloudy'}
turn 0: model called get_weather({'city': 'Tokyo'}) -> {'city': 'Tokyo', 'temp_c': 21, 'sky': 'cloudy'}
final answer: Tokyo is warmer: 21°C versus 14°C in Paris, both cloudy.
```

This is the standard loop:

1. Send the messages and the tools.
2. If the reply contains `tool_calls`, run each one and append a `role: "tool"` message with the matching `tool_call_id`.
3. Call again, and repeat until the model answers in plain text.

The model asked for two tools in one turn (parallel tool calls), and the loop handled both. Anthropic natively uses `tool_use`/`tool_result` content blocks; LiteLLM converts both ways, so this exact loop also works on Claude, Gemini and Bedrock. The `range(5)` caps the loop so a confused model can't call tools forever.

### Exercises

**5.1 ★ `ex05_1_order_agent.py`: a support agent with two tools**

Give the model two tools backed by a dict of orders: `lookup_order(order_id)` and `refund_order(order_id, reason)`. Dispatch tool calls through a `{name: function}` map and cap the loop at 6 turns. Errors go back to the model instead of crashing the loop: an unknown tool name returns `{"error": "unknown tool"}`, and arguments that aren't valid JSON return `{"error": "bad arguments"}`. The user says "Order A17 arrived broken, please refund it." Offline, turn 0 fakes `lookup_order("A17")`, turn 1 fakes `refund_order("A17", "damaged")` and turn 2 is a text answer.

Checks:
- Order A17 is marked refunded in your dict.
- Every `role: "tool"` message's `tool_call_id` matches an ID in the assistant message just before it.
- The loop ends with a text answer within 6 turns.
- Calling your dispatcher with the name `"drop_tables"`, and separately with arguments `"{not json"`, returns the two error dicts.

<details><summary>Hint</summary>

Decide whether to run tools by checking `msg.tool_calls`, not `finish_reason`. Mocked tool calls report `finish_reason="stop"`, and providers differ on this field too.
</details>

**5.2 ★★ `ex05_2_tool_policy.py`: force a tool, switch model, refuse a dangerous one**

1. Force a tool with `tool_choice={"type": "function", "function": {"name": "lookup_order"}}` and confirm the first tool call is `lookup_order`.
2. Run your 5.1 agent unchanged on `_env.ALT` (Nova) to show the same loop works on another model family.
3. Add a `delete_customer(customer_id)` tool. Your dispatcher refuses it unless *your code* set `confirmed=True` for that customer. Nothing the model sends can change the outcome.

Checks:
- (1) `msg.tool_calls[0].function.name == "lookup_order"`.
- (2) Live: Nova reaches a text answer and A17 is refunded.
- (3) After a faked `delete_customer` call, the customer still exists and the tool message says the action was refused.

<details><summary>Hint</summary>

Keep authorization outside the model: the dispatcher checks your own state, not anything in `call.function.arguments`.
</details>

## 6. Errors, retries and fallbacks

**Use case:** survive rate limits and outages, and handle each kind of error correctly.

[`06_errors_fallbacks.py`](examples/06_errors_fallbacks.py)

```python
try:
    litellm.completion(model="openai/gpt-4o-mini", messages=messages, mock_response=err)
except litellm.RateLimitError as e:
    ...  # back off and retry
except litellm.ContextWindowExceededError as e:
    ...  # trim input or use a bigger model
except litellm.AuthenticationError as e:
    ...  # fix the key, do not retry

resp = litellm.completion(
    model="anthropic/claude-sonnet-5-5",
    messages=messages,
    mock_response=litellm.ServiceUnavailableError("overloaded", llm_provider="anthropic",
                                                  model="claude-sonnet-5-5"),
    fallbacks=[{"model": "openai/gpt-4o-mini", "mock_response": "hello from the fallback"}],
)
```

```text
RateLimitError       status=429  -> back off and retry
ContextWindowExceeded status=400 -> trim input or use a bigger model
AuthenticationError  status=401  -> fix the key, do not retry

primary failed; answer came from gpt-4o-mini -> 'hello from the fallback'
```

- **One set of exceptions.** Every provider's errors are mapped to OpenAI-style exception classes, so one `except` block handles them all. They also subclass the `openai` SDK's exceptions, so existing handlers keep working.
- **Retry only what retrying can fix.** Retry 429, 500, 503 and timeouts. Don't retry 401, 400 or context-window errors; they will fail the same way again. `completion(..., num_retries=3)` is not selective: in 1.110.2 it retries every error type, 401 and 400 included, and by default retries at once with no wait. Pass `retry_strategy="exponential_backoff_retry"` for backoff, and write your own loop when only some errors should be retried (exercise 6.3).
- **Fallbacks** try other models in order when the primary fails. An entry can be a model string, or a dict that overrides parameters for that model (its own `api_key`, `api_base` or, here, a mock).
- **Gotcha:** `ContextWindowExceededError` is a subclass of `BadRequestError`. When you catch both, put the more specific one first.

### Exercises

**6.1 ★ `ex06_1_error_triage.py`: map each error to an action**

Write `triage(exc) -> str` that returns one of `"retry"`, `"shrink-input"`, `"fix-credentials"`, `"blocked-by-policy"` or `"fix-request"`. Raise each of the following on `_env.FAST` with `mock_response=<exception instance>`, catch it, and print the class name, `status_code` and `triage()` result: `RateLimitError`, `ServiceUnavailableError`, `InternalServerError`, `Timeout`, `ContextWindowExceededError`, `ContentPolicyViolationError`, `AuthenticationError` and `BadRequestError`.

Checks:
- Rate limit, 503, 500 and timeout map to `"retry"`; context window to `"shrink-input"`; authentication to `"fix-credentials"`; content policy to `"blocked-by-policy"`; plain bad request to `"fix-request"`.
- `isinstance(ContextWindowExceededError(...), litellm.BadRequestError)` is `True`. Your `triage` must still return `"shrink-input"` for it.

<details><summary>Hint</summary>

The positional order differs between classes: `RateLimitError`, `ServiceUnavailableError`, `InternalServerError` and `AuthenticationError` take `(message, llm_provider, model)`, while `Timeout`, `BadRequestError`, `ContextWindowExceededError` and `ContentPolicyViolationError` take `(message, model, llm_provider)`. Pass `llm_provider=` and `model=` by keyword, as `06_errors_fallbacks.py` does. Check the more specific classes first.
</details>

**6.2 ★ `ex06_2_fallback_chain.py`: SMART, then FAST, then ALT**

Call `_env.SMART` with a mocked `ServiceUnavailableError` and `fallbacks=[{...FAST...}, {...ALT...}]`, where each entry is a dict with its own `mock_response`. Print which model answered. Then make the FAST entry fail too, and finally make every entry fail.

Checks:
- Run 1 is answered by FAST and run 2 by ALT; check `resp.model`. It comes back without the provider prefix, so compare it with `_env.FAST.removeprefix("bedrock/")`.
- Run 3 raises an exception, and your script catches it and prints its class.

<details><summary>Hint</summary>

A fallback entry's `mock_response` can itself be an exception instance. Look at which exception class run 3 raises: it is not the one you mocked.
</details>

**6.3 ★★ `ex06_3_backoff.py`: your own retry with backoff**

Write `call_with_backoff(make_call, max_attempts=4, base=0.2)` with exponential backoff and full jitter: sleep `random.uniform(0, base * 2**attempt)`. It retries only errors that `triage()` from 6.1 calls `"retry"`. Test it with a `make_call` closure whose first two calls mock a `RateLimitError` and whose third call succeeds.

Checks:
- The test case succeeds after exactly 3 attempts.
- A mocked `AuthenticationError` is raised after 1 attempt, with no sleep.
- The total time slept is at most `base * (1 + 2 + 4)`.

<details><summary>Hint</summary>

Inject the sleep function (`sleep=time.sleep`) so a test can record the delays instead of waiting.
</details>

## 7. Router: load balancing and failover

**Use case:** spread traffic over several deployments of the same model, such as two API keys or two regions, and fail over to a different model when one breaks.

[`07_router.py`](examples/07_router.py)

```python
router = Router(
    model_list=[
        {"model_name": "fast", "litellm_params": {"model": "openai/gpt-4o-mini", "api_key": "sk-fake-a", ...}},
        {"model_name": "fast", "litellm_params": {"model": "openai/gpt-4o-mini", "api_key": "sk-fake-b", ...}},
        {"model_name": "smart", "litellm_params": {"model": "anthropic/claude-sonnet-5-5", ...}},
        {"model_name": "flaky", "litellm_params": {"model": "openai/gpt-4o", ...}},
    ],
    routing_strategy="simple-shuffle",
    num_retries=1,
    fallbacks=[{"flaky": ["smart"]}],
)

router.completion(model="fast", messages=msgs)     # model = the alias, not the provider ID
```

```text
100 calls to 'fast': {'from deployment A': 42, 'from deployment B': 58}
'flaky' failed; the call was answered by 'from smart'
```

The key idea is that **`model_name` is an alias, a model group, and each entry is one deployment in that group.** Callers ask for `"fast"`, and the router picks a deployment. The 42/58 split is random shuffling; real traffic would be similar.

What the router adds over a plain `completion()`:

| Feature | Setting |
| --- | --- |
| Pick a deployment | `routing_strategy`: `simple-shuffle` (default; weight entries with `weight` or `rpm`), `least-busy`, `latency-based-routing`, `cost-based-routing`, `usage-based-routing-v2` |
| Respect rate limits | `rpm` / `tpm` on each deployment |
| Take failing deployments out of rotation | `allowed_fails`, `cooldown_time` |
| Retry, then fail over to another group | `num_retries`, `fallbacks` |
| Special failovers | `context_window_fallbacks` (to a longer-context model), `content_policy_fallbacks` |
| Share state across processes | `redis_host` / `redis_port`, so cooldowns and usage counts are shared |

`router.acompletion`, `router.embedding` and streaming all work the same way.

This router picks among deployments of one model group. To choose between different models per request, based on the prompt or on what users liked, see section 14.

**Gotcha:** `Router` deep-copies `model_list`, so every value must be copyable. My first attempt put an exception object in `mock_response`, and it crashed with `TypeError: ServiceUnavailableError.__init__() missing 2 required positional arguments`. Pass `mock_testing_fallbacks=True` on the call instead.

### Exercises

**7.1 ★ `ex07_1_two_regions.py`: weighted load balancing across regions**

Build a `Router` with one model group, `claude-fast`, holding two deployments of `_env.FAST`: one with `aws_region_name="us-west-2"` and `weight: 3`, the other with `"us-east-1"` and `weight: 1`. Give each `model_info={"id": "<region>"}`, and offline a mock reply. Make 400 calls offline (40 live) and count which deployment answered, using `resp._hidden_params["model_id"]`.

Checks:
- Both regions served traffic.
- us-west-2's share is between 65% and 85% (offline; with 40 live calls allow 55% to 95%).

<details><summary>Hint</summary>

`weight` goes in `litellm_params`. `_hidden_params["model_id"]` is the `model_info.id` of the deployment that answered, so it works live too.
</details>

**7.2 ★ `ex07_2_group_fallbacks.py`: general and context-window fallbacks**

Make three groups, `smart`, `fast` and `alt`, with `fallbacks=[{"smart": ["fast", "alt"]}]` and `context_window_fallbacks=[{"fast": ["smart"]}]`.

1. Call `smart` with `mock_testing_fallbacks=True`.
2. Give the `fast` deployment `model_info={"max_input_tokens": 50}`, build the router with `enable_pre_call_checks=True`, and send `fast` a 500-word prompt. Then send it a short prompt.

Checks:
- (1) is answered by the `fast` group.
- (2) the long prompt is answered by `smart` and the short one by `fast`.

<details><summary>Hint</summary>

Give each deployment a `model_info.id` and check `_hidden_params["model_id"]`, so the checks hold live as well as offline.
</details>

**7.3 ★★ `ex07_3_cooldown.py`: take a broken deployment out of rotation**

One group, `g`, with two deployments. `broken` is `openai/gpt-4o-mini` with a fake key and `api_base="http://127.0.0.1:9/v1"`, a closed port, so it fails for real even offline. `healthy` is `_env.FAST`. Set `allowed_fails=1`, `cooldown_time=30` and `num_retries=2`, and make 20 calls. A `CustomLogger` counts successes and failures per deployment, using `kwargs["standard_logging_object"]["model_id"]`. Section 10 explains `CustomLogger`; all you need here is a subclass with `log_success_event` and `log_failure_event`, registered with `litellm.callbacks = [YourLogger()]`.

Checks:
- All 20 calls succeed.
- `broken` fails at most twice, and is never tried again after it enters cooldown.

<details><summary>Hint</summary>

Name the logger's parameters exactly `kwargs, response_obj, start_time, end_time`. LiteLLM passes them by keyword, and a hook with other parameter names fails silently. Set the logger level of `"LiteLLM Router"` to `CRITICAL` to hide the expected tracebacks.
</details>

## 8. Counting tokens, pricing calls and capping spend

**Use case:** know what a call will cost before you make it, what it did cost afterwards, and stop a runaway job.

[`08_cost_and_budget.py`](examples/08_cost_and_budget.py)

```python
print("prompt tokens (estimate):", litellm.token_counter(model=MODEL, messages=messages))
print("context window:", litellm.get_model_info(MODEL)["max_input_tokens"])
print(f"this call cost ${litellm.completion_cost(resp):.6f}")

info = litellm.get_model_info(model)
p, c = info["input_cost_per_token"] * 1e6, info["output_cost_per_token"] * 1e6

class BudgetGuard:
    """Refuse calls once recorded spend reaches the limit."""

    def __init__(self, limit_usd):
        self.limit, self.spent = limit_usd, 0.0

    def completion(self, **kwargs):
        if self.spent >= self.limit:
            raise RuntimeError(f"budget ${self.limit} reached (spent ${self.spent:.6f})")
        resp = litellm.completion(**kwargs)
        self.spent += litellm.completion_cost(resp)
        return resp
```

```text
prompt tokens (estimate): 188
context window: 1000000
this call cost $0.000220
anthropic/claude-haiku-5-5     $   0.10 per 1M in  $   0.50 per 1M out
anthropic/claude-sonnet-5-5    $   2.00 per 1M in  $  10.00 per 1M out
openai/gpt-4o                  $   2.50 per 1M in  $  10.00 per 1M out

call 6 refused: budget $0.001 reached (spent $0.001100)
```

- `token_counter` is an **estimate** for non-OpenAI models; the provider's own count, in `resp.usage`, is the real one. Use the estimate for pre-flight checks such as "will this fit the context window?".
- `get_model_info` returns context size, prices and capability flags (`supports_vision`, `supports_function_calling`, ...).
- Prices come from LiteLLM's price table: the current one downloaded at import by default, or the copy bundled with your LiteLLM version when `LITELLM_LOCAL_MODEL_COST_MAP=True`. Some models have a second, higher rate for long prompts (Haiku 5.5 costs five times as much per token above 100k prompt tokens), so `cost_per_token(prompt_tokens=1_000_000, ...)` does not give the base rate; read it from `get_model_info`. For a private or fine-tuned model, register prices with `litellm.register_model({...})`. Some models also have a price per service tier (`input_cost_per_token_priority`, `..._flex`); section 12 shows how a Bedrock call picks its tier and which tier it is billed at.

**Gotcha: don't rely on `litellm.max_budget` in 1.110.2.** The SDK has a global `litellm.max_budget` that should raise `BudgetExceededError`. I set it, made five calls costing $0.0011 in total, and `litellm._current_cost` stayed at `0.0`. The code that accumulates spend (`litellm_logging.py`) only counts results that are plain `dict`s, and a chat completion response is not a dict. Use your own guard like the one above, or the proxy's per-key budgets (section 13). Notice that the guard checks *before* each call, so spend can pass the limit by up to one call. Every budget system works this way.

### Exercises

**8.1 ★ `ex08_1_preflight.py`: estimate before you spend**

Write `estimate(model, messages, max_tokens) -> (input_tokens, worst_case_usd)` using `token_counter` and `cost_per_token`, assuming every one of `max_tokens` is used. For a document of about 300 words and `max_tokens=200`, print a table for the three models: estimated input tokens, context window, whether the prompt fits, and worst-case cost. Then call the cheapest model.

Checks:
- The call's actual `completion_cost` is at most the worst-case estimate.
- Live only: the estimate is within ±25% of `usage.prompt_tokens`.
- `estimate` raises `ValueError` when the input exceeds `get_model_info(model)["max_input_tokens"]`. Test it with a model you register with a 100-token window.

<details><summary>Hint</summary>

`litellm.register_model({"bedrock/tiny-test": {"max_input_tokens": 100, "input_cost_per_token": 1e-6, "output_cost_per_token": 1e-6, "litellm_provider": "bedrock", "mode": "chat"}})`.
</details>

**8.2 ★ `ex08_2_team_budgets.py`: per-team budget guard**

Extend section 8's `BudgetGuard`: `guard.completion(team="search", **kwargs)` takes per-team limits from a dict, protects its counters with a `threading.Lock`, and raises your own `BudgetExceeded(team, spent, limit)`. Run calls for two teams until one is refused. Then run 8 threads against a fresh guard for one team.

Checks:
- One team is refused while the other keeps working.
- Sequentially, the overshoot is at most one call's cost.
- With 8 threads, the overshoot is at most 8 calls' cost. Print it, and explain in a comment why it can exceed one call.

<details><summary>Hint</summary>

The lock protects the counter, but the check and the spend are separate steps with a network call in between. Every in-flight call has already passed the check.
</details>

**8.3 ★★ `ex08_3_custom_pricing.py`: price a private model**

Register `bedrock/my-finetuned-haiku` with `litellm.register_model`, at $1 per million input tokens and $5 per million output tokens. Make a mocked call to it and compute its cost three ways: `completion_cost(resp)`, `cost_per_token(...)` with the response's usage, and by hand.

Checks:
- All three numbers agree to within 1e-12.
- `get_model_info("bedrock/my-finetuned-haiku")` returns your prices.

<details><summary>Hint</summary>

The registered entry needs `litellm_provider` and `mode`. Offline, a mocked call reports 10 tokens in and 20 out.
</details>

## 9. Caching

**Use case:** don't pay twice for identical requests, for example re-running an eval or a test suite.

[`09_caching.py`](examples/09_caching.py)

```python
from litellm.caching.caching import Cache

litellm.cache = Cache(type="local")

resp = litellm.completion(model="openai/gpt-4o-mini", messages=messages, caching=True, ...)
resp._hidden_params.get("cache_hit")   # True on a hit

litellm.completion(..., cache={"no-cache": True})   # bypass the cache for one call
```

```text
call 1: 'Canberra.'  id=chatcmpl-1cf74d69-b17a-4a83-b47f-8412ddbe5edc  cache_hit=None
call 2: 'Canberra.'  id=chatcmpl-1cf74d69-b17a-4a83-b47f-8412ddbe5edc  cache_hit=True
call 3 with no-cache: cache_hit = None
```

The second call returned the *same response ID*: it came from the cache, not the provider. The cache key covers the model, the messages and the parameters, so any change is a miss.

| `type=` | Use for |
| --- | --- |
| `"local"` | One process, in memory |
| `"redis"` (`host`, `port`, `password`) | Shared by many processes or pods |
| `"s3"`, `"gcs"`, `"azure-blob"` | Survives restarts; cheap long-term storage |
| `"redis-semantic"`, `"qdrant-semantic"` | Also matches *similar* prompts, using embeddings |

Use `ttl=` to make entries expire. The old `"disk"` backend has been removed. 1.110.2 logs *"Ignoring disk_cache_dir, the disk cache backend was removed"*, so for a cache that survives restarts on a laptop, run a local Redis.

This response cache is a different thing from provider **prompt caching**, where Anthropic or OpenAI bill a repeated prompt prefix at a discount. That happens on the provider side and still returns a fresh answer.

**Gotcha:** the first cache hit in a process is slow. It pays a one-off setup cost of about half a second, with or without `mock_delay`, so time the third call when you measure the speed-up; later hits return in under a millisecond. A hit never reaches the mock, so `mock_delay` does not slow it down.

### Exercises

**9.1 ★ `ex09_1_cache_rules.py`: prove the cache key rules**

With `litellm.cache = Cache(type="local")`, assert each of these on `_env.FAST`, using `resp._hidden_params.get("cache_hit")` (`_hidden_params` is a dict LiteLLM attaches to every response; a miss shows as `None`, not `False`):

1. Repeating an identical call is a hit.
2. The same call with a different `max_tokens` is a miss.
3. The same messages on `_env.ALT` are a miss.
4. `cache={"no-cache": True}` doesn't return a cached reply.
5. After a call with `cache={"no-store": True}`, the next identical call is a miss.
6. An entry stored with `cache={"ttl": 1}` is a miss after 1.5 seconds.

Checks: the six asserts above.

<details><summary>Hint</summary>

Use different user messages for cases 5 and 6, so earlier cases haven't already cached them. Pass `caching=True` on each call.
</details>

**9.2 ★★ `ex09_2_cached_eval.py`: what does a cached rerun cost?**

Run a 10-question eval twice with caching on. A `CustomLogger` (set up as in exercise 7.3; section 10 explains it) sums `standard_logging_object["response_cost"]` and counts `standard_logging_object["cache_hit"]` for each run. Report the cost of each run and the saving.

Checks:
- Run 2 has 10 cache hits and a logged cost of `0.0`.
- For a cached response, compare `litellm.completion_cost(resp)` with `resp._hidden_params["response_cost"]`, and assert they differ. Write a comment saying which one to trust for billing, and why.

<details><summary>Hint</summary>

`completion_cost` re-prices the response from its token counts and doesn't know it came from the cache.
</details>

## 10. Callbacks: logging, metrics and cost attribution

**Use case:** record the model, latency, tokens, cost and an owner tag for every call in one place, without touching any call site.

[`10_callbacks.py`](examples/10_callbacks.py)

```python
from litellm.integrations.custom_logger import CustomLogger

class UsageLog(CustomLogger):
    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        cost = kwargs.get("response_cost") or 0.0
        tags = kwargs["litellm_params"]["metadata"].get("tags")
        print(f"[ok]   {kwargs['model']:22} {(end_time - start_time).total_seconds() * 1000:5.0f}ms "
              f"{response_obj.usage.total_tokens:4} tok  ${cost:.6f}  tags={tags}")

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        exc = kwargs.get("exception")
        print(f"[fail] {kwargs['model']:22} {type(exc).__name__}: {str(exc)[:50]}")

litellm.callbacks = [UsageLog()]
litellm.completion(model="openai/gpt-4o-mini", messages=msgs, metadata={"tags": ["demo"]}, ...)
```

```text
[ok]   gpt-4o-mini              214ms   30 tok  $0.000013  tags=['demo']
[ok]   claude-haiku-5-5           7ms   30 tok  $0.000011  tags=['demo']
[fail] gpt-4o                 RateLimitError: litellm.RateLimitError: slow down

running total: $0.000024
```

- `metadata={...}` on a call is passed to every callback. Use it for tags such as the feature, user or experiment ID.
- For async code, override `async_log_success_event` and `async_log_failure_event`.
- You often don't need a custom class. Built-in integrations take a string: `litellm.callbacks = ["langfuse"]`, `["otel"]`, `["datadog"]`, `["s3_v2"]` and more, configured through each tool's env vars. Section 18 covers them.
- The first call's 214ms is one-off import and client setup. The real per-call overhead is the 7ms on the second line.

### Exercises

**10.1 ★ `ex10_1_jsonl_logger.py`: one log line per call**

Write a `CustomLogger` that appends one JSON line per call to `calls.jsonl`, with the timestamp, model, status, latency in ms, prompt and completion tokens, cost, tags, and error type if any. Make six calls across the three models with `metadata={"tags": [...]}`, one of them a mocked failure. Then read the file back and print the cost per tag.

Checks:
- The file has exactly 6 lines, and exactly 1 has status `failure`.
- The sum of logged costs equals the sum of `_hidden_params["response_cost"]` over the successful responses.

<details><summary>Hint</summary>

`kwargs["standard_logging_object"]` already holds most of the fields (`status`, `response_cost`, `request_tags`, `prompt_tokens`, `model`). Sync success hooks run in a background thread, so sleep briefly before you read the file. Delete the file at the start of each run.
</details>

**10.2 ★★ `ex10_2_async_redacting_logger.py`: async logging without leaking PII**

Write an async logger (`async_log_success_event`) that logs the messages as well, but replaces every email address with `<email>` before writing. Send 5 concurrent `acompletion` calls whose prompts contain email addresses.

Checks:
- The log has 5 entries, and no logged text contains `@`.
- The prompts sent to the model still contain the real addresses. Redaction applies to the log only.

<details><summary>Hint</summary>

Read the messages from `standard_logging_object["messages"]`. To keep message content out of every logger, LiteLLM has `litellm.turn_off_message_logging = True`.
</details>

## 11. Comparing models on your own task

**Use case:** pick a model by running the same small eval on several and comparing accuracy, cost and latency. This is where LiteLLM's one interface pays off most.

[`11_compare_models.py`](examples/11_compare_models.py)

```python
litellm.drop_params = True

MODELS = ["anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5", "openai/gpt-4o-mini"]
CASES = [
    ("What is 17 * 23? Reply with the number only.", "391"),
    ("Capital of Canada? One word.", "Ottawa"),
    ("Is 91 prime? Reply yes or no.", "no"),
    ("Reverse the string 'litellm'. Reply with the result only.", "mlletil"),
]

async def run_case(model, i, prompt):
    start = time.perf_counter()
    resp = await litellm.acompletion(model=model, messages=[{"role": "user", "content": prompt}],
                                     max_tokens=20, temperature=0, **fake)
    return (resp.choices[0].message.content.strip(), litellm.completion_cost(resp),
            time.perf_counter() - start)
```

```text
model                            acc        cost  p50 s
anthropic/claude-haiku-5-5     3/4   $0.00004400   0.56
anthropic/claude-sonnet-5-5    4/4   $0.00088000   0.16
openai/gpt-4o-mini             2/4   $0.00005400   0.15
```

The answers are mocked, so in this run the accuracy and latency numbers only show the shape of the report. Haiku's 0.56s includes the one-off warm-up from section 10. With `LIVE=1` the table is real.

**Gotcha: `drop_params`.** Without `litellm.drop_params = True`, this script failed on its first model:

```text
litellm.exceptions.UnsupportedParamsError: litellm.UnsupportedParamsError: claude-haiku-5-5 does not
support temperature=0. Only temperature=1 is supported. To drop unsupported params, set
`litellm.drop_params = True`.
```

Models differ in which parameters they accept. By default LiteLLM **refuses** a parameter the target model can't take, so you find out. With `drop_params=True` it **silently removes** the parameter instead. That's convenient for a multi-model sweep, but it means some models run under different settings than you asked for. Prefer setting it per call (`completion(..., drop_params=True)`) when you need it, rather than globally.

### Exercises

**11.1 ★ `ex11_1_eval_harness.py`: a reusable eval harness**

Write 8 test cases, each with its own checker function: exact match, contains, numeric tolerance or regex. Run every case on all three models concurrently, at most 4 calls at a time. Report each model's accuracy, total cost, and p50 and p95 latency, and write the results to `results.csv`. Offline, give each model its own table of fake answers so the accuracies differ.

Checks:
- There are 24 results.
- `results.csv` has a header row and 3 data rows.
- Offline: each model's accuracy equals what its fake answers imply.

<details><summary>Hint</summary>

`statistics.quantiles(latencies, n=20)[18]` gives p95. Normalise answers with `.strip().rstrip(".").lower()` before you compare them.
</details>

**11.2 ★★ `ex11_2_param_support.py`: "supported" is not the same as "accepted"**

For each model, print whether `"temperature"` is in `litellm.get_supported_openai_params(model=...)`. Then call each model with `temperature=0`, without `drop_params`, and record which ones raise `UnsupportedParamsError`. Retry those with `drop_params=True` on the call.

Checks:
- `_env.FAST` lists `temperature` as supported, yet raises `UnsupportedParamsError` for `temperature=0`.
- With per-call `drop_params=True` the same call succeeds.
- `litellm.drop_params` is still `False` at the end of the script.

<details><summary>Hint</summary>

`get_supported_openai_params` lists parameter *names*. Some models restrict the *values*: Claude Haiku 5.5 only accepts `temperature=1`. This check works offline.
</details>

---

## 12. The proxy: one endpoint for every app

**Use case:** many apps, scripts and tools (anything that speaks the OpenAI API) share one endpoint. Provider keys live only on the server.

[`examples/proxy/config.yaml`](examples/proxy/config.yaml)

```yaml
model_list:
  - model_name: chat                      # the alias clients ask for
    litellm_params:
      model: anthropic/claude-sonnet-5-5
      api_key: os.environ/ANTHROPIC_API_KEY
      mock_response: "Hi from Claude (via the proxy)"   # delete this line for real calls
  - model_name: chat-cheap
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY
      mock_response: "Hi from GPT-4o mini (via the proxy)"
  - model_name: chat-broken                 # always fails, to show fallbacks
    litellm_params:
      model: openai/gpt-4o
      api_key: sk-invalid
      api_base: http://127.0.0.1:9/v1

router_settings:
  num_retries: 1
  fallbacks: [{"chat-broken": ["chat-cheap"]}]

litellm_settings:
  drop_params: true

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

The `model_list` and `router_settings` are the same structure as the `Router` in section 7. `os.environ/NAME` reads a secret from the environment, so no key is written in the file. `chat-broken` fails for real: it points at a closed local port, so its fallback is triggered by a genuine connection error rather than a mock.

Start the proxy. It runs in the foreground, so use a second shell for the check:

```bash
cd examples/proxy
export LITELLM_MASTER_KEY=sk-master-demo ANTHROPIC_API_KEY=unused OPENAI_API_KEY=unused
export LITELLM_LOCAL_MODEL_COST_MAP=True          # use the bundled price table instead of downloading it
uv run litellm --config config.yaml --port 4000
```

```bash
curl -s localhost:4000/health/liveliness          # in another shell: "I'm alive!"
```

**Running the proxy examples.** The same four rules apply to every proxy run from here to section 22:

- **One proxy per port.** Most runs use port 4000. Stop the previous proxy with Ctrl-C before you start the next one, or the new one fails with "address already in use".
- **A new shell has none of your exports.** Where a step says "in another shell", `cd` to the same folder and export `LITELLM_MASTER_KEY` (and whatever else the client reads) again.
- **Stop the helpers when a subsection ends.** Fake providers are started in the background with `&`. List them with `jobs` and stop them with `kill %1` (`%2`, ...). If one is still running when a later block starts it again, skip that line.
- **"Section 13's Postgres" means the `litellm-tutorial-db` container** on port 55432. Section 13 creates it with `docker run`, and its Compose part removes it. When a later section needs it, run `docker start litellm-tutorial-db`, or the `docker run` line from section 13 again if the container is gone.

Or run the official image instead, which needs no Python environment at all. The tag matches the pinned SDK version:

```bash
docker run -d --name litellm-proxy -p 127.0.0.1:4000:4000 \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  -e LITELLM_MASTER_KEY -e ANTHROPIC_API_KEY -e OPENAI_API_KEY \
  ghcr.io/berriai/litellm:v1.110.2 --config /app/config.yaml --port 4000
docker logs -f litellm-proxy                       # Ctrl-C to stop following
docker rm -f litellm-proxy                         # when you're done
```

- The image's entrypoint is the `litellm` CLI, so everything after the image name is the same arguments as `uv run litellm`.
- `-e NAME` with no value copies that variable from your shell, so the keys never appear in the command or in shell history. The `os.environ/...` references in the config read them inside the container.
- `-p 127.0.0.1:4000:4000` publishes the port on localhost only. A bare `-p 4000:4000` would expose the proxy to your whole network.

`client.py` below, and the no-database error at the end of this section, gave identical output against the container and against `uv run litellm`. Section 13 runs the container together with Postgres using Docker Compose.

Call it with curl:

```bash
curl -s localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"model":"chat","messages":[{"role":"user","content":"hello"}]}'
```

```json
{
    "id": "chatcmpl-87fe9aab-b9d4-4a5c-b2b3-e0f5f298c6e6",
    "model": "chat",
    "object": "chat.completion",
    "choices": [{"finish_reason": "stop", "index": 0,
                 "message": {"content": "Hi from Claude (via the proxy)", "role": "assistant"}}],
    "usage": {"completion_tokens": 20, "prompt_tokens": 10, "total_tokens": 30}
}
```

Or call it with the plain OpenAI SDK. [`examples/proxy/client.py`](examples/proxy/client.py) contains no LiteLLM import at all. Run it with `LITELLM_KEY=$LITELLM_MASTER_KEY uv run python client.py`:

```python
client = OpenAI(base_url="http://localhost:4000", api_key=os.environ["LITELLM_KEY"])

raw = client.chat.completions.with_raw_response.create(model=alias, messages=[...])
raw.headers.get("x-litellm-model-group")
raw.headers.get("x-litellm-response-cost")
raw.headers.get("x-litellm-attempted-fallbacks")
```

```text
models: ['chat', 'chat-cheap', 'chat-broken']
chat         -> 'Hi from Claude (via the proxy)'  model=chat  cost=$0.000220  fallbacks=0
chat-cheap   -> 'Hi from GPT-4o mini (via the proxy)'  model=chat-cheap  cost=$0.000013  fallbacks=0
chat-broken  -> 'Hi from GPT-4o mini (via the proxy)'  model=chat-cheap  cost=$0.000013  fallbacks=1
```

The `x-litellm-*` response headers tell the client which model group actually answered, what the call cost and whether a fallback was used. Here `chat-broken` was answered by `chat-cheap` after one fallback.

Without a database, only the master key works. A wrong key returned `{"error":{"message":"No connected db.","code":"400"}}` instead of a 401. For per-user keys, add a database, as in the next section.

### Through a cloud platform: AWS Bedrock

So far the proxy has called model providers **directly**: `anthropic/...` with an Anthropic key, `openai/...` with an OpenAI key. The other way to reach the same models is **through a cloud platform**: AWS Bedrock, Microsoft Foundry (Azure) or Google Vertex AI host models from Anthropic, Meta, Mistral, Amazon, OpenAI and others inside your cloud account. LiteLLM treats each platform as a provider of its own, with its own prefix, its own request format and its own authentication:

| | Direct provider | Through a cloud platform |
| --- | --- | --- |
| Examples | `anthropic/claude-sonnet-5-5`, `openai/gpt-4o` | `bedrock/us.anthropic.claude-sonnet-5-5`, `azure/<deployment>`, `vertex_ai/gemini-2.5-flash` |
| Who bills you | The model vendor, on a separate contract | Your cloud bill, under your existing agreement and committed spend |
| Authentication | A vendor API key | The cloud's identity: IAM roles (AWS), Entra ID (Azure), service accounts (Google) |
| Network path | The public internet to the vendor | Can stay on your cloud network: VPC endpoints / PrivateLink, Private Service Connect |
| Data handling | The vendor's terms | The cloud's terms, in a region you choose |
| Quotas | Per vendor account | Per cloud account, per region, per model; raised through the cloud's quota tooling |
| New models and features | First | Usually days or weeks later, sometimes with platform-specific options |
| Platform extras | — | Bedrock: Guardrails, Knowledge Bases, inference profiles, provisioned throughput. Azure: content filters, data zones, provisioned throughput units. Vertex AI: grounding with Google Search, provisioned throughput |

Organisations that already run on a cloud usually go through its platform: there is no new vendor contract, no API key to rotate, and the cloud's IAM, audit trail (CloudTrail) and network controls apply. This subsection covers Bedrock, which the tutorial's notebooks and exercises already call. The next two cover Microsoft Azure and Google Vertex AI the same way, and the last covers calling providers directly, including models you host yourself.

**The model string.** `bedrock/[route/]<model id>`. The model ID takes several forms, and the form decides where the request runs and what it costs:

| Model ID form | Example | Runs in | Notes |
| --- | --- | --- | --- |
| Base model ID | `anthropic.claude-haiku-5-5` | The region you call | Newer models are offered only through an inference profile: this one returned 400 `Invocation of model ID ... with on-demand throughput isn't supported` |
| Regional cross-region inference profile | `us.anthropic.claude-haiku-5-5` (also `eu.`, `apac.`) | Any region in that geography | Higher throughput; keeps data in the geography. 10% dearer than the base model in LiteLLM's 1.110.2 price table |
| Global inference profile | `global.anthropic.claude-haiku-5-5` | Any commercial region worldwide | Highest throughput; base price |
| Application inference profile ARN | `arn:aws:bedrock:us-west-2:123456789012:application-inference-profile/a1b2c3` | As the profile defines | Tags usage for cost allocation per team or app. Pass `base_model` so LiteLLM can price it |
| Provisioned throughput or imported model ARN | `arn:aws:bedrock:...:provisioned-model/...` | Your reserved capacity | Billed by the hour, not per token |

**The route.** For most chat models LiteLLM uses Bedrock's **Converse** API, one request format for every model family. `bedrock/invoke/<id>` uses the **Invoke** API instead, which takes each vendor's native body; use it only when a model or feature isn't supported by Converse. `bedrock/converse/<id>` forces Converse.

**The identity.** LiteLLM signs Bedrock requests with AWS Signature Version 4, using boto3 credentials. It takes the first of these that is set:

| Order | Parameters | Use it for |
| --- | --- | --- |
| 1 | `aws_web_identity_token` + `aws_role_name` + `aws_session_name` | Exchanging an OIDC token for AWS credentials (EKS IRSA-style, GitHub Actions) |
| 2 | `aws_role_name` (+ `aws_session_name`, `aws_external_id`) | Assuming a role: another account per team, or a narrower role for the proxy |
| 3 | `aws_profile_name` | A named profile from `~/.aws/config` (SSO profiles in development) |
| 4 | `aws_access_key_id` + `aws_secret_access_key` + `aws_session_token` | Temporary credentials you obtained yourself |
| 5 | `aws_access_key_id` + `aws_secret_access_key` | Long-lived keys. Avoid them; this tutorial's `_env.py` refuses to load when they are in `.env.local`, and warns when they are exported in the shell |
| 6 | Nothing | boto3's default chain: environment, `AWS_PROFILE`, then the workload's role (EKS Pod Identity, IRSA, ECS task role, EC2 instance profile). **The production default** |

Instead of signing, a **Bedrock API key** can be sent as a bearer token (`api_key=` or `AWS_BEARER_TOKEN_BEDROCK`). It is handy for quick tests; a long-term Bedrock API key is a long-lived secret, while a short-term one expires within hours. Two more parameters matter: `aws_region_name` (otherwise `AWS_REGION_NAME`, then `AWS_REGION`) decides the endpoint and the signature, and `aws_bedrock_runtime_endpoint` overrides the endpoint URL, for a VPC interface endpoint, for example (`https://vpce-...bedrock-runtime.us-west-2.vpce.amazonaws.com`).

**What LiteLLM sends.** [`examples/bedrock/fake_bedrock.py`](examples/bedrock/fake_bedrock.py) is a fake Bedrock runtime and STS. It records every request, reads the SigV4 `Authorization` header to show which key, region and service signed it, and returns AWS-style errors on demand. [`examples/bedrock/bedrock_inspect.py`](examples/bedrock/bedrock_inspect.py) points the SDK at it with `aws_bedrock_runtime_endpoint`:

```python
def call(label: str, model: str, show_body: bool = False, **kwargs: object) -> None:
    """Make one call against the fake Bedrock and print the reply and what reached the wire."""
    httpx.get(f"{FAKE}/_reset")
    try:
        r = litellm.completion(model=model, messages=kwargs.pop("messages", MSGS), max_tokens=64,
                               aws_bedrock_runtime_endpoint=FAKE, num_retries=0, **kwargs)
        ...

call("regional inference profile", "bedrock/us.anthropic.claude-haiku-5-5", show_body=True)
call("same model, Invoke route", "bedrock/invoke/us.anthropic.claude-haiku-5-5", show_body=True)
call("application inference profile ARN", "bedrock/arn:aws:bedrock:us-west-2:123456789012:application-inference-profile/"
     "a1b2c3", base_model="anthropic.claude-haiku-5-5")
call("tools", "bedrock/us.anthropic.claude-haiku-5-5", show_body=True, tools=TOOLS)
call("Bedrock Guardrails on the call", "bedrock/us.anthropic.claude-haiku-5-5", show_body=True,
     guardrailConfig={"guardrailIdentifier": "gr-abc123", "guardrailVersion": "1"})
call("assume a role first (STS)", "bedrock/us.anthropic.claude-haiku-5-5",
     aws_role_name="arn:aws:iam::123456789012:role/litellm-bedrock", aws_session_name="litellm-proxy",
     aws_sts_endpoint=FAKE)
call("Bedrock API key (bearer token)", "bedrock/us.anthropic.claude-haiku-5-5", api_key="bedrock-api-key-fake")
```

```bash
cd examples/bedrock
uv run python fake_bedrock.py 4015 &
uv run python bedrock_inspect.py
```

```text
== model IDs and routes
regional inference profile           cost $0.00000462
    POST /model/us.anthropic.claude-haiku-5-5/converse              SigV4 AKIAFAKEEXAMPLE0001 us-west-2/bedrock
    body: {"messages": [{"role": "user", "content": [{"text": "Weather in Paris?"}]}], "inferenceConfig": {"maxTokens": 64}, "additionalModelResponseFieldPaths": ["/usage/output_tokens_details"], "system": [{"text": "Be brief."}]}
same model, Invoke route             cost $0.00000462
    POST /model/us.anthropic.claude-haiku-5-5/invoke                SigV4 AKIAFAKEEXAMPLE0001 us-west-2/bedrock
    body: {"messages": [{"role": "user", "content": [{"type": "text", "text": "Weather in Paris?"}]}], "max_tokens": 64, "system": [{"type": "text", "text": "Be brief."}], "anthropic_version": "bedrock-2023-05-31"}
global inference profile             cost $0.00000420
    POST /model/global.anthropic.claude-haiku-5-5/converse          SigV4 AKIAFAKEEXAMPLE0001 us-west-2/bedrock
Amazon Nova (Converse)               cost $0.00002046
    POST /model/us.amazon.nova-2-lite-v1:0/converse                 SigV4 AKIAFAKEEXAMPLE0001 us-west-2/bedrock
application inference profile ARN    cost $0.00000420
    POST /model/arn:aws:bedrock:us-west-2:123456789012:application-inference-profile/a1b2c3/converse SigV4 AKIAFAKEEXAMPLE0001 us-west-2/bedrock
== request features
tools                                cost $0.00000462
    POST /model/us.anthropic.claude-haiku-5-5/converse              SigV4 AKIAFAKEEXAMPLE0001 us-west-2/bedrock
    body: {"messages": [{"role": "user", "content": [{"text": "Weather in Paris?"}]}], "inferenceConfig": {"maxTokens": 64}, "additionalModelResponseFieldPaths": ["/usage/output_tokens_details"], "system": [{"text": "Be brief."}], "toolConfig": {"tools": [{"toolSpec": {"inputSchema": {"json": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}, "name": "get_weather", "description": "Weather for a city"}}]}}
Bedrock Guardrails on the call       cost $0.00000462
    POST /model/us.anthropic.claude-haiku-5-5/converse              SigV4 AKIAFAKEEXAMPLE0001 us-west-2/bedrock
    body: {"messages": [{"role": "user", "content": [{"guardContent": {"text": {"text": "Weather in Paris?"}}}]}], "inferenceConfig": {"maxTokens": 64}, "additionalModelResponseFieldPaths": ["/usage/output_tokens_details"], "system": [{"text": "Be brief."}], "guardrailConfig": {"guardrailIdentifier": "gr-abc123", "guardrailVersion": "1"}}
== credentials and region
aws_region_name=eu-west-1            cost $0.00000462
    POST /model/eu.anthropic.claude-haiku-5-5/converse              SigV4 AKIAFAKEEXAMPLE0001 eu-west-1/bedrock
assume a role first (STS)            cost $0.00000462
    POST /                                                          SigV4 AKIAFAKEEXAMPLE0001 us-west-2/sts
    POST /model/us.anthropic.claude-haiku-5-5/converse              SigV4 ASIAASSUMEDROLE0001 us-west-2/bedrock  +session token
Bedrock API key (bearer token)       cost $0.00000462
    POST /model/us.anthropic.claude-haiku-5-5/converse              Bearer
== errors
Bedrock answers 'throttled'          RateLimitError 429
    POST /model/us.anthropic.claude-haiku-5-5/converse              SigV4 AKIAFAKEEXAMPLE0001 us-west-2/bedrock
Bedrock answers 'denied'             PermissionDeniedError 403
    POST /model/us.anthropic.claude-haiku-5-5/converse              SigV4 AKIAFAKEEXAMPLE0001 us-west-2/bedrock
Bedrock answers 'invalid'            BadRequestError 400
    POST /model/us.anthropic.claude-haiku-5-5/converse              SigV4 AKIAFAKEEXAMPLE0001 us-west-2/bedrock
Bedrock answers 'unavailable'        ServiceUnavailableError 503
    POST /model/us.anthropic.claude-haiku-5-5/converse              SigV4 AKIAFAKEEXAMPLE0001 us-west-2/bedrock
```

The script sets fake static keys only so that requests to the fake endpoint can be signed. With a real account, rely on the credential chain instead. What the output shows:

- **One OpenAI-shaped call becomes a different body per route.** Converse takes the system prompt as a top-level `system` list, `max_tokens` as `inferenceConfig.maxTokens`, and tools as `toolConfig.tools[].toolSpec`. Since 1.110.0, when the call asks for thinking or the model thinks by default (LiteLLM's catalog marks Claude Haiku 5.5 so), the Converse body also carries `additionalModelResponseFieldPaths: ["/usage/output_tokens_details"]`, which asks Bedrock to return the breakdown of the output tokens, reasoning tokens included; 1.109.1 sent these bodies without it. Invoke for Claude takes Anthropic's Messages body with `anthropic_version`. Your code sends the same thing either way.
- **The region is part of the signature, not only the URL.** `aws_region_name=eu-west-1` changed the SigV4 credential scope to `eu-west-1/bedrock`. Against real Bedrock, the `eu.` profile worked from `eu-west-1` and failed from `us-west-2` with 400 `The provided model identifier is invalid`: an inference profile exists only in the regions of its geography.
- **Assuming a role costs one STS call, then it is cached.** The STS request was signed with the base identity; the Bedrock request with the temporary `ASIA...` key and a session token. In the proxy example below, three calls through an assumed role made one STS call.
- **Prices differ by ID form.** The `us.` profile cost $0.00000462 for the same tokens that cost $0.00000420 on `global.` and on the base ID.
- **An inference-profile ARN needs `base_model` to be priced.** With `base_model="anthropic.claude-haiku-5-5"` the call cost $0.0000042; without it, `response_cost` was `None`, so budgets and spend reports never see that traffic (exercise 12.3). On the wire, LiteLLM URL-encodes the ARN in the path (`arn%3Aaws%3Abedrock...`); the fake decodes it for display.
- **Bedrock Guardrails can run inside Bedrock.** `guardrailConfig` on the call (or in a deployment's `litellm_params`) is passed to Converse, and LiteLLM wraps the user text in `guardContent` so the guardrail evaluates it. This is the provider-side alternative to section 21's proxy-side guardrails.
- **Bedrock errors become OpenAI-style exceptions.** `ThrottlingException` gives `RateLimitError` (429) and `AccessDeniedException` gives `PermissionDeniedError` (403); the usual cause of the latter is a model not enabled in that account and region. `ServiceUnavailableException` gives 503. `ValidationException` gives `BadRequestError` (400), whether the request is malformed or the model ID doesn't exist in the signing region; read the message to tell them apart. Only 429 and 5xx are worth retrying in another region.

The same kinds of call against real Bedrock in us-west-2, through an SSO profile (`AWS_PROFILE`, no keys in the environment), with the prompt "Capital of France?" and a five-word limit:

```text
converse us. haiku                  2.8s OK  'Paris.' tools=[] tokens=24/6 cost=5.940000000000001e-06
invoke us. haiku                    1.2s OK  'Paris.' tools=[] tokens=24/6 cost=5.940000000000001e-06
global. haiku                       1.6s OK  'Paris.' tools=[] tokens=24/6 cost=5.4e-06
base id haiku (no profile)          0.4s ERR BadRequestError 400 litellm.BadRequestError: BedrockException - {"message":"Invocation of model ID anthropic.claude-haiku-5-5 with on-demand throughput isn’t supported. R
us. nova                            0.4s OK  'Paris, beautiful city.' tools=[] tokens=57/8 cost=4.081e-05
tools, converse                     1.0s OK  '' tools=['get_weather'] tokens=372/40 cost=6.292e-05
us. haiku signed us-east-1          3.4s OK  'Paris.' tools=[] tokens=24/6 cost=5.940000000000001e-06
eu. haiku signed us-west-2          0.1s ERR BadRequestError 400 litellm.BadRequestError: BedrockException - {"message":"The provided model identifier is invalid."}
eu. haiku signed eu-west-1          2.9s OK  'Paris.' tools=[] tokens=24/6 cost=5.940000000000001e-06
invalid model id                    0.4s ERR BadRequestError 400 litellm.BadRequestError: BedrockException - {"message":"The provided model identifier is invalid."}
temperature on haiku                0.0s ERR UnsupportedParamsError 400 litellm.UnsupportedParamsError: us.anthropic.claude-haiku-5-5 does not support temperature=0.2. Only temperature=1 is supported. To drop unsupported p
```

Converse and Invoke returned the same answer, token counts and cost. The `global.` profile was 10% cheaper for the same tokens. The `temperature` refusal happens inside LiteLLM, before any request is sent (0.0 s). The tool call used 372 input tokens for a one-line question: the tool definition and the tool-use instructions Bedrock adds count as input.

**Service tiers: priority, flex and default.** Bedrock serves an on-demand call at one of several tiers: **Standard**, the default; **Priority**, served ahead of other traffic at a higher price; and **Flex**, cheaper and allowed to take longer. A fourth, **Reserved**, is capacity your account has bought in advance. Not every model offers every tier, so check the model's card in the Bedrock documentation. You choose the tier per call with OpenAI's `service_tier` parameter, and LiteLLM turns it into Converse's `serviceTier` object. [`examples/bedrock/bedrock_service_tier.py`](examples/bedrock/bedrock_service_tier.py) sends each value to the fake Bedrock. Like Bedrock, the fake reports the tier it served only when the request named one; it can also be told to serve another tier (`GET /_serve?tier=default`) or to refuse the tier (`GET /_fail?region=us-west-2&error=tier`):

```python
NOVA = "bedrock/us.amazon.nova-2-lite-v1:0"  # priced per tier in LiteLLM's table

def call(label: str, model: str = NOVA, serve: str | None = None, fail: str | None = None, **kwargs: object) -> None:
    """One call against the fake Bedrock: the tier sent, the tier reported back, and the cost LiteLLM recorded."""
    ...
        r = litellm.completion(model=model, messages=MSGS, max_tokens=32,
                               aws_bedrock_runtime_endpoint=FAKE, num_retries=0, **kwargs)
        result = f"reply tier={str(getattr(r, 'service_tier', None)):9} cost ${r._hidden_params['response_cost']:.8f}"
    ...

call('service_tier="priority"', service_tier="priority")
call('service_tier="reserved"', service_tier="reserved")
call("asked priority, served default", service_tier="priority", serve="default")
call("Bedrock refuses the tier", service_tier="priority", fail="tier")
call("Claude Haiku, Invoke", "bedrock/invoke/us.anthropic.claude-haiku-5-5", service_tier="priority")

router = litellm.Router(model_list=[{"model_name": "nova-batchy", "litellm_params": {
    "model": NOVA, "aws_bedrock_runtime_endpoint": FAKE, "service_tier": "flex"}}])
```

```bash
cd examples/bedrock
uv run python fake_bedrock.py 4015 &
uv run python bedrock_service_tier.py
```

```text
Nova 2 Lite (us.) per 1M tokens, in/out:
    standard $0.3300/$2.7500
    flex $0.1650/$1.3750
    priority $0.5775/$4.8125
== the values LiteLLM forwards
no service_tier                    wire serviceTier=None                      reply tier=None      cost $0.00002046
service_tier="priority"            wire serviceTier={'type': 'priority'}      reply tier=priority  cost $0.00003581
service_tier="flex"                wire serviceTier={'type': 'flex'}          reply tier=flex      cost $0.00001023
service_tier="default"             wire serviceTier={'type': 'default'}       reply tier=default   cost $0.00002046
service_tier="auto"                wire serviceTier={'type': 'default'}       reply tier=default   cost $0.00002046
== the values LiteLLM drops without a word
service_tier="reserved"            wire serviceTier=None                      reply tier=None      cost $0.00002046
service_tier="standard"            wire serviceTier=None                      reply tier=None      cost $0.00002046
service_tier="Priority"            wire serviceTier=None                      reply tier=None      cost $0.00003581
service_tier="ultrafast"           wire serviceTier=None                      reply tier=None      cost $0.00002046
== Bedrock decides
asked priority, served default     wire serviceTier={'type': 'priority'}      reply tier=default   cost $0.00002046
Bedrock refuses the tier           wire serviceTier={'type': 'priority'}      BadRequestError 400
== other routes and models
Claude Haiku, Converse             wire serviceTier={'type': 'priority'}      reply tier=priority  cost $0.00000462
Claude Haiku, Invoke               nothing sent                               UnsupportedParamsError 400
Claude Haiku, Invoke, drop_params  wire serviceTier=None                      reply tier=None      cost $0.00000462
== a default tier per deployment (the proxy's model_list works the same way)
deployment default                 wire serviceTier={'type': 'flex'}          reply tier=flex      cost $0.00001023
caller overrides it                wire serviceTier={'type': 'priority'}      reply tier=priority  cost $0.00003581
```

Every call used 12 input and 6 output tokens, so the costs compare directly. What the output shows:

- **Four values reach Bedrock, all in lower case.** `priority`, `flex` and `default` are sent as `{"type": "<tier>"}`. `auto` is rewritten to `default`, because Converse has no `auto`. Without `service_tier`, no field is sent and Bedrock serves Standard.
- **Any other value is dropped without an error.** In 1.110.2, `AmazonConverseConfig._map_service_tier_param` forwards only those four exact strings. `reserved` never reaches Bedrock, so reserved capacity sits unused; `standard`, AWS's own name for the base tier, and `Priority` with a capital P are dropped as well, and the call runs on Standard. There is no warning and no 400, and `drop_params` changes nothing: Converse lists `service_tier` as supported, so LiteLLM accepts the value and then ignores it. LiteLLM's main branch has since changed this (PR #50516, merged on 14 November 2026: an unknown tier answers 400, `reserved` is forwarded, `standard` maps to `default`), but 1.110.2 doesn't include it.
- **The cost follows the tier Bedrock reports, otherwise the tier you asked for.** Nova 2 Lite's priority rate is 1.75 times the standard rate, and flex is half of it: $0.00003581 and $0.00001023 against $0.00002046. When the Converse response carries `serviceTier`, LiteLLM copies it to `response.service_tier` and prices the call at that tier, so asking for priority and being served default was billed at the standard rate. When the response carries no tier, the request decides. That makes `Priority` with a capital P the worst case: it was dropped on the wire and ran on Standard, but the cost lookup lower-cases the tier and billed it at the priority rate.
- **LiteLLM doesn't check which tiers a model offers.** It sends the tier, and a model that doesn't offer it answers `ValidationException`, which becomes `BadRequestError` (400). The Claude Haiku row shows the pricing side: the fake served priority, and LiteLLM billed the standard rate, because its price table has no tier prices for Claude on Bedrock. A tier with no price in the table is billed as Standard. Real Bedrock doesn't serve priority to Claude Haiku 5.5 at all (below).
- **The Invoke route doesn't take `service_tier`.** For Claude on `bedrock/invoke/...`, LiteLLM refused it with `UnsupportedParamsError` (400) before sending anything; with `drop_params=True` it was dropped and the call ran on Standard. Use the Converse route when you need a tier.
- **A deployment can set a default tier.** `service_tier: flex` in a deployment's `litellm_params` went out on every call to it, and a caller's own `service_tier` overrode it. I ran this through `Router`, which the proxy uses for its `model_list`. Behind the proxy that gives you, say, a `nova-flex` alias for batch jobs next to the standard one for interactive traffic, and clients that need a different tier pass `service_tier=` through the OpenAI SDK as usual.

The same values against real Bedrock in us-west-2, through an SSO profile, with [`bedrock_service_tier_live.py`](examples/bedrock/bedrock_service_tier_live.py). It uses section 1's `_wire.py` to show what was sent:

```bash
cd examples/bedrock
LIVE=1 uv run python bedrock_service_tier_live.py     # AWS credentials as in Setup; no fake
```

```text
amazon    None      sent=None                   reported=None       2.5s 'The capital of France is **Paris**.' tokens=53/11 cost=4.774e-05
amazon    default   sent={'type': 'default'}    reported=default    0.6s 'The capital of France is **Paris**.' tokens=53/11 cost=4.774e-05
amazon    priority  sent={'type': 'priority'}   reported=priority   0.5s 'The capital of France is **Paris**.' tokens=53/11 cost=8.3545e-05
amazon    flex      sent={'type': 'flex'}       reported=flex       0.5s 'The capital of France is **Paris**.' tokens=53/11 cost=2.387e-05
amazon    reserved  sent=None                   reported=None       0.6s 'The capital of France is **Paris**.' tokens=53/11 cost=4.774e-05
amazon    Priority  sent=None                   reported=None       0.5s 'The capital of France is **Paris**.' tokens=53/11 cost=8.3545e-05
anthropic None      sent=None                   reported=None       1.0s 'Paris' tokens=17/5 cost=4.62e-06
anthropic default   sent={'type': 'default'}    reported=default    0.8s 'Paris' tokens=17/5 cost=4.62e-06
anthropic priority  sent={'type': 'priority'}   reported=None       0.1s BadRequestError: {"message":"The provided service tier is not supported for this
anthropic flex      sent={'type': 'flex'}       reported=None       0.2s BadRequestError: {"message":"The provided service tier is not supported for this
anthropic reserved  sent=None                   reported=None       1.1s 'Paris' tokens=17/5 cost=4.62e-06
anthropic Priority  sent=None                   reported=None       0.8s 'Paris' tokens=17/5 cost=4.62e-06
```

- **Bedrock reports a tier only when the request named one,** as the fake assumes: no `service_tier`, and the dropped `reserved` and `Priority`, came back without one.
- **The billing gotcha is real.** `Priority` with a capital P was not sent, so Nova ran on Standard, yet LiteLLM billed $0.0000835 for it, the priority rate, instead of the $0.0000477 the standard call cost.
- **Not every model has every tier.** Nova 2 Lite served priority and flex. Claude Haiku 5.5 refused both with `The provided service tier is not supported for this model` (`BadRequestError`, 400) and accepted only `default`. Check the model's card in the Bedrock documentation before you rely on a tier, and send the tier in lower case.

**Bedrock behind the proxy.** In production, the proxy is where Bedrock's regions, accounts and quotas come together. [`examples/bedrock/bedrock_proxy.yaml`](examples/bedrock/bedrock_proxy.yaml):

```yaml
model_list:
  - model_name: claude                          # one alias, two regions: load-balanced, and failover
    litellm_params:
      model: bedrock/us.anthropic.claude-haiku-5-5
      aws_region_name: us-west-2
      aws_bedrock_runtime_endpoint: os.environ/BEDROCK_ENDPOINT
  - model_name: claude
    litellm_params:
      model: bedrock/us.anthropic.claude-haiku-5-5
      aws_region_name: us-east-1
      aws_bedrock_runtime_endpoint: os.environ/BEDROCK_ENDPOINT

  - model_name: nova                            # a different model family and region, as the last resort
    litellm_params:
      model: bedrock/us.amazon.nova-2-lite-v1:0
      aws_region_name: us-east-2
      aws_bedrock_runtime_endpoint: os.environ/BEDROCK_ENDPOINT

  - model_name: claude-team-b                   # billed to another AWS account through an assumed role
    litellm_params:
      model: bedrock/us.anthropic.claude-haiku-5-5
      aws_region_name: us-west-2
      aws_role_name: arn:aws:iam::210987654321:role/team-b-bedrock
      aws_session_name: litellm-team-b
      aws_sts_endpoint: os.environ/BEDROCK_ENDPOINT   # the fake also plays STS; leave out for real AWS
      aws_bedrock_runtime_endpoint: os.environ/BEDROCK_ENDPOINT

  - model_name: claude-guarded                  # Amazon Bedrock Guardrails applied by Bedrock itself
    litellm_params:
      model: bedrock/us.anthropic.claude-haiku-5-5
      aws_region_name: us-west-2
      guardrailConfig: {guardrailIdentifier: gr-abc123, guardrailVersion: "1"}
      aws_bedrock_runtime_endpoint: os.environ/BEDROCK_ENDPOINT

router_settings:
  routing_strategy: simple-shuffle
  num_retries: 1
  cooldown_time: 30                             # a 429 takes the deployment out for 30 s (no allowed_fails set)
  fallbacks: [{"claude": ["nova"]}]

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

[`bedrock_proxy_client.py`](examples/bedrock/bedrock_proxy_client.py) uses only the OpenAI SDK against the proxy, makes the fake throttle or fail regions (`GET /_fail?region=...`), and reads the fake's log to see where each request went:

```bash
cd examples/bedrock
uv run python fake_bedrock.py 4015 &
export LITELLM_MASTER_KEY=sk-master-demo BEDROCK_ENDPOINT=http://127.0.0.1:4015 AWS_REGION=us-west-2
export AWS_ACCESS_KEY_ID=AKIAFAKEEXAMPLE0001 AWS_SECRET_ACCESS_KEY=fake-secret   # fake: only signs requests to the fake
uv run litellm --config bedrock_proxy.yaml --port 4000
LITELLM_KEY=sk-master-demo uv run python bedrock_proxy_client.py      # in another shell
```

```text
1. 10 calls to 'claude', by region: {'us-west-2': 4, 'us-east-1': 6}
2. us-west-2 throttled; 6 calls succeeded: 6 | attempts by region: {'us-west-2': 1, 'us-east-1': 6}
3. both regions down; served by: ('nova', '1') | last Bedrock model: us.amazon.nova-2-lite-v1:0
4. claude-team-b x3: STS AssumeRole calls: 1 arn:aws:iam::210987654321:role/team-b-bedrock | Bedrock signed by: {'ASIAASSUMEDROLE0001'}
5. claude-guarded body carries: {'guardrailIdentifier': 'gr-abc123', 'guardrailVersion': '1'}
```

- **Spread one alias over several regions.** Each region has its own quota, so two deployments of the same inference profile in `us-west-2` and `us-east-1` double the throughput the proxy can draw on. Clients only see `claude`.
- **A throttled region is taken out after its first 429.** In step 2, us-west-2 was tried once, returned `ThrottlingException`, and went into cooldown; the retry and the next five calls went to us-east-1, and all six calls succeeded. My first config also set `allowed_fails: 1`, and the throttled region kept being tried on most calls: with `allowed_fails` set, LiteLLM uses its older rule and cools a deployment down only after *more than* that many failures within `cooldown_time` (30 seconds here). Without it, a 429 cools down immediately.
- **Fall back to another model family, in another region.** Step 3 failed both Claude regions and the request was answered by `nova` (`x-litellm-attempted-fallbacks: 1`). My first attempt put `nova` in us-west-2 too, and the fallback failed along with the region it was meant to cover: put the fallback where the primary isn't.
- **One proxy, several AWS accounts.** `claude-team-b` assumes a role in another account, so that team's usage lands on its own AWS bill and in its own CloudTrail. The proxy's own identity needs only `sts:AssumeRole` on that role, and the role needs `bedrock:InvokeModel` (plus `bedrock:InvokeModelWithResponseStream` for streaming) on the model and inference-profile ARNs.
- **For real calls, unset `BEDROCK_ENDPOINT`** and the fake keys (`unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`; `boto3` reads keys from the environment before `AWS_PROFILE`), and remove `aws_sts_endpoint`; the deployments then call the regional Bedrock endpoints. With fake keys, AWS answered `AuthenticationError ... The security token included in the request is invalid`. With an SSO profile (`AWS_PROFILE`) and no keys, a live version of this config (Claude in us-west-2 and us-east-1, Nova in us-east-2) answered every call, streamed, and fell back to Nova when the Claude deployment was an `eu.` profile signed for us-west-2. The proxy's response headers don't show which region served a request (`x-litellm-model-api-base` is empty for Bedrock), so the fake's log is the easier way to see the spread. Give the proxy a real identity as follows.

**Giving the proxy an AWS identity.** Choose by where the proxy runs:

| Where the proxy runs | Identity | What the config needs |
| --- | --- | --- |
| Your laptop | `aws sso login --profile <p>`, then `AWS_PROFILE=<p>` in the proxy's environment | Nothing |
| Docker on your laptop | Mount `~/.aws` read-only, pass `AWS_PROFILE` (exercise 13.3's hint) | Nothing |
| EKS | EKS Pod Identity or IRSA on the proxy's service account | Nothing: the default chain finds it |
| ECS / EC2 | Task role / instance profile | Nothing |
| A different AWS account per team | Any of the above, plus `aws_role_name` per deployment | `aws_role_name`, `aws_session_name` |
| Outside AWS (another cloud, CI) | OIDC federation: `aws_web_identity_token` + `aws_role_name` | Those two plus `aws_session_name` |

A minimal IAM policy for the proxy's role:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
    "Resource": [
      "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-5-5",
      "arn:aws:bedrock:*:123456789012:inference-profile/us.anthropic.claude-haiku-5-5"
    ]
  }]
}
```

A cross-region profile can run the request in any region of its geography, so the foundation-model resource uses a `*` region. Enable model access for each model in the Bedrock console, in every region the profile can route to, or calls fail with `AccessDeniedException` (403).

**Bedrock Mantle behind the proxy.** Amazon Bedrock Mantle is Bedrock's second inference endpoint, `bedrock-mantle.<region>.api.aws`, which speaks OpenAI's Chat Completions and Responses APIs (and Anthropic's Messages API for Claude). Its model catalogue differs from bedrock-runtime's and between regions. Section 1 covers the `bedrock_mantle/` provider, the request formats and the gotchas. In the proxy, a Mantle deployment is one more `model_list` entry. It takes the same AWS identity as the Bedrock deployments above, so nothing in the "Giving the proxy an AWS identity" table changes. [`examples/bedrock/mantle_proxy.yaml`](examples/bedrock/mantle_proxy.yaml):

```yaml
model_list:
  - model_name: open-weights                    # gpt-oss on Mantle, load-balanced over two regions
    litellm_params:
      model: bedrock_mantle/openai.gpt-oss-120b
      aws_region_name: us-west-2
  - model_name: open-weights
    litellm_params:
      model: bedrock_mantle/openai.gpt-oss-120b
      aws_region_name: us-east-1

  - model_name: gpt-5                           # LiteLLM calls it through the Responses API; only some regions serve it
    litellm_params:
      model: bedrock_mantle/openai.gpt-5.5
      aws_region_name: us-east-1

  - model_name: claude                          # one alias, two Bedrock endpoints
    litellm_params:
      model: bedrock_mantle/anthropic.claude-haiku-4-5
      aws_region_name: us-west-2
  - model_name: claude
    litellm_params:
      model: bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0
      aws_region_name: us-west-2

  - model_name: gpt-5-wrong-region              # gpt-5.5 isn't served in us-west-2: fails, then falls back
    litellm_params:
      model: bedrock_mantle/openai.gpt-5.5
      aws_region_name: us-west-2

router_settings:
  routing_strategy: simple-shuffle
  num_retries: 0
  fallbacks: [{"gpt-5-wrong-region": ["open-weights"]}]

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

[`mantle_proxy_client.py`](examples/bedrock/mantle_proxy_client.py) uses only the OpenAI SDK. It reads the deployment that answered from `x-litellm-model-name`, and calls the proxy's `/v1/responses` as well as `/v1/chat/completions`. There is no fake Mantle, so this runs against real AWS:

```bash
cd examples/bedrock
export AWS_PROFILE=<profile> AWS_REGION=us-west-2 LITELLM_MASTER_KEY=sk-master-demo
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY BEDROCK_ENDPOINT
uv run litellm --config mantle_proxy.yaml --port 4000
LITELLM_KEY=sk-master-demo uv run python mantle_proxy_client.py      # in another shell
```

```text
1. chat open-weights  -> 'Paris'  deployment=bedrock_mantle/openai.gpt-oss-120b api_base=https://bedrock-mantle.us-west-2.api.aws/v1 cost=3.149999999999999e-05
1. chat gpt-5         -> 'Paris'  deployment=bedrock_mantle/openai.gpt-5.5 api_base=https://bedrock-mantle.us-west-2.api.aws/openai/v1 cost=0.0006325
1. chat claude        -> 'Paris'  deployment=bedrock_mantle/anthropic.claude-haiku-4-5 api_base=https://bedrock-mantle.us-west-2.api.aws/v1 cost=3.4e-05
2. 8 calls to 'claude': 4 x bedrock_mantle/anthropic.claude-haiku-4-5 (cost 3.4e-05); 4 x bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0 (cost 3.74e-05)
3. gpt-5-wrong-region -> 'Paris.' deployment=bedrock_mantle/openai.gpt-oss-120b api_base=https://bedrock-mantle.us-west-2.api.aws/v1 fallbacks=1
4. responses open-weights  -> 'Paris' tokens=74/33
4. responses claude        -> 'Paris' tokens=14/4
5. stream open-weights -> 1 chunks with text: '1 2 3 4 5'
```

- **Clients don't see which endpoint is behind an alias.** `claude` was answered by Mantle four times and by bedrock-runtime four times, and the client code was the same. The cost header shows the difference: the `us.` profile on bedrock-runtime is priced 10% higher.
- **A model LiteLLM calls through the Responses API works on `/v1/chat/completions`.** `gpt-5` answered a plain chat completion. The proxy sent it to Mantle's Responses API and converted the reply, as the SDK does (section 1).
- **A model missing from a region is a fallback case.** gpt-5.5 isn't served in us-west-2, so `gpt-5-wrong-region` failed with `NotFoundError` and the request was answered by `open-weights` (`x-litellm-attempted-fallbacks: 1`). Check each region's catalogue (section 1) before you add a deployment.
- **The proxy's `/v1/responses` reaches Mantle too.** For gpt-oss it went to Mantle's own Responses API; for Claude, LiteLLM translated it into a Messages request.
- **`x-litellm-model-api-base` names the wrong region for Mantle.** It said us-west-2 for every Mantle deployment, including the gpt-5 deployment in us-east-1, which can only have been answered there. An SDK call with `aws_region_name="us-east-1"` went to `https://bedrock-mantle.us-east-1.api.aws/v1/chat/completions` (captured with section 1's `_wire.py`), while LiteLLM reported `https://bedrock-mantle.us-west-2.api.aws/v1` as its `api_base`, built from `AWS_REGION`. It also says `.../v1` for Claude, whose request goes to `/anthropic/v1/messages`. Use `x-litellm-model-name` and `x-litellm-model-id` to tell deployments apart, not the API base.
- **Streaming arrived as a single chunk.** gpt-oss on Mantle sent the whole five-number reply in one content chunk here. Don't rely on streaming for short replies to show text progressively.
- **Authentication works as for `bedrock/`.** With no key configured, each Mantle request is signed with the proxy's AWS identity. A deployment can instead set `api_key: os.environ/BEDROCK_MANTLE_API_KEY` to use a Bedrock API key; I had no key to try it. Section 1 explains why a stale key in the proxy's environment breaks every Mantle deployment.

**Amazon SageMaker endpoints** (`sagemaker/<endpoint-name>`) use the same AWS credential chain and `aws_region_name` as Bedrock. I didn't run them.

### Through a cloud platform: Microsoft Azure

Azure offers models in two ways, and LiteLLM has a provider prefix for each:

| | Azure OpenAI | Other Microsoft Foundry models |
| --- | --- | --- |
| Models | OpenAI's models (GPT-4o, GPT-4.1, o-series, embeddings) | Claude, Llama, Mistral, DeepSeek, Phi and others from the Foundry catalogue |
| LiteLLM prefix | `azure/<deployment name>` | `azure_ai/<model>` |
| Endpoint | `https://<resource>.openai.azure.com` | `https://<resource>.services.ai.azure.com` |
| You first | Create a **deployment** of a model in your resource and give it a name | Deploy the model in a Foundry project |

**The deployment name is not the model name.** In Azure OpenAI you deploy `gpt-4o` under a name you choose, such as `gpt4o-prod`, and requests address that name. LiteLLM therefore can't tell from `azure/gpt4o-prod` which model runs behind it, and can't price it. Tell it with `base_model` (in the SDK) or `model_info.base_model` (in the proxy config), as with Bedrock's application inference profiles.

**The identity.** LiteLLM takes the first of these that is set:

| Parameters | What reaches Azure | Use it for |
| --- | --- | --- |
| `api_key` (or `AZURE_API_KEY`) | `api-key: <key>` header (Bearer on the v1 API) | Quick tests. A key is a long-lived secret; rotate it in the portal |
| `azure_ad_token` (or `AZURE_AD_TOKEN`) | `Authorization: Bearer <token>` | A Microsoft Entra ID token you obtained yourself; it expires in about an hour |
| `tenant_id` + `client_id` + `client_secret` | A token from Entra ID for that app registration, refreshed by LiteLLM | A service principal. Still a secret to store and rotate |
| `azure_ad_token: oidc/...` + `tenant_id` + `client_id` | A federated token (from a file, an env var, GitHub Actions...) exchanged for an Entra ID token | **Workload identity federation**: AKS workload identity, or a proxy running on AWS or GCP. No Azure secret anywhere |
| `litellm_settings: {enable_azure_ad_token_refresh: true}` and nothing else | A token from `DefaultAzureCredential`: managed identity, AKS workload identity, `az login` | **The production default on Azure** (VMs, App Service, AKS) |

Give the identity the **Cognitive Services OpenAI User** role (Azure OpenAI) or **Azure AI User** (Foundry) on the resource. The token's scope is `https://cognitiveservices.azure.com/.default`; `azure_scope` changes it.

**The API version.** Azure OpenAI's classic API puts the deployment in the URL and needs an `api-version` query parameter (`api_version: "2024-10-21"`, or `AZURE_API_VERSION`). The newer **v1 API** (`api_version: v1`) drops the version and the deployment from the URL and takes the deployment name as `model` in the body, like OpenAI's own API.

**What LiteLLM sends.** [`examples/azure/fake_azure.py`](examples/azure/fake_azure.py) is a fake Azure OpenAI, Foundry and Entra ID token endpoint. The first path segment stands for the resource, so `http://127.0.0.1:4018/eastus` plays `https://<eastus resource>.openai.azure.com`. A deployment name containing `throttled`, `filtered`, `missing` or `unavailable` gets that Azure error. [`examples/azure/azure_inspect.py`](examples/azure/azure_inspect.py) calls it through the SDK:

```python
call("deployment, API key", "azure/gpt4o-prod", show_body=True,
     api_base=EASTUS, api_key="azure-key-1", api_version="2024-10-21")
call("same, with base_model for pricing", "azure/gpt4o-prod",
     api_base=EASTUS, api_key="azure-key-1", api_version="2024-10-21", base_model="azure/gpt-4o")
call("v1 API (api_version=v1)", "azure/gpt4o-prod",
     api_base=EASTUS, api_key="azure-key-1", api_version="v1", base_model="azure/gpt-4o")
call("Claude in Foundry", "azure_ai/claude-haiku-5-5", show_body=True, api_base=FOUNDRY, api_key="foundry-key")
call("Llama in Foundry", "azure_ai/Llama-4-Maverick-17B-128E-Instruct-FP8",
     api_base=f"{FOUNDRY}/models", api_key="foundry-key")
call("static Entra ID token", "azure/gpt4o-prod",
     api_base=EASTUS, api_version="2024-10-21", azure_ad_token="eyJ.entra-access-token.sig")
call("workload identity (OIDC), 3 calls", "azure/gpt4o-prod", repeat=3,
     api_base=EASTUS, api_version="2024-10-21", azure_ad_token="oidc/env/FEDERATED_TOKEN",
     tenant_id="tenant-1", client_id="client-1")
```

```bash
cd examples/azure
uv run python fake_azure.py 4018 &
uv run python azure_inspect.py
```

```text
== Azure OpenAI: deployments and API versions
deployment, API key                    cost None
    POST eastus/openai/deployments/gpt4o-prod/chat/completions?api-version=2024-10-21 api-key azure-key-1
    body: {"model": "gpt4o-prod", "messages": [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Weather in Paris?"}], "max_tokens": 64}
same, with base_model for pricing      cost $0.00009000
    POST eastus/openai/deployments/gpt4o-prod/chat/completions?api-version=2024-10-21 api-key azure-key-1
v1 API (api_version=v1)                cost $0.00009000
    POST eastus/openai/v1/chat/completions                                        Bearer azure-key-1
== Microsoft Foundry models
Claude in Foundry                      cost $0.00000420
    POST myfoundry/anthropic/v1/messages                                          api-key foundry-key
    body: {"model": "claude-haiku-5-5", "messages": [{"role": "user", "content": [{"type": "text", "text": "Weather in Paris?"}]}], "max_tokens": 64, "system": [{"type": "text", "text": "Be brief."}]}
Llama in Foundry                       cost $0.00000900
    POST myfoundry/models/chat/completions                                        Bearer foundry-key
== Entra ID instead of keys
static Entra ID token                  cost None
    POST eastus/openai/deployments/gpt4o-prod/chat/completions?api-version=2024-10-21 Bearer eyJ.entra-access-token.s
workload identity (OIDC), 3 calls      cost None
    POST entra/tenant-1/oauth2/v2.0/token                                         none
    POST eastus/openai/deployments/gpt4o-prod/chat/completions?api-version=2024-10-21 Bearer entra-token-1
    POST eastus/openai/deployments/gpt4o-prod/chat/completions?api-version=2024-10-21 Bearer entra-token-1
    POST eastus/openai/deployments/gpt4o-prod/chat/completions?api-version=2024-10-21 Bearer entra-token-1
== errors
deployment answers 'throttled'         RateLimitError 429
    POST eastus/openai/deployments/gpt4o-throttled/chat/completions?api-version=2024-10-21 api-key azure-key-1
deployment answers 'filtered'          ContentPolicyViolationError 400
    POST eastus/openai/deployments/gpt4o-filtered/chat/completions?api-version=2024-10-21 api-key azure-key-1
deployment answers 'missing'           NotFoundError 404
    POST eastus/openai/deployments/gpt4o-missing/chat/completions?api-version=2024-10-21 api-key azure-key-1
deployment answers 'unavailable'       ServiceUnavailableError 503
    POST eastus/openai/deployments/gpt4o-unavailable/chat/completions?api-version=2024-10-21 api-key azure-key-1
```

What the output shows:

- **Without `base_model`, an Azure deployment has no cost.** `response_cost` was `None`, so budgets and spend reports never see that traffic. With `base_model="azure/gpt-4o"` the same call cost $0.00009. The proxy has the same problem, and `model_info.base_model` fixes it there.
- **Two URL shapes.** The classic API puts the deployment in the path and needs `api-version`. The v1 API (`/openai/v1/chat/completions`) has no version parameter and sends the key as a Bearer token. The body is OpenAI's either way, because Azure OpenAI *is* OpenAI's API.
- **Foundry serves each model family in its own format.** Claude went to `/anthropic/v1/messages` with Anthropic's Messages body. Llama went to `/models/chat/completions`, the Foundry inference API, with an OpenAI body. `azure_ai/` picks the route from the model name, and both were priced.
- **A federated token is exchanged once, then cached.** Three calls made one request to Entra ID's token endpoint (`grant_type=client_credentials` with a `client_assertion` of type `jwt-bearer`, scope `cognitiveservices`). All three calls carried the same Entra ID token. This is the Azure equivalent of Bedrock's STS `AssumeRole`.
- **Azure's content filter has its own exception.** A `content_filter` refusal became `ContentPolicyViolationError` (400), not a plain `BadRequestError`. The proxy can route these to another model with `content_policy_fallbacks` (below). A deployment that doesn't exist gives `NotFoundError` (404). Check the deployment name, which is not the model name.

**Azure behind the proxy.** [`examples/azure/azure_proxy.yaml`](examples/azure/azure_proxy.yaml):

```yaml
model_list:
  - model_name: gpt                             # one alias, two Azure regions: load-balanced, and failover
    litellm_params:
      model: azure/gpt4o-prod                   # azure/<your deployment name>, not the model name
      api_base: os.environ/AZURE_EASTUS_BASE    # https://<eastus resource>.openai.azure.com
      api_key: os.environ/AZURE_EASTUS_KEY
      api_version: "2024-10-21"
    model_info:
      base_model: azure/gpt-4o                  # what the deployment runs, so LiteLLM can price it
  - model_name: gpt
    litellm_params:
      model: azure/gpt4o-prod
      api_base: os.environ/AZURE_SWEDEN_BASE    # https://<swedencentral resource>.openai.azure.com
      api_key: os.environ/AZURE_SWEDEN_KEY
      api_version: "2024-10-21"
    model_info:
      base_model: azure/gpt-4o

  - model_name: claude                          # Claude deployed in Microsoft Foundry
    litellm_params:
      model: azure_ai/claude-haiku-5-5
      api_base: os.environ/AZURE_FOUNDRY_BASE   # https://<foundry resource>.services.ai.azure.com
      api_key: os.environ/AZURE_FOUNDRY_KEY

  - model_name: gpt-entra                       # no key: a federated token exchanged for an Entra ID token
    litellm_params:
      model: azure/gpt4o-prod
      api_base: os.environ/AZURE_EASTUS_BASE
      api_version: "2024-10-21"
      azure_ad_token: oidc/env/AZURE_FEDERATED_TOKEN
      tenant_id: os.environ/AZURE_TENANT_ID
      client_id: os.environ/AZURE_CLIENT_ID
    model_info:
      base_model: azure/gpt-4o

router_settings:
  routing_strategy: simple-shuffle
  num_retries: 1
  cooldown_time: 30
  content_policy_fallbacks: [{"gpt": ["claude"]}]   # Azure's content filter refused: try another model family

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

[`azure_proxy_client.py`](examples/azure/azure_proxy_client.py) uses only the OpenAI SDK. It stages incidents on the fake (`GET /_fail?resource=eastus&error=throttled`) and reads the fake's log to see where each request went:

```bash
cd examples/azure            # fake_azure.py still running on 4018
export LITELLM_MASTER_KEY=sk-master-demo LITELLM_LOCAL_MODEL_COST_MAP=True F=http://127.0.0.1:4018
export AZURE_EASTUS_BASE=$F/eastus AZURE_SWEDEN_BASE=$F/swedencentral AZURE_FOUNDRY_BASE=$F/myfoundry
export AZURE_EASTUS_KEY=fake-1 AZURE_SWEDEN_KEY=fake-2 AZURE_FOUNDRY_KEY=fake-3
export AZURE_AUTHORITY_HOST=$F AZURE_TENANT_ID=tenant-1 AZURE_CLIENT_ID=client-1 AZURE_FEDERATED_TOKEN=eyJ.fake.sig
uv run litellm --config azure_proxy.yaml --port 4000
LITELLM_KEY=sk-master-demo uv run python azure_proxy_client.py      # in another shell
```

```text
1. 10 calls to 'gpt', by resource: {'swedencentral': 7, 'eastus': 3} | cost header: {'9.000000000000002e-05'}
2. eastus throttled; 6 calls succeeded: 6 | attempts by resource: {'eastus': 1, 'swedencentral': 6}
3. content filter in both regions; served by: claude | reply: 'reply from claude-haiku-5-5' | last path: /anthropic/v1/messages
4. gpt-entra x3: Entra ID token requests: 1 | chat auth: {'Bearer entra-token-2'}
```

- **One alias, two regions, priced.** Each Azure OpenAI resource has its own quota (tokens per minute per deployment), so a second resource in another region doubles what the proxy can draw on. `model_info.base_model` put a cost on every call.
- **A throttled region is taken out after its first 429**, exactly as with Bedrock: eastus was tried once, then six calls went to swedencentral.
- **A content-filter refusal can go to another model family.** The filter is configured per Azure resource. When both GPT deployments refused, `content_policy_fallbacks` sent the request to Claude in Foundry. Plain `fallbacks` catch filter refusals too when no `content_policy_fallbacks` is set: an SDK `Router` with only `fallbacks: [{"gpt": ["claude"]}]` also answered from Claude. So a general fallback list quietly routes around Azure's filter. Decide whether you want that; a filter refusal is often the answer you want to keep. To keep it, set `content_policy_fallbacks: [{"gpt": []}]`, which stopped the Router falling back; an empty `content_policy_fallbacks: []` did not.
- **The proxy needs no Azure secret with workload identity.** `gpt-entra` made one token exchange for three calls (the token is `-2` because the inspect script above got `-1` from the same fake). On AKS, enable workload identity on the proxy's service account. Azure then writes the federated token to a file named by `AZURE_FEDERATED_TOKEN_FILE`, which `DefaultAzureCredential` reads when `enable_azure_ad_token_refresh: true` is set.
- **For real calls,** set the `AZURE_*_BASE` variables to your resources' endpoints, use real keys or an identity, and unset `AZURE_AUTHORITY_HOST` so that tokens come from `login.microsoftonline.com`.

### Through a cloud platform: Google Cloud Vertex AI

Vertex AI serves Google's Gemini models and partner models such as Claude, Llama and Mistral from your Google Cloud project. One prefix covers them all: `vertex_ai/<model>`. LiteLLM picks the request format from the model name:

| Model | Vertex method | Body |
| --- | --- | --- |
| `vertex_ai/gemini-2.5-flash` | `.../publishers/google/models/gemini-2.5-flash:generateContent` | Gemini's `contents`/`parts`, `system_instruction`, `generationConfig` |
| `vertex_ai/claude-haiku-5-5` | `.../publishers/anthropic/models/claude-haiku-5-5:rawPredict` | Anthropic's Messages body plus `anthropic_version: vertex-2023-10-16` |
| `vertex_ai/meta/llama-...`, `vertex_ai/mistral-...` | The partner's own route | OpenAI-style or the partner's format |

Two settings place the call: `vertex_project` (or `VERTEXAI_PROJECT`) and `vertex_location` (or `VERTEXAI_LOCATION`, default `us-central1`). Location `global` lets Google choose the region and uses the host `aiplatform.googleapis.com`; any other location uses `<location>-aiplatform.googleapis.com`. In LiteLLM 1.110.2's price table, Claude in a regional location costs 10% more than in `global`, as with Bedrock's `us.` and `global.` profiles. `gemini/<model>` is a different provider: Google AI Studio, with an API key (`GEMINI_API_KEY`) and no project.

**The identity.** Vertex AI takes a short-lived Google OAuth2 access token as `Authorization: Bearer`. LiteLLM mints it with `google-auth` from the first of these it finds:

| Source | Use it for |
| --- | --- |
| `vertex_credentials` (or `VERTEXAI_CREDENTIALS`): a service-account key file's path or JSON | A service account outside Google Cloud. The key is a long-lived secret; prefer federation |
| `vertex_credentials` pointing at a **workload identity federation** config (`"type": "external_account"`) | A proxy on AWS, Azure or anywhere with an OIDC token: the token is exchanged at Google's Security Token Service. No Google key exists |
| Nothing: **Application Default Credentials** | `GOOGLE_APPLICATION_CREDENTIALS`, `gcloud auth application-default login` on a laptop, or the workload's service account on GKE (Workload Identity) and Cloud Run. **The production default on Google Cloud** |

Give the identity the **Vertex AI User** role (`roles/aiplatform.user`) on the project, and enable each partner model in Model Garden first.

**What LiteLLM sends.** [`examples/vertex/fake_vertex.py`](examples/vertex/fake_vertex.py) is a fake Vertex AI plus Google's two token endpoints: the OAuth2 endpoint where a service account trades a signed JWT for a token, and the STS endpoint used by federation. [`make_fake_credentials.py`](examples/vertex/make_fake_credentials.py) writes a service-account key file (with a freshly generated RSA key) and a federation config. Their `token_uri` and `token_url` point at the fake, so the real `google-auth` code runs offline. `api_base` sends the model calls to the fake. [`examples/vertex/vertex_inspect.py`](examples/vertex/vertex_inspect.py):

```python
kwargs = {"vertex_project": "acme-ml-prod", "vertex_location": "us-central1", "vertex_credentials": SA,
          "api_base": FAKE, **kwargs}
...
call("Gemini", "vertex_ai/gemini-2.5-flash", show_body=True)
call("Claude on Vertex", "vertex_ai/claude-haiku-5-5", show_body=True)
call("Claude, location global", "vertex_ai/claude-haiku-5-5", vertex_location="global")
call("Gemini with tools", "vertex_ai/gemini-2.5-flash", show_body=True, tools=TOOLS)
call("service-account key, 3 calls", "vertex_ai/gemini-2.5-flash", repeat=3)
call("workload identity federation, 3 calls", "vertex_ai/gemini-2.5-flash", repeat=3, vertex_credentials=WIF)
```

```bash
cd examples/vertex
uv run python make_fake_credentials.py          # writes .creds/ (git-ignored)
uv run python fake_vertex.py 4019 &
uv run python vertex_inspect.py
```

```text
== model families and locations
Gemini                               cost $0.00001860
    POST /token                                                                 {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "iss": "litellm-proxy@acme-ml-prod.iam.gserviceaccount.com", "scope": "https://www.googleapis.com/auth/cloud-platform"}
    POST .../locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent Bearer ya29.sa-token-1
    body: {"contents": [{"role": "user", "parts": [{"text": "Weather in Paris?"}]}], "system_instruction": {"parts": [{"text": "Be brief."}]}, "generationConfig": {"max_output_tokens": 64}}
Claude on Vertex                     cost $0.00000462
    POST /token                                                                 {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "iss": "litellm-proxy@acme-ml-prod.iam.gserviceaccount.com", "scope": "https://www.googleapis.com/auth/cloud-platform"}
    POST .../locations/us-central1/publishers/anthropic/models/claude-haiku-5-5:rawPredict Bearer ya29.sa-token-2
    body: {"messages": [{"role": "user", "content": [{"type": "text", "text": "Weather in Paris?"}]}], "max_tokens": 64, "anthropic_version": "vertex-2023-10-16", "system": [{"type": "text", "text": "Be brief."}]}
Claude, location global              cost $0.00000420
    POST .../locations/global/publishers/anthropic/models/claude-haiku-5-5:rawPredict Bearer ya29.sa-token-2
Gemini, location europe-west4        cost $0.00001860
    POST .../locations/europe-west4/publishers/google/models/gemini-2.5-flash:generateContent Bearer ya29.sa-token-1
== request features
Gemini with tools                    cost $0.00001860
    POST .../locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent Bearer ya29.sa-token-1
    body: {"contents": [{"role": "user", "parts": [{"text": "Weather in Paris?"}]}], "system_instruction": {"parts": [{"text": "Be brief."}]}, "tools": [{"function_declarations": [{"name": "get_weather", "description": "Weather for a city", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}]}], "generationConfig": {"max_output_tokens": 64}}
== Google credentials
service-account key, 3 calls         cost $0.00001860
    POST .../locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent Bearer ya29.sa-token-1
    POST .../locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent Bearer ya29.sa-token-1
    POST .../locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent Bearer ya29.sa-token-1
workload identity federation, 3 calls cost $0.00001860
    POST /v1/token                                                              {"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange", "audience": "//iam.googleapis.com/projects/123456789/locations/global/workloadIdentityPools/litellm/providers/eks", "subject_token_type": "urn:ietf:params:oauth:token-type:jwt"}
    POST .../locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent Bearer ya29.federated-token-3
    POST .../locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent Bearer ya29.federated-token-3
    POST .../locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent Bearer ya29.federated-token-3
== errors
Vertex answers 'exhausted'           RateLimitError 429
    POST .../locations/us-central1/publishers/google/models/gemini-2.5-flash-exhausted:generateContent Bearer ya29.sa-token-1
Vertex answers 'denied'              BadRequestError 403
    POST .../locations/us-central1/publishers/google/models/gemini-2.5-flash-denied:generateContent Bearer ya29.sa-token-1
Vertex answers 'missing'             NotFoundError 404
    POST .../locations/us-central1/publishers/google/models/gemini-2.5-flash-missing:generateContent Bearer ya29.sa-token-1
Vertex answers 'unavailable'         ServiceUnavailableError 503
    POST .../locations/us-central1/publishers/google/models/gemini-2.5-flash-unavailable:generateContent Bearer ya29.sa-token-1
```

- **One call, two very different bodies.** Gemini got `contents` with `parts`, the system prompt as `system_instruction`, `max_tokens` as `generationConfig.max_output_tokens`, and tools as `function_declarations`. Claude got Anthropic's Messages body with Vertex's `anthropic_version`; the model ID moved from the body into the URL.
- **The location is in the URL, not in the signature.** Unlike Bedrock's SigV4, a Google token is not tied to a region, so one token served `us-central1`, `europe-west4` and `global`. Moving a deployment to another region is a one-line change.
- **A token is minted once and cached.** The service account signed a JWT and traded it at `/token` once. Three later calls reused `ya29.sa-token-1`. Claude on Vertex minted its own token (`-2`), because its handler caches separately from Gemini's. Federation exchanged the other cloud's OIDC token at STS once for three calls.
- **A Vertex 403 is not a `PermissionDeniedError`.** `PERMISSION_DENIED` came back as `BadRequestError` with `status_code` 403, while Bedrock's `AccessDeniedException` gives `PermissionDeniedError`. Code that catches by exception class must check `status_code` for Vertex. The usual cause is a missing role or a partner model not enabled in Model Garden. `RESOURCE_EXHAUSTED` became `RateLimitError` (429), the error worth retrying in another region.

**Vertex AI behind the proxy.** [`examples/vertex/vertex_proxy.yaml`](examples/vertex/vertex_proxy.yaml) spreads Gemini over two regions, falls back to `global`, and calls Claude with federated credentials:

```yaml
model_list:
  - model_name: gemini                          # one alias, two Vertex regions: load-balanced, and failover
    litellm_params:
      model: vertex_ai/gemini-2.5-flash
      vertex_project: os.environ/VERTEXAI_PROJECT
      vertex_location: us-central1
      vertex_credentials: os.environ/VERTEX_SA_FILE   # leave out to use Application Default Credentials
      api_base: os.environ/VERTEX_API_BASE            # the fake; leave out for real Vertex AI
  - model_name: gemini
    litellm_params:
      model: vertex_ai/gemini-2.5-flash
      vertex_project: os.environ/VERTEXAI_PROJECT
      vertex_location: us-east4
      vertex_credentials: os.environ/VERTEX_SA_FILE
      api_base: os.environ/VERTEX_API_BASE

  - model_name: gemini-global                   # Google picks the region: the fallback when both are exhausted
    litellm_params:
      model: vertex_ai/gemini-2.5-flash
      vertex_project: os.environ/VERTEXAI_PROJECT
      vertex_location: global
      vertex_credentials: os.environ/VERTEX_SA_FILE
      api_base: os.environ/VERTEX_API_BASE

  - model_name: claude                          # Claude on Vertex, with no Google key: workload identity federation
    litellm_params:
      model: vertex_ai/claude-haiku-5-5
      vertex_project: os.environ/VERTEXAI_PROJECT
      vertex_location: global
      vertex_credentials: os.environ/VERTEX_WIF_FILE
      api_base: os.environ/VERTEX_API_BASE

router_settings:
  routing_strategy: simple-shuffle
  num_retries: 1
  cooldown_time: 30
  fallbacks: [{"gemini": ["gemini-global"]}]

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

```bash
cd examples/vertex            # fake_vertex.py still running on 4019
export LITELLM_MASTER_KEY=sk-master-demo LITELLM_LOCAL_MODEL_COST_MAP=True VERTEXAI_PROJECT=acme-ml-prod
export VERTEX_API_BASE=http://127.0.0.1:4019 VERTEX_SA_FILE=$PWD/.creds/service-account.json \
       VERTEX_WIF_FILE=$PWD/.creds/workload-identity.json
uv run litellm --config vertex_proxy.yaml --port 4000
LITELLM_KEY=sk-master-demo uv run python vertex_proxy_client.py     # in another shell
```

```text
1. 10 calls to 'gemini', by location: {'us-east4': 6, 'us-central1': 4}
2. us-central1 exhausted; 6 calls succeeded: 6 | attempts by location: {'us-east4': 6, 'us-central1': 1}
3. both regions exhausted; served by: gemini-global | reply: 'reply from gemini-2.5-flash in global'
4. claude x3: token exchanges: ['/v1/token'] | publisher: {'anthropic'} | auth: {'Bearer ya29.federated-token-5'}
```

- **Regional quotas add up.** Vertex quotas are per project, region and model. Two regional deployments of the same model spread the load, and a region that answers `RESOURCE_EXHAUSTED` is taken out after its first 429.
- **`global` is a natural last resort.** It draws on capacity in any region. Keep it as the fallback, not the primary, if your data must stay in one geography: a request served through `global` can run anywhere.
- **No Google key on the proxy.** `claude` used the federation config; the proxy's own OIDC token (on EKS, the service account's projected token) was exchanged for a Google token once for three calls. On GKE or Cloud Run, leave `vertex_credentials` out and the workload's service account is used.
- **For real calls,** remove `api_base` and point `vertex_credentials` at your real key file or federation config, or leave it out on Google Cloud.

### Directly to a model provider: OpenAI, Anthropic, Ollama and vLLM

Calling a provider's own API is the simplest setup: a prefix, a key, and optionally `api_base`. The same holds for servers you run yourself, which mostly speak OpenAI's API.

| Provider | Prefix | Credential | Default endpoint, and what to set |
| --- | --- | --- | --- |
| OpenAI | `openai/<model>` | `OPENAI_API_KEY`, sent as `Authorization: Bearer` | `https://api.openai.com/v1`; `OPENAI_ORGANIZATION` for an org |
| Anthropic | `anthropic/<model>` | `ANTHROPIC_API_KEY`, sent as `x-api-key`, with `anthropic-version` | `https://api.anthropic.com` |
| Google AI Studio | `gemini/<model>` | `GEMINI_API_KEY`, sent as `x-goog-api-key` | `generativelanguage.googleapis.com` |
| Mistral, Groq, DeepSeek, xAI, Together, Fireworks... | `mistral/`, `groq/`, `deepseek/`, `xai/`, `together_ai/`, `fireworks_ai/` | `<PROVIDER>_API_KEY` in most cases; check the provider's page, because the name does not always follow the prefix (`together_ai/` reads `TOGETHER_API_KEY` or `TOGETHERAI_API_KEY`) | Each provider's API |
| **Ollama** (local) | `ollama_chat/<model>` (chat API) or `ollama/<model>` (generate API) | None | `api_base: http://localhost:11434` |
| **vLLM** (self-hosted) | `hosted_vllm/<model>` | `api_key` if you started vLLM with `--api-key` | `api_base: http://<host>:8000/v1` |
| Any OpenAI-compatible server (LM Studio, llama.cpp `llama-server`, SGLang, TGI, LocalAI) | `openai/<model>` | `api_key` (anything, if the server ignores it) | `api_base: http://<host>:<port>/v1` |

**What LiteLLM sends.** [`examples/providers/providers_inspect.py`](examples/providers/providers_inspect.py) sends the hosted and vLLM calls to [`examples/_fake_upstream.py`](examples/_fake_upstream.py), which records them. It sends the Ollama calls to a real Ollama in Docker, running Qwen 2.5 0.5B, a 400 MB model that runs on a laptop CPU:

```bash
docker run -d --name litellm-tutorial-ollama -p 127.0.0.1:11434:11434 \
  -v litellm-tutorial-ollama:/root/.ollama ollama/ollama:0.12.6
docker exec litellm-tutorial-ollama ollama pull qwen2.5:0.5b      # about 400 MB
cd examples
uv run python _fake_upstream.py 4011 &
uv run python providers/providers_inspect.py
```

```python
call("OpenAI", "openai/gpt-4o-mini", show_body=True, api_base=f"{FAKE}/v1", api_key="sk-openai-fake")
call("Anthropic", "anthropic/claude-haiku-5-5", show_body=True, api_base=FAKE, api_key="sk-ant-fake")
call("vLLM (hosted_vllm/)", "hosted_vllm/Qwen/Qwen2.5-7B-Instruct", api_base=f"{FAKE}/v1")
call("any OpenAI-compatible (openai/)", "openai/my-local-model", api_base=f"{FAKE}/v1", api_key="none")
call("ollama_chat/ (POST /api/chat)", "ollama_chat/qwen2.5:0.5b", api_base=OLLAMA)
call("ollama/ (POST /api/generate)", "ollama/qwen2.5:0.5b", api_base=OLLAMA)
call("ollama_chat/ with tools", "ollama_chat/qwen2.5:0.5b", api_base=OLLAMA, tools=TOOLS, messages=[...])
```

```text
== hosted providers (fake upstream on :4011)
OpenAI                          0.3s 'fake OpenAI reply'                      tokens=10/3 cost=3.2999999999999997e-06
    POST /v1/chat/completions     {'authorization': 'Bearer sk-openai-fak...'}
    body: {"model":"gpt-4o-mini","messages":[{"role":"system","content":"Be brief."},{"role":"user","content":"Name the capital of France."}],"max_tokens":64}
Anthropic                       0.3s 'fake Anthropic reply'                   tokens=10/3 cost=2.4999999999999998e-06
    POST /v1/messages             {'anthropic-version': '2023-06-01', 'x-api-key': 'sk-ant-fake'}
    body: {"model": "claude-haiku-5-5", "messages": [{"role": "user", "content": [{"type": "text", "text": "Name the capital of France."}]}], "max_tokens": 64, "system": [{"type": "text", "text": "Be brief."}]}
== self-hosted, OpenAI-compatible servers (fake upstream on :4011)
vLLM (hosted_vllm/)             0.0s 'fake OpenAI reply'                      tokens=10/3 cost=None
    POST /v1/chat/completions     {'authorization': 'Bearer fake-api-key'}
any OpenAI-compatible (openai/)  0.0s 'fake OpenAI reply'                      tokens=10/3 cost=None
    POST /v1/chat/completions     {'authorization': 'Bearer none'}
== Ollama, a real local server (qwen2.5:0.5b on CPU)
ollama_chat/ (POST /api/chat)   2.3s 'Paris'                                  tokens=22/2 cost=0.0
ollama/ (POST /api/generate)    0.7s 'Paris.'                                 tokens=44/3 cost=0.0
ollama_chat/ with tools         1.8s "tool_calls=['get_weather']"             tokens=159/20 cost=0.0
ollama_chat/ streaming         10 chunks -> '1 2 3 4 5'
model info: {"max_input_tokens": 32768, "input_cost_per_token": 0.0, "supports_function_calling": true}
```

- **OpenAI passes through; Anthropic is translated.** The OpenAI body is your request unchanged. For Anthropic, the system prompt moved to a top-level `system` list, content became typed blocks, and the key went in `x-api-key` with an `anthropic-version` header.
- **Self-hosted models have no price.** vLLM and the generic `openai/` model had `cost=None`, because LiteLLM's price table doesn't know a model you serve. Ollama models are priced at `0.0`, and the proxy sends no cost header for them. Either way budgets see nothing. Set `input_cost_per_token` and `output_cost_per_token` on the deployment to your own figure, such as GPU hours divided by tokens served (below).
- **`hosted_vllm/` sends a placeholder key.** With no `api_key`, LiteLLM sent `Bearer fake-api-key`. vLLM accepts any key unless it was started with `--api-key`, in which case set the real one.
- **Prefer `ollama_chat/` to `ollama/`.** `ollama_chat/` uses Ollama's chat API, which keeps the roles and supports tools: the 0.5B model returned a `get_weather` tool call. `ollama/` uses the older generate API, which flattens the conversation into one prompt; the same question cost 44 prompt tokens instead of 22.
- **Ollama reports what the model can do.** `get_model_info` asked the running server (`/api/show`): a 32k context and function calling. The proxy uses this for `/model/info` and for context-window checks.
- The first Ollama call took 2.3 s because Ollama loaded the model into memory; later calls took under a second on CPU.

**Providers and local models behind the proxy.** [`examples/providers/providers_proxy.yaml`](examples/providers/providers_proxy.yaml) puts hosted and self-hosted models behind one endpoint:

```yaml
model_list:
  - model_name: claude                          # Anthropic's own API
    litellm_params:
      model: anthropic/claude-haiku-5-5
      api_key: os.environ/ANTHROPIC_API_KEY
      api_base: os.environ/FAKE_UPSTREAM        # the fake; leave out for api.anthropic.com
  - model_name: gpt                             # OpenAI's own API
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY
      api_base: os.environ/FAKE_UPSTREAM_V1     # the fake; leave out for api.openai.com

  - model_name: local                           # Ollama on this machine (or a GPU box on your network)
    litellm_params:
      model: ollama_chat/qwen2.5:0.5b
      api_base: os.environ/OLLAMA_API_BASE      # http://localhost:11434
  - model_name: local-gpu                       # a vLLM server; this one points at a closed port, to show failover
    litellm_params:
      model: hosted_vllm/Qwen/Qwen2.5-7B-Instruct
      api_base: http://127.0.0.1:9/v1
  - model_name: qwen-vllm                       # a vLLM server with a price, so budgets see its traffic
    litellm_params:
      model: hosted_vllm/Qwen/Qwen2.5-7B-Instruct
      api_base: os.environ/FAKE_UPSTREAM_V1     # the fake stands in for http://<vllm host>:8000/v1
      input_cost_per_token: 0.0000002           # your own figure: GPU hours / tokens served
      output_cost_per_token: 0.0000008

router_settings:
  num_retries: 0
  fallbacks: [{"local-gpu": ["local"]}, {"claude": ["gpt"]}]

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

```bash
cd examples/providers         # Ollama and _fake_upstream.py still running
export LITELLM_MASTER_KEY=sk-master-demo LITELLM_LOCAL_MODEL_COST_MAP=True
export ANTHROPIC_API_KEY=sk-ant-fake OPENAI_API_KEY=sk-openai-fake OLLAMA_API_BASE=http://localhost:11434
export FAKE_UPSTREAM=http://127.0.0.1:4011 FAKE_UPSTREAM_V1=http://127.0.0.1:4011/v1
uv run litellm --config providers_proxy.yaml --port 4000
LITELLM_KEY=sk-master-demo uv run python providers_proxy_client.py   # in another shell
```

```text
models: ['claude', 'gpt', 'local', 'local-gpu', 'qwen-vllm']
claude     -> 'fake Anthropic reply'   served_by=claude     cost=0.0000025 fallbacks=0
gpt        -> 'fake OpenAI reply'      served_by=gpt        cost=0.0000033 fallbacks=0
local      -> 'Paris.'                 served_by=local      cost=no header fallbacks=0
qwen-vllm  -> 'fake OpenAI reply'      served_by=qwen-vllm  cost=0.0000044 fallbacks=0
local-gpu  -> 'Paris'                  served_by=local      cost=no header fallbacks=1
```

- **Hosted and local models share one endpoint, one key scheme and one spend log.** Apps can't tell `claude` from `local`. That makes it easy to move a workload to a model you host when the hosted bill grows, or the other way when quality matters more.
- **A down GPU server falls back to another server.** `local-gpu` pointed at a closed port; the request was answered by the CPU Ollama (`fallbacks=1`). In practice the fallback is often a hosted model, as in exercise 12.9.
- **An unpriced call gets no cost header.** The Ollama calls cost `0.0` only because LiteLLM has no price for them, and since 1.110.0 the proxy then leaves out `x-litellm-response-cost` instead of sending `0.0` (1.109.1 sent it). A client that reads the header must handle it missing; give the deployment prices and the header comes back.
- **A price makes self-hosted traffic count.** `qwen-vllm` cost $0.0000044 for 10 input and 3 output tokens at the configured rates, so virtual-key budgets and spend reports include it.
- **When the proxy runs in Docker,** `localhost` is the container itself. Put Ollama and the proxy on one Docker network and use the container name: with `docker network create litellm-local`, `docker network connect litellm-local litellm-tutorial-ollama` and the proxy started with `--network litellm-local`, `api_base: http://litellm-tutorial-ollama:11434` answered from the official LiteLLM image. Docker Desktop also offers `http://host.docker.internal:11434`.
- **vLLM needs a GPU for real models,** so I ran this subsection's vLLM deployments against the fake only. To serve one: `docker run --gpus all -p 8000:8000 vllm/vllm-openai --model Qwen/Qwen2.5-7B-Instruct`, then set `api_base: http://<host>:8000/v1`. The [vLLM docs](https://docs.vllm.ai/) cover serving in depth.
- When you're done: `docker rm -f litellm-tutorial-ollama` (add `docker volume rm litellm-tutorial-ollama` to delete the downloaded model).

**Which way to reach a model.** The same model is often available several ways. Claude Haiku 5.5, for example, was reachable in this section as `anthropic/`, `bedrock/`, `azure_ai/` and `vertex_ai/`:

| If you... | Use |
| --- | --- |
| Already run on one cloud, and want its billing, IAM and network controls | That cloud's platform: `bedrock/`, `azure/` and `azure_ai/`, or `vertex_ai/` |
| Want new models and features first, or a model no cloud offers | The provider directly: `anthropic/`, `openai/`, `gemini/`... |
| Need data to stay on your hardware, or have steady volume that a GPU you own would serve more cheaply | Self-hosted: `ollama_chat/` for a laptop or small server, `hosted_vllm/` for production throughput |
| Need resilience against one provider's outage or quota | Several of the above behind one alias, as exercise 12.8 does |

### Exercises

These need a running proxy. Put the config in `exercises/`, export your AWS profile and region in the shell that starts the proxy, and keep `mock_response` lines in the config for offline runs.

```bash
cd exercises
export LITELLM_MASTER_KEY=sk-master-demo LITELLM_LOCAL_MODEL_COST_MAP=True
export AWS_PROFILE=<your-profile> AWS_REGION=us-west-2      # needed only when the config has no mocks
uv run litellm --config proxy_config.yaml --port 4000
```

**12.1 ★ `proxy_config.yaml` + `ex12_1_proxy_client.py`: your own gateway**

Write a config with aliases `fast`, `smart` and `alt` that point at the three Bedrock models (`aws_region_name: os.environ/AWS_REGION`), plus a `broken` alias aimed at a closed port, with `fallbacks: [{"broken": ["fast"]}]` and `num_retries: 1`. The client script uses only the `openai` package, with no `import litellm`. It lists the models, calls each alias with `with_raw_response`, and prints the `x-litellm-model-group`, `x-litellm-response-cost` and `x-litellm-attempted-fallbacks` headers. It then streams a reply from `fast`.

Checks:
- `client.models.list()` returns exactly the four aliases.
- For `broken`, the model-group header is `fast` and attempted fallbacks is `1`.
- The stream yields more than one chunk.

<details><summary>Hint</summary>

Copy the shape of [`examples/proxy/config.yaml`](examples/proxy/config.yaml) and [`examples/proxy/client.py`](examples/proxy/client.py). For live calls, delete the `mock_response` lines and restart the proxy.
</details>

**12.2 ★★ `ex12_2_native_routes.py`: the routes beyond chat completions**

Using `httpx`, call the proxy's Anthropic-format `POST /v1/messages` with model `fast` (authenticate with an `x-api-key` header), then `GET /health/liveliness` and `GET /model/info`.

Checks:
- The `/v1/messages` reply has `type == "message"` and text at `content[0]["text"]`. It is the Anthropic response shape, even though the model behind it is on Bedrock.
- `/model/info` shows the `bedrock/...` model behind each alias.
- A chat request with a made-up key is refused. Print the status code; without a database it is not 401 (see section 12).

The next three exercises use [`examples/bedrock/fake_bedrock.py`](examples/bedrock/fake_bedrock.py) on port 4015, so they run without AWS. Set fake `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` values in the script or in the proxy's shell, and unset `AWS_PROFILE`, so requests are signed with a key you can recognise in the fake's log (`GET /_seen`). The hints say how to run each one against real Bedrock.

**12.3 ★ `ex12_3_bedrock_wire.py`: the same call, two Bedrock APIs, four model IDs**

Send one request (a system prompt, a user message, one tool, `max_tokens=100`) to `bedrock/us.anthropic.claude-haiku-5-5` and to `bedrock/invoke/us.anthropic.claude-haiku-5-5`, with `aws_bedrock_runtime_endpoint` set to the fake. Then call `bedrock/eu.anthropic.claude-haiku-5-5` with `aws_region_name="eu-central-1"`. Compare the input prices of the base ID and the `us.`, `eu.` and `global.` profiles in `litellm.model_cost`. Finally, call an application-inference-profile ARN with and without `base_model`.

Checks:
- The Converse body has `system` as `[{"text": ...}]`, `inferenceConfig.maxTokens == 100` and `toolConfig`; the Invoke body has `max_tokens`, `tools` and `anthropic_version`.
- The SigV4 scope of the `eu.` call is `eu-central-1/bedrock`.
- The `us.` profile's input price is higher than `global.`'s, which equals the base model's.
- The ARN call has no `response_cost` without `base_model`, and a positive one with it.

<details><summary>Hint</summary>

The fake records `path`, `auth` (key, region and service from the SigV4 header) and `body` for every request. Prices are keyed without the `bedrock/` prefix: `litellm.model_cost["us.anthropic.claude-haiku-5-5"]`. For a live run, drop `aws_bedrock_runtime_endpoint`, use `_env.FAST`, and compare `response.usage` and `_hidden_params["response_cost"]` between the two routes.
</details>

**12.4 ★★ `ex12_4_bedrock_failover.yaml` + `ex12_4_bedrock_failover.py`: three regions and a way out**

Write a proxy config whose alias `fast` has three deployments of `bedrock/us.anthropic.claude-haiku-5-5`, in `us-west-2`, `us-east-1` and `us-east-2`, and an alias `alt` on `bedrock/eu.amazon.nova-2-lite-v1:0` in `eu-west-1`, with `fallbacks: [{"fast": ["alt"]}]`, `num_retries: 2` and `cooldown_time: 5`. Point every deployment at the fake through `aws_bedrock_runtime_endpoint: os.environ/BEDROCK_ENDPOINT`. Then use the fake's `GET /_fail?region=<region>&error=throttled|unavailable` to stage incidents.

Checks:
- With every region healthy, 12 calls reach all three regions.
- With `us-west-2` throttled, 10 calls all succeed and us-west-2 is attempted exactly once.
- Six seconds later, with the fake healthy again, us-west-2 serves traffic again.
- With all three Claude regions unavailable, calls are answered by `alt` (`x-litellm-model-group: alt`) from `eu-west-1`.

<details><summary>Hint</summary>

Don't set `allowed_fails`: with it set, LiteLLM cools a deployment down only after more than that many failures within `cooldown_time`, and the throttled region keeps being tried. `GET /_reset` clears both the log and the staged failures. For the live version, your account needs model access in every region you list; a region without it answers 403, which is also a reason to cool down.
</details>

**12.5 ★★ `ex12_5_bedrock_identity.py`: four identities in one Router**

Build an SDK `Router` with four aliases on the same Bedrock model, each with its own identity: `team-a` and `team-b` assume roles in two different accounts (`aws_role_name`, `aws_session_name`, and `aws_sts_endpoint` pointing at the fake, which also answers STS); `team-c` uses a named profile (`aws_profile_name="team-c"`) from a credentials file you write to a temporary path and point `AWS_SHARED_CREDENTIALS_FILE` at; `sandbox` uses a Bedrock API key (`api_key=`). Call each alias three times with `await router.acompletion(...)`.

Checks:
- Exactly two STS `AssumeRole` calls are made, one per role ARN, both signed with the base identity.
- The six team-a and team-b Bedrock calls are signed with the assumed `ASIA...` key and carry a session token.
- The three team-c calls are signed with the profile's key, and the three sandbox calls use `Bearer` with no SigV4 signature.

<details><summary>Hint</summary>

Set `AWS_CONFIG_FILE=/dev/null` so your real `~/.aws/config` can't interfere. Credentials from an assumed role are cached until shortly before they expire, which is why 6 calls make only 2 STS requests. In real AWS, the base identity needs `sts:AssumeRole` on both roles, and each role's trust policy must name the base identity.
</details>

The next three exercises use the fakes of the Azure and Vertex AI subsections: `examples/azure/fake_azure.py 4018` and `examples/vertex/fake_vertex.py 4019`, after `examples/vertex/make_fake_credentials.py`. `GET /_reset` clears a fake's log and staged failures. Verified solutions for 12.6–12.9 are in [`solutions/`](solutions/); 12.1–12.5 and section 13's exercises have hints only.

**12.6 ★ `ex12_6_azure_wire.py`: deployments, API versions and Entra ID on the wire**

With the SDK and `api_base` pointing at a resource on the fake (for example `http://127.0.0.1:4018/westeurope`), call a deployment named `team-gpt` with an API key and `api_version="2024-10-21"`, then again with `base_model="azure/gpt-4o"`, then with `api_version="v1"`. Make three calls that authenticate with workload identity: `azure_ad_token="oidc/env/<VAR>"` plus `tenant_id` and `client_id`, with `AZURE_AUTHORITY_HOST` set to the fake. Finally call deployments named `team-gpt-filtered` and `team-gpt-throttled`.

Checks:
- The first call's path is `/openai/deployments/team-gpt/chat/completions`, its query is `api-version=2024-10-21`, and it carries an `api-key` header. Its `response_cost` is `None`, and positive with `base_model`.
- The v1 call's path is `/openai/v1/chat/completions`, with no query and a Bearer header.
- The three workload-identity calls make exactly one token request, and all three carry the same Bearer token.
- The filtered deployment raises `litellm.ContentPolicyViolationError`, and the throttled one `litellm.RateLimitError`.

<details><summary>Hint</summary>

The fake's log entries have `resource`, `path`, `query`, `auth` and `body`; token requests have a path ending in `/oauth2/v2.0/token` and no `resource`. Set `AZURE_AUTHORITY_HOST` before the first token is requested: LiteLLM caches tokens per tenant, client and authority. For a live run, use your resource's endpoint and a key, or `az login` with `litellm.enable_azure_ad_token_refresh = True`.
</details>

**12.7 ★ `ex12_7_vertex_wire.py`: two model families, three locations, one token**

Using the fake's service-account file as `vertex_credentials` and `api_base` pointing at the fake, call `vertex_ai/gemini-2.5-flash` three times in `us-central1`, then `vertex_ai/claude-haiku-5-5` in `us-central1` and in `global`, each with a system prompt and `max_tokens=100`. Then call a model whose name contains `denied`.

Checks:
- The three Gemini calls make exactly one request to `/token`, and all three use the same Bearer token.
- The Gemini body has `contents`, `system_instruction` and `generationConfig.max_output_tokens == 100`; the Claude call uses `rawPredict` with `anthropic_version == "vertex-2023-10-16"`.
- The `global` Claude call's path contains `/locations/global/`, and its `response_cost` is lower than the `us-central1` call's.
- The `denied` call raises an exception with `status_code == 403` that is **not** a `litellm.PermissionDeniedError`.

<details><summary>Hint</summary>

Make the token-counting calls first: tokens are cached for the whole process, so a later block would see none. Read the file's JSON with `Path(...).read_text()` and pass it as the string. For a live run, run `gcloud auth application-default login`, set `vertex_project` to your project, and drop `vertex_credentials` and `api_base`.
</details>

**12.8 ★★ `ex12_8_three_clouds.yaml` + `ex12_8_three_clouds.py`: one alias, three clouds**

Write a proxy config with one alias, `claude`, that has three deployments of Claude Haiku 5.5: on Bedrock (`examples/bedrock/fake_bedrock.py 4015`, through `aws_bedrock_runtime_endpoint`), in Microsoft Foundry (`azure_ai/`, on the Azure fake) and on Vertex AI (location `global`, on the Vertex fake), with `num_retries: 2` and `cooldown_time: 5`. The client uses only the `openai` package and the fakes' control routes: Bedrock `/_fail?region=`, Azure `/_fail?resource=`, Vertex `/_fail?location=`.

Checks:
- 12 calls reach all three clouds, and every call has a positive `x-litellm-response-cost`.
- With Bedrock throttled, 10 calls all succeed and Bedrock is attempted exactly once.
- A little after the cooldown, with the fakes healthy again, Bedrock serves traffic again.
- With all three throttled, the client gets `openai.RateLimitError` (429).

<details><summary>Hint</summary>

Count model calls only: the Bedrock log also holds STS requests, and the Azure and Vertex logs hold token requests. Start the proxy with fake AWS keys and no `AWS_PROFILE`, as for 12.4. For a live version, each cloud needs model access for Claude Haiku 5.5 and an identity: an AWS profile, a Foundry key or Entra ID, and Google ADC.
</details>

**12.9 ★ `ex12_9_local_first.yaml` + `ex12_9_local_first.py`: a local model first, a hosted one as the way out**

Start Ollama in Docker and pull `qwen2.5:0.5b`, as in "Directly to a model provider". Write a proxy config with `chat` on `ollama_chat/qwen2.5:0.5b` with your own `input_cost_per_token` and `output_cost_per_token`, `chat-down` on the same model at a closed port, and `cloud` on `anthropic/claude-haiku-5-5` (aimed at `examples/_fake_upstream.py 4011` offline). Fall back from both local aliases to `cloud`.

Checks:
- `chat` is served by `chat`, the reply mentions Paris (the real local model answered), and `x-litellm-response-cost` is positive.
- `chat-down` is served by `cloud` with `x-litellm-attempted-fallbacks: 1`.
- Streaming from `chat` yields more than one chunk.

<details><summary>Hint</summary>

Without the prices, an Ollama call costs `0.0` and budgets never see it. Set `num_retries: 0` so the closed port fails fast. No Docker? Use `hosted_vllm/` aimed at the fake upstream for `chat` and drop the Paris check. For a live `cloud`, remove its `api_base` and set a real `ANTHROPIC_API_KEY`, or use a `bedrock/` model.
</details>

**12.10 ★★ `ex12_10_mantle_mix.yaml` + `ex12_10_mantle_mix.py`: bedrock-runtime and Mantle behind one proxy**

Write a proxy config with an alias `assistant` that has two deployments in us-west-2: `bedrock/us.anthropic.claude-haiku-5-5` on bedrock-runtime and `bedrock_mantle/openai.gpt-oss-120b` on Mantle. Add `gpt-5-west` on `bedrock_mantle/openai.gpt-5.5` in us-west-2 and `gpt-5-east` on the same model in us-east-1, with a fallback from west to east. With the OpenAI SDK, send ten chat requests to `assistant` and add up the cost per deployment. Then call `gpt-5-west`, and finally call `assistant` through `client.responses.create()`.

Checks:
- Both `assistant` deployments answer at least once, told apart by `x-litellm-model-name`, and every reply mentions Paris.
- `gpt-5-west` is answered by the model group `gpt-5-east`, with `x-litellm-attempted-fallbacks: 1`.
- The Responses API call through the proxy answers too, whichever deployment it lands on.

<details><summary>Hint</summary>

This needs real AWS credentials (an SSO profile in `AWS_PROFILE`), because there is no fake Mantle. Set `num_retries: 0`, so the missing model in us-west-2 goes straight to the fallback. Use `x-litellm-model-group` for the fallback check: both gpt-5.5 deployments have the same `x-litellm-model-name`.
</details>

## 13. Virtual keys, budgets and rate limits

**Use case:** give each app, team or person their own key with an allowed model list, a dollar budget and a rate limit, without ever handing out a provider key.

This needs Postgres. A throwaway one in Docker:

```bash
docker run -d --name litellm-tutorial-db -e POSTGRES_PASSWORD=demo -e POSTGRES_DB=litellm \
  -p 55432:5432 postgres:16
export DATABASE_URL=postgresql://postgres:demo@localhost:55432/litellm

# One-off: generate the Prisma client the proxy uses for its database
uv run prisma generate --schema "$(uv run python -c 'import litellm.proxy,os;print(os.path.dirname(litellm.proxy.__file__))')/schema.prisma"

uv run litellm --config config.yaml --port 4000   # creates its tables on first start
```

```bash
curl -s localhost:4000/health/readiness           # in another shell; this endpoint needs no key
# {"status": "healthy", "db": "connected"}
```

Two setup failures I hit, in order:

1. Without `litellm[extra_proxy]` installed (`pyproject.toml` includes it): *"a database URL is set but the prisma CLI is neither on PATH nor importable"*.
2. Without `prisma generate`: *"The Client hasn't been generated yet"*. The official `ghcr.io/berriai/litellm` Docker image has both steps done already, which is why most deployments use it.

[`examples/proxy/keys_demo.sh`](examples/proxy/keys_demo.sh) creates a key and then tests every limit:

```bash
curl -s "$PROXY/key/generate" -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "$JSON" -d '{
  "key_alias": "demo-app-<timestamp>", "models": ["chat-cheap"],
  "max_budget": 0.00003, "rpm_limit": 10, "metadata": {"team": "search"}
}'
```

```text
== 1. create a key: only 'chat-cheap', $0.00003 budget, 10 requests/min
key: sk-1o10q...
== 2. allowed model
Hi from GPT-4o mini (via the proxy)
== 3. model not on the key's list
403 The requested model 'chat' is not available for this API key, or the model name is invalid
== 4. spend until the budget runs out
call 2: ok
call 3: ok
call 4: 422 Budget has been exceeded! Key=demo-app-1794601606 (sk-...S7Cg) Current cost: 3.9
call 5: 422 Budget has been exceeded! Key=demo-app-1794601606 (sk-...S7Cg) Current cost: 3.9
== 5. what the proxy recorded for the key
{'key_alias': 'demo-app-1794601606', 'spend': 0.0, 'max_budget': 3e-05, 'models': ['chat-cheap'], 'rpm_limit': 10}
== 6. an unknown key
401 Authentication Error, Invalid API key provided.
== 7. rate limit: a key allowed 2 requests per minute
call 1: ok
call 2: ok
call 3: 429 Rate limit exceeded for api_key: d2929e29d17b7fa5b06345125899fbcaf6eff
```

The budget message's "Current cost" is cut off by the demo script; the full value was `3.96e-05`.

How to read this:

- **Each limit has its own status code.** The model allowlist gives 403, the budget 422, the rate limit 429 and an unknown key 401. Clients can tell "not allowed", "out of money" and "slow down" apart.
- **A budget can overshoot by one call.** Each call cost $0.0000132. After three calls, spend was $0.0000396, which is over the $0.00003 limit, and *then* the fourth call was refused. As in section 8, the check happens before a call, and the call's cost is only known after it.
- **The database lags behind enforcement.** Step 5 ran right after the calls and showed `spend: 0.0`, even though the proxy was already refusing the key. Enforcement uses an in-memory counter, and spend is written to Postgres in batches every `PROXY_BATCH_WRITE_AT` seconds (default 10). Queried about 20 seconds later, the key showed `3.96e-05`. Don't build a "check spend right after the call" test on `/key/info`.
- **Key aliases must be unique.** Re-running with a fixed alias returned `400 Key with alias 'demo-app' already exists`, so the script adds a timestamp.

Beyond keys, the proxy also has teams and users, each with their own budget (`/team/new`, `/user/new`). It records spend reports (`/spend/logs`), shows an admin UI at `http://localhost:4000/ui`, and offers guardrails such as PII masking and prompt-injection checks (section 21). Roles, identity providers and secret handling are in section 20. It also exposes provider-native routes, such as Anthropic's `/v1/messages`, so Anthropic-SDK clients can use it too.

Clean up:

```bash
docker rm -f litellm-tutorial-db
```

### The same stack with Docker Compose

Running the proxy from `uv` is useful for learning, but deployments use the image. [`examples/proxy/docker-compose.yml`](examples/proxy/docker-compose.yml) starts Postgres and the proxy together, with the same `config.yaml`:

```yaml
name: litellm-tutorial

services:
  db:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: demo
      POSTGRES_DB: litellm
    ports:
      - "127.0.0.1:55432:5432"   # only for inspecting the database with psql
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d litellm"]
      interval: 2s
      retries: 15

  proxy:
    image: ghcr.io/berriai/litellm:v1.110.2
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    ports:
      - "127.0.0.1:4000:4000"
    volumes:
      - ./config.yaml:/app/config.yaml:ro
    environment:
      LITELLM_MASTER_KEY: ${LITELLM_MASTER_KEY:?export LITELLM_MASTER_KEY first}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-unused}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-unused}
      DATABASE_URL: postgresql://postgres:demo@db:5432/litellm   # "db" is the service name, not localhost
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:4000/health/liveliness')\""]
      interval: 5s
      retries: 30

volumes:
  pgdata:
```

```bash
cd examples/proxy
docker rm -f litellm-tutorial-db                   # frees port 55432 if the container above is still running
# Stop the `uv run litellm` proxy from above first (Ctrl-C): Compose's proxy also binds port 4000.
export LITELLM_MASTER_KEY=sk-master-demo
docker compose up -d --wait                        # returns once both healthchecks pass (about 35 s here)
curl -s localhost:4000/health/readiness
# {"status":"healthy","db":"connected"}
bash keys_demo.sh                                  # same output as above
```

`keys_demo.sh` printed the same seven steps, with the same 403, 422, 401 and 429 codes, as the `uv` run above. Points to note:

- **No `prisma generate` and no `extra_proxy`.** The image includes the Prisma toolchain and applies the database migrations on start (the log reports *"Found 233 migrations"*). Both setup failures listed above disappear.
- **Inside a container, `localhost` is the container itself.** The proxy reaches Postgres as `db`, the service name, on the internal port 5432. With `DATABASE_URL` pointing at `localhost:55432`, as in the `uv` setup, the proxy exits with *"P1001: Can't reach database server at `localhost:55432`"*.
- **`depends_on: condition: service_healthy`** holds the proxy back until Postgres accepts connections. Without it, the proxy can start first and fail its migrations.
- **`${LITELLM_MASTER_KEY:?...}`** makes Compose refuse to start if the master key isn't exported, rather than starting a proxy with an empty one. `${ANTHROPIC_API_KEY:-unused}` falls back to a placeholder, which is enough for the `mock_response` models.
- **Keys live in the `pgdata` volume.** A key created before `docker compose down` and `up` still worked afterwards. `docker compose down -v` deletes the volume, and every key with it.
- **Port 55432 is optional.** The proxy doesn't need it; it is there so you can run `psql postgresql://postgres:demo@localhost:55432/litellm` and look at the `LiteLLM_VerificationToken` and `LiteLLM_SpendLogs` tables.

For real calls, delete the `mock_response` lines, export the real provider keys and run `docker compose up -d` again. Compose recreates the proxy container when its environment changes, but not when only a mounted file changes, so after editing `config.yaml` run `docker compose restart proxy`.

Clean up:

```bash
docker compose down -v                             # containers, network and the pgdata volume
```

### Exercises

Exercises 13.1 and 13.2 need either the Postgres setup above or the Compose stack. Use `httpx` for the admin calls, and add a timestamp to every alias so the scripts can be re-run.

**13.1 ★ `ex13_1_key_lifecycle.py`: a key from birth to deletion**

1. Create a key allowed only `fast`, with `rpm_limit: 3`, `max_budget: 1.0` and `metadata: {"owner": "ex13"}`.
2. Call `fast` (allowed), then `smart` (not on the key's list).
3. Call `fast` quickly until you get a 429 (it should take no more than 3 calls), then wait 60 s.
4. Add `smart` with `/key/update` and call it again.
5. Block the key with `/key/block`, call with it, then unblock it.
6. Delete the key with `/key/delete` and call with it once more.

Checks:
- Steps 2 and 3 return 200, 403 and then 429; step 4 returns 200.
- Step 5 refuses the blocked key. Record the status code you get in a comment. A blocked key and a deleted key get the same code, so tell them apart by the error message.
- After step 6, the deleted key gets 401.

<details><summary>Hint</summary>

Admin endpoints take the master key as `Authorization: Bearer`. `/key/update` takes `{"key": ..., "models": [...]}`, `/key/block` and `/key/unblock` take `{"key": ...}`, and `/key/delete` takes a list: `{"keys": [...]}`.
</details>

**13.2 ★★ `ex13_2_team_and_customer_budgets.py`: shared and per-end-user budgets**

1. Create a team with `/team/new` with a tiny `max_budget` (a few calls' worth) and two keys in it. Spend the budget with key A, then call with key B.
2. Create a customer with `/customer/new` (`user_id`, tiny `max_budget`; this is the endpoint in 1.110.2, and the docs call it the legacy path now that 1.111 added `/management/v1/customer_*`), and send chat requests with `"user": "<that id>"` in the body until they are refused.
3. Wait at least `PROXY_BATCH_WRITE_AT` (10 s by default), then read spend with `/key/info` and `/spend/logs`.

Checks:
- Key B is refused even though key B itself spent nothing, because the budget belongs to the team.
- The customer's requests are refused once their budget is used up.
- After the wait, recorded spend for key A is greater than 0.

<details><summary>Hint</summary>

Budgets overshoot by up to one call (section 8), so "a few calls' worth" means the refusal comes one call later than you might expect.
</details>

**13.3 ★ `docker-compose.yml` + `ex13_3_compose_lifecycle.py`: where the keys live**

Write `exercises/docker-compose.yml` that runs your `proxy_config.yaml` from exercise 12.1 with Postgres, modelled on [`examples/proxy/docker-compose.yml`](examples/proxy/docker-compose.yml). Then write a script that drives it with `subprocess` and `httpx`:

1. `docker compose up -d --wait`, create a key allowed `fast`, and call `fast` with it.
2. `docker compose restart proxy`, wait for `/health/readiness` to report `"db": "connected"`, and call again with the same key.
3. `docker compose down -v`, bring the stack back up, and call once more.

Checks:
- The three calls return 200, 200 and 401.
- `docker compose config` fails with your error message when `LITELLM_MASTER_KEY` isn't exported.

<details><summary>Hint</summary>

The container can't see your shell's AWS session, so for live Bedrock calls mount your AWS config read-only (`${HOME}/.aws:/root/.aws:ro`) and pass `AWS_PROFILE` and `AWS_REGION` through `environment:`. Sign in with `aws sso login` before starting the stack; the container uses the cached token. With the `mock_response` lines kept, no AWS access is needed. Readiness can briefly fail with a connection error while the proxy restarts, so catch `httpx.TransportError` in the wait loop.
</details>

---

## 14. Smart routing: let the router choose the model

**Use case:** send each request to the cheapest model that can handle it, without the caller choosing a model.

Section 7's router balances load across deployments of the same model. A smart router chooses between different models, request by request. LiteLLM 1.110.2 ships five. This section covers four of them; the fifth, the Switchyard stage router (`switchyard_router_config`, new in 1.110.0), sends each turn to an efficient or a capable model and escalates on signals that the cheaper answer failed, optionally with an LLM judge. It needs the `litellm[switchyard]` extra, which pins an alpha package (`nemo-switchyard==0.4.0a1`), so it is not run here. The current docs mark the semantic router as deprecated and steer new deployments to the complexity router, so read 14b to understand an existing setup, not to start a new one:

| Router | `litellm_params.model` | How it chooses | Needs | Subsection |
| --- | --- | --- | --- | --- |
| Complexity | `auto_router/complexity_router` | Scores the prompt locally on keywords and length, sorts it into SIMPLE, MEDIUM, COMPLEX or REASONING, and maps each level to a model | Nothing extra | 14a |
| Semantic | `auto_router/<any other name>` | Embeds the prompt and picks the route whose example phrases are most similar | The `semantic-router` package and an embedding model | 14b |
| Quality | `auto_router/quality_router` | Classifies like the complexity router, then picks the cheapest model whose declared quality tier matches | Nothing extra | 14c |
| Adaptive | `auto_router/adaptive_router` | A bandit that learns from conversation signals which model users are happy with | Nothing extra; the proxy saves what it learns to Postgres | 14d |

What all four have in common:

- **A smart router is a model entry.** Its `model_name` is the alias callers use, its `litellm_params.model` starts with `auto_router/`, and its config names other model groups in the same `model_list`. The proxy config takes the same entries.
- **They route only on the async path in 1.110.2.** `await router.acompletion(...)` works. The synchronous `router.completion(...)` fails with `BadRequestError: ... Every deployment for it is a strategy router marker (auto_router/...), which is not a callable model, and no pre-routing strategy selected a deployment for this request`. The proxy handles requests asynchronously, so it is not affected.
- **None of them needs a licence for what this section uses.** The SDK `Router` has no limits. On the proxy some complexity-router options are metered, not locked: without the `auto_router` licence feature you get one router each that uses the `heuristic_v2`, `capability` or `llm_v2` classifier or custom tier definitions or classifier prompts, and one router with tuned heuristic scoring (`tier_boundaries`, `keyword_tier_rules`, weights, keyword lists). More than that needs the licence.

### 14a. Complexity router

**Use case:** a cheap model for easy questions and a strong one for hard questions, decided locally in under a millisecond, with no extra model call.

The router scores the last user message on seven weighted dimensions: length, code keywords, reasoning phrases, technical terms, simple-question phrases, multi-step patterns and question marks. It cuts the score into four tiers at `tier_boundaries` (by default 0.15, 0.35 and 0.60), and `tiers` maps each tier to a model group. The decision appears in the logging payload at `standard_logging_object["metadata"]["routing_decision"]`, which a `CustomLogger` (section 10) can read.

[`14a_complexity_router.py`](examples/14a_complexity_router.py)

```python
"""Complexity router: score each prompt locally and send it to the model for its tier."""
import asyncio

import litellm
from litellm import Router
from litellm.integrations.custom_logger import CustomLogger

from _mock import mock

MODELS = [
    {"model_name": "small", "litellm_params": {"model": "openai/gpt-4o-mini"}},
    {"model_name": "mid", "litellm_params": {"model": "openai/gpt-4o"}},
    {"model_name": "big", "litellm_params": {"model": "anthropic/claude-sonnet-5-5"}},
    {"model_name": "think", "litellm_params": {"model": "anthropic/claude-opus-5-5"}},
]
TIERS = {"SIMPLE": "small", "MEDIUM": "mid", "COMPLEX": "big", "REASONING": "think"}
PROMPTS = [
    "What is the capital of France?",
    "Summarise the plot of Hamlet in two sentences.",
    "Write a Python function that parses a CSV file and returns a list of dicts.",
    "Debug this async Python code: the database connection pool deadlocks under load.",
    "Think step by step: analyze the trade-offs between eventual and strong consistency, "
    "then design a replication protocol and prove it is linearizable.",
]


class Decisions(CustomLogger):
    """Keep the routing decision of every successful call."""

    def __init__(self):
        super().__init__()
        self.seen = []

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self.seen.append(kwargs["standard_logging_object"]["metadata"]["routing_decision"])


def build_router(config):
    """Return a Router with the four tier models plus an auto-router group called 'auto'."""
    auto = {"model_name": "auto", "litellm_params": {
        "model": "auto_router/complexity_router", "complexity_router_config": config}}
    return Router(model_list=[*MODELS, auto])


async def run(router, decisions, title):
    """Send every prompt to 'auto' and print where it went and why."""
    print(title)
    for prompt in PROMPTS:
        resp = await router.acompletion(model="auto", messages=[{"role": "user", "content": prompt}],
                                        **mock("ok"))
        await asyncio.sleep(0.05)
        d = decisions.seen[-1]
        score = f"{d['score']:.2f}" if "score" in d else "-"
        print(f"  {d['tier']:9} {score:>5}  {d['cause']:21} -> {resp.model:18} {d.get('signals', '')}")


async def main():
    decisions = Decisions()
    litellm.callbacks = [decisions]
    await run(build_router({"tiers": TIERS}), decisions, "Default weights and boundaries")
    tuned = {
        "tiers": TIERS,
        "tier_boundaries": {"simple_medium": 0.10, "medium_complex": 0.25, "complex_reasoning": 0.45},
        "keyword_tier_rules": [{"keywords": ["prove", "linearizable"], "tier": "REASONING"}],
    }
    await run(build_router(tuned), decisions, "Lower boundaries plus a keyword rule")


asyncio.run(main())
```

```text
Default weights and boundaries
  SIMPLE    -0.15  heuristic_scorer      -> gpt-4o-mini        ['short (7 tokens)', 'simple (what is)']
  SIMPLE    -0.10  heuristic_scorer      -> gpt-4o-mini        ['short (11 tokens)']
  MEDIUM     0.30  heuristic_scorer      -> gpt-4o             ['code (function, python)']
  MEDIUM     0.30  heuristic_scorer      -> gpt-4o             ['code (async, debug, database)']
  MEDIUM     0.17  heuristic_scorer      -> gpt-4o             ['reasoning (step by step)']
Lower boundaries plus a keyword rule
  SIMPLE    -0.15  heuristic_scorer      -> gpt-4o-mini        ['short (7 tokens)', 'simple (what is)']
  SIMPLE    -0.10  heuristic_scorer      -> gpt-4o-mini        ['short (11 tokens)']
  COMPLEX    0.30  heuristic_scorer      -> claude-sonnet-5-5  ['code (function, python)']
  COMPLEX    0.30  heuristic_scorer      -> claude-sonnet-5-5  ['code (async, debug, database)']
  REASONING     -  literal_keyword_match -> claude-opus-5-5
```

What to notice:

- **With default settings, most prompts land in SIMPLE or MEDIUM.** Both code prompts scored 0.30, just under the 0.35 COMPLEX boundary. The "step by step ... prove it is linearizable" prompt scored only 0.17: "prove" and "linearizable" are not on the default keyword lists, and the scorer only sees keywords.
- **Two reasoning phrases jump straight to REASONING.** A prompt with two or more phrases such as "step by step", "show your work" or "compare and contrast" is promoted to REASONING with cause `reasoning_override`, provided its score clears the SIMPLE boundary. Exercise 14a.1 uses this.
- **Tune it with your own prompts.** Lowering `tier_boundaries` moved both code prompts to COMPLEX. A `keyword_tier_rules` entry bypasses scoring entirely: the decision has cause `literal_keyword_match` and no score. Other options include `dimension_weights`, `custom_technical_keywords`, `escalation_keywords` and `default_model`.
- **It replaces your `max_tokens`.** By default (`max_tokens_from_tier_model: true`) every routed request gets `max_tokens` set to the chosen model's maximum output, whatever the caller sent. With the fake server from section 1, a caller's `max_tokens=50` reached gpt-4o-mini as 16384. Set it to `"clamp"` to keep a smaller value, or to `false` to forward the caller's value unchanged. This matters for the cap advice in section 1.
- `classifier_type: "llm"` asks a model to pick the tier instead. That costs one extra call per request.

#### Exercises

**14a.1 ★ `ex14a_1_complexity_tiers.py`: where do your prompts land?**

Build a router with two groups, `fast` (`_env.FAST`) and `smart` (`_env.SMART`), and a complexity router `auto` that sends SIMPLE and MEDIUM to `fast`, and COMPLEX and REASONING to `smart`. Send it "What is 2 + 2?", "Define photosynthesis.", "Write a Python function that merges two sorted lists.", "Think step by step and prove that the square root of 2 is irrational." and "Hello!". Then write a prompt of your own that lands in REASONING. Print each prompt's tier, score, cause and model, read from the routing decision.

Checks:
- "What is 2 + 2?" is SIMPLE, and the merge-function prompt is not SIMPLE.
- Every decision's `routed_model` is the group its tier maps to.
- The "step by step ... prove" prompt is not REASONING, but your own prompt is, with cause `reasoning_override`.

<details><summary>Hint</summary>

Copy the `Decisions` logger from the example. The scorer only counts phrases on its keyword lists; "step by step" is one reasoning phrase, and you need two. The overall score must still clear the tier's threshold, and a very short prompt or a "what is" opener pulls it down, so make the prompt a full sentence. The default list includes "compare and contrast", "show your work" and "explain your reasoning". Classification is local, so the checks hold live too.
</details>

**14a.2 ★ `ex14a_2_keep_my_max_tokens.py`: the router overrides `max_tokens`**

Send "Hi there" with `max_tokens=50` through a complexity router whose four tiers all map to `fast`, three times: with `max_tokens_from_tier_model` left unset, set to `"clamp"` and set to `False`. A `CustomLogger` records the `max_tokens` that was actually used.

Checks:
- Unset: the recorded value is `litellm.get_model_info(_env.FAST)["max_output_tokens"]`, not 50.
- `"clamp"` and `False`: the recorded value is 50.

<details><summary>Hint</summary>

The final request parameters are in the logger's `kwargs["optional_params"]`.
</details>

### 14b. Semantic router

**Use case:** route by topic. Code questions go to a coding model, translations to a multilingual model, and everything else to a cheap default.

You describe each route with a few example phrases, called utterances. The router embeds the utterances once and then embeds the last user message of each request. It picks the route whose utterances are most similar, provided the similarity clears that route's `score_threshold` (default 0.3); otherwise it uses `auto_router_default_model`. A route's `name` is the model group it sends to.

It needs the `semantic-router` package, which is LiteLLM's `semantic-router` extra. Every release LiteLLM accepts (below 1.0) requires `openai<3`, and this project pins `openai==3.50.0`, so the package is not in [`pyproject.toml`](pyproject.toml). Run this subsection and its exercises from `examples` in a pinned overlay. uv downloads the two packages on the first run and uses `openai` 2.x for that run only, which leaves the project environment unchanged:

```bash
uv run --with semantic-router==0.1.16 --with openai==2.54.0 python 14b_semantic_router.py
```

To stay offline, the script runs a fake embedding server. Its vectors are hashed word counts, so texts that share words come out similar. Real embeddings capture meaning, not shared words.

[`14b_semantic_router.py`](examples/14b_semantic_router.py)

```python
"""Semantic router: embed the prompt and send it to the route whose example phrases it is closest to."""
import asyncio
import hashlib
import json
import logging
import math
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import litellm
from litellm import Router
from litellm.integrations.custom_logger import CustomLogger

ROUTES = {"routes": [
    {"name": "coder", "description": "Programming questions", "score_threshold": 0.3,
     "utterances": ["write a python function", "fix this bug in my code",
                    "how do I sort a list in python", "explain this javascript error"]},
    {"name": "writer", "description": "Creative writing", "score_threshold": 0.3,
     "utterances": ["write a poem about the sea", "write a short story about a dragon",
                    "give me a haiku about autumn"]},
]}
PROMPTS = ["how do I fix this python bug", "write a poem about autumn leaves",
           "what is the capital of France"]


def embed(text, dim=256):
    """Return a normalised hashed bag-of-words vector, so texts sharing words point the same way."""
    vec = [0.0] * dim
    for word in re.findall(r"[a-z]+", text.lower()):
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class FakeEmbeddings(BaseHTTPRequestHandler):
    """Answer POST /v1/embeddings in OpenAI format, so the demo needs no embedding API."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
        data = json.dumps({"object": "list", "model": body["model"],
                           "data": [{"object": "embedding", "index": i, "embedding": embed(t)}
                                    for i, t in enumerate(texts)],
                           "usage": {"prompt_tokens": 1, "total_tokens": 1}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class Decisions(CustomLogger):
    """Keep the routing decision of every successful call."""

    def __init__(self):
        super().__init__()
        self.seen = []

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self.seen.append(kwargs["standard_logging_object"]["metadata"]["routing_decision"])


async def main():
    server = HTTPServer(("127.0.0.1", 0), FakeEmbeddings)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    decisions = Decisions()
    litellm.callbacks = [decisions]
    router = Router(model_list=[
        {"model_name": "coder", "litellm_params": {"model": "openai/gpt-4o", "mock_response": "def f(): ..."}},
        {"model_name": "writer", "litellm_params": {"model": "anthropic/claude-sonnet-5-5",
                                                    "mock_response": "Leaves fall..."}},
        {"model_name": "general", "litellm_params": {"model": "openai/gpt-4o-mini", "mock_response": "Paris."}},
        {"model_name": "embedder", "litellm_params": {
            "model": "openai/fake-embed", "api_key": "fake", "api_base": f"http://127.0.0.1:{server.server_port}/v1"}},
        {"model_name": "auto", "litellm_params": {
            "model": "auto_router/semantic",
            "auto_router_config": json.dumps(ROUTES),
            "auto_router_default_model": "general",
            "auto_router_embedding_model": "embedder"}},
    ])
    logging.getLogger("semantic_router").setLevel(logging.ERROR)
    for prompt in PROMPTS:
        resp = await router.acompletion(model="auto", messages=[{"role": "user", "content": prompt}])
        await asyncio.sleep(0.05)
        d = decisions.seen[-1]
        print(f"{prompt!r:34} -> {d['routed_model']:8} {d['cause']:17} {resp.model}")
    server.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
```

```text
'how do I fix this python bug'     -> coder    semantic_match    gpt-4o
'write a poem about autumn leaves' -> writer   semantic_match    claude-sonnet-5-5
'what is the capital of France'    -> general  semantic_no_match gpt-4o-mini
```

What to notice:

- **`auto_router_config` is a JSON string**, so use `json.dumps(...)`; a dict fails validation. `auto_router_embedding_model` names a model group in the same `model_list`, which is where it gets its `api_base` and key. Only the last user message is embedded, cut to `auto_router_max_input_chars` (default 2000).
- **A failed query embedding doesn't fail the request.** The request goes to the default model with cause `semantic_error` (exercise 14b.2). The route index, though, is built on the first request; if the embedding model is down at that point, the request fails, and the next request tries again.
- **Use `auto_router_config`, not `auto_router_config_path`.** The file variant goes through `semantic-router`'s own loader, which needs that library's encoder settings and makes its own embedding calls outside LiteLLM.
- Importing `semantic-router` configures the root logger at INFO level, which doubles LiteLLM's log lines. The script calls `logging.basicConfig(level=logging.WARNING)` first to prevent that.

#### Exercises

**14b.1 ★ `ex14b_1_routes.py`: topic routes**

Build a semantic router `auto` with two routes: `smart` for programming (utterances such as "write a python function", "fix this bug in my code", "explain this stack trace") and `alt` for translation ("translate this sentence into french", "how do you say hello in spanish"), with `fast` as the default. Offline, the embedding model is the fake server from the example. Live, use `bedrock/amazon.titan-embed-text-v2:0`. Route "fix the bug in this python function", "sort this list in python", "translate good morning into french", "how do you say thank you in spanish" and "what is the tallest mountain in the world".

Checks:
- Offline: the first two go to `smart`, the next two to `alt`, and the last one to `fast` with cause `semantic_no_match`; the others have cause `semantic_match`.
- Live: every decision's `routed_model` is one of `smart`, `alt` or `fast`.

<details><summary>Hint</summary>

Run it with `uv run --with semantic-router==0.1.16 --with openai==2.54.0 python ex14b_1_routes.py`. Copy `embed` and `FakeEmbeddings` from the example. With the fake embedder, the shared words decide: "how do I sort a dict in python" goes to the translation route, because of "how do". I have not run the live path.
</details>

**14b.2 ★★ `ex14b_2_threshold_and_failure.py`: thresholds and a dead embedding model**

Using the routes from 14b.1 with the fake embedder (offline only):

1. Set every route's `score_threshold` to 0.95 and send "fix the bug in this python function".
2. Back at 0.3, send it again, then shut the embedding server down (`server.shutdown()` and `server.server_close()`) and send it a third time.

Checks:
- (1) goes to `fast` with cause `semantic_no_match`.
- (2) goes to `smart` while the server is up, then to `fast` with cause `semantic_error` once it is down.

<details><summary>Hint</summary>

Send at least one request before shutting the server down; the route index is built on the first request, and a failure at that point fails the request instead of falling back. Expect warnings and a retry message while the server is down.
</details>

### 14c. Quality router

**Use case:** many models at several capability levels. Each model declares its own level and price, and the router picks the cheapest model at the level the request needs.

The router classifies the prompt with the complexity router's default heuristic. It maps the result through `complexity_to_quality` (by default SIMPLE→1, MEDIUM→2, COMPLEX→3, REASONING→4) to a target tier. Then it picks from `available_models` the model whose `model_info.litellm_routing_preferences.quality_tier` matches.

[`14c_quality_router.py`](examples/14c_quality_router.py)

```python
"""Quality router: each model declares its own quality tier; the router maps complexity to a tier."""
import asyncio

from litellm import Router

from _mock import mock


def model(name, provider_model, tier, cost, keywords=()):
    """Return a deployment that declares its quality tier, price and keywords."""
    return {
        "model_name": name,
        "litellm_params": {"model": provider_model},
        "model_info": {
            "input_cost_per_token": cost,
            "litellm_routing_preferences": {"quality_tier": tier, "keywords": list(keywords)},
        },
    }


MODELS = [
    model("small", "openai/gpt-4o-mini", 1, 0.15e-6),
    model("mid", "openai/gpt-4.1-mini", 2, 0.40e-6),
    model("big", "openai/gpt-4o", 3, 2.50e-6),
    model("big-cheap", "openai/gpt-4.1", 3, 2.00e-6),
    model("think", "anthropic/claude-opus-5-5", 4, 5.00e-6, keywords=["prove"]),
]
AUTO = {"model_name": "auto", "litellm_params": {
    "model": "auto_router/quality_router",
    "quality_router_config": {
        "available_models": [m["model_name"] for m in MODELS],
        "default_model": "small",
        "complexity_to_quality": {"SIMPLE": 1, "MEDIUM": 2, "COMPLEX": 3, "REASONING": 4},
    },
}}
PROMPTS = [
    "What is the capital of France?",
    "Write a SQL query that joins orders and customers and returns the top 5 customers by revenue.",
    "Design a distributed rate limiter architecture for a microservice system, "
    "handle failover, consistency, and implement it in Python with tests.",
    "Think step by step: analyze the trade-offs, derive the time complexity, "
    "and reason carefully about whether this algorithm is optimal. Explain your reasoning.",
    "Please prove that the square root of 2 is irrational.",
]


async def main():
    router = Router(model_list=[*MODELS, AUTO])
    for prompt in PROMPTS:
        resp = await router.acompletion(model="auto", messages=[{"role": "user", "content": prompt}],
                                        **mock("ok"))
        h = resp._hidden_params["additional_headers"]
        why = h.get("x-litellm-quality-router-complexity") or f"keyword {h['x-litellm-quality-router-keyword']!r}"
        print(f"{why:16} tier {h['x-litellm-quality-router-tier']} -> "
              f"{h['x-litellm-quality-router-model']:9} ({resp.model}) | {prompt[:40]}")


asyncio.run(main())
```

```text
SIMPLE           tier 1 -> small     (gpt-4o-mini) | What is the capital of France?
MEDIUM           tier 2 -> mid       (gpt-4.1-mini) | Write a SQL query that joins orders and 
COMPLEX          tier 3 -> big-cheap (gpt-4.1) | Design a distributed rate limiter archit
REASONING        tier 4 -> think     (claude-opus-5-5) | Think step by step: analyze the trade-of
keyword 'prove'  tier 4 -> think     (claude-opus-5-5) | Please prove that the square root of 2 i
```

What to notice:

- **Ties within a tier** go to the lowest `order`, then the lowest `input_cost_per_token`, then the name. `big-cheap` beat `big` on price. A model with no price counts as the most expensive.
- **Gaps:** when no model has the target tier, the router takes the nearest higher tier, then the nearest lower one, then `default_model`.
- **Keywords skip classification.** A model's `keywords` are matched case-insensitively against the last user message before scoring, and among several matches the highest tier wins.
- **The router config still lists every model.** A model that declares a tier but is missing from `available_models` is ignored without a warning. A `complexity_to_quality` you supply replaces the default table instead of merging into it. `default_model` is required. The classifier itself can't be configured.
- **Which model answered:** the `x-litellm-quality-router-*` entries in `resp._hidden_params["additional_headers"]` give the model group, the complexity and the target tier.

#### Exercises

**14c.1 ★ `ex14c_1_tier_ties.py`: ties and gaps**

Declare three models for a quality router: `fast` (`_env.FAST`, tier 1, `input_cost_per_token` 1.0e-6), `alt` (`_env.ALT`, tier 1, 0.3e-6) and `smart` (`_env.SMART`, tier 3, 5.0e-6). There is no tier-2 model. Send "What is the capital of Japan?" and "Write a SQL query that returns the ten newest orders." Then rebuild the router with `order: 1` added to `fast`, and send the first prompt again.

Checks:
- The SIMPLE prompt goes to `alt`, the cheaper tier-1 model.
- The MEDIUM prompt goes to `smart`, rounding up past the missing tier 2.
- With `order: 1`, the SIMPLE prompt goes to `fast` despite its price.

<details><summary>Hint</summary>

Read the decision from `resp._hidden_params["additional_headers"]`. The `...-tier` entry is the target tier, so it says 2 even when a tier-3 model answers.
</details>

**14c.2 ★★ `ex14c_2_misconfig.py`: three ways to misconfigure it**

Show each mistake and what it does:

1. A quality router with no `default_model`.
2. `alt` declares tier 1 but is left out of `available_models`; `fast` declares tier 2 and is listed. Send a SIMPLE prompt.
3. `complexity_to_quality` set to `{"MEDIUM": 2}` only. Send a SIMPLE prompt.

Checks:
- (1) raises `ValueError` when the `Router` is built, and the message mentions the default model.
- (2) is answered by `fast`: `alt` is ignored without an error.
- (3) raises `ValueError` on the request, and the message names `SIMPLE`.

<details><summary>Hint</summary>

(2) and (3) only fail or misroute at request time: the router builds its tier index on the first request.
</details>

### 14d. Adaptive router

**Use case:** you don't know in advance which model your users are happiest with, so the router learns it from the conversations.

Each pair of request type and model has a Beta(alpha, beta) score: alpha counts good outcomes and beta bad ones, so alpha / (alpha + beta) is the model's estimated quality. On every call the router draws a random sample from each candidate's score, combines it with price using `weights` (default quality 0.7, cost 0.3), and picks the highest. This is Thompson sampling. After each turn it reads the conversation for signals. Feedback in the user's new message counts for or against the model that gave the previous reply; a repeated reply or tool loop counts against the model answering now:

| Signal | Detected when | Effect |
| --- | --- | --- |
| Satisfaction | The user says "thanks", "perfect", "that worked" and similar | +1 alpha, at most once per session and only from turn 3 |
| Disengagement | "forget it", "never mind", "stop" and similar | +1 beta |
| Misalignment | Two consecutive user messages share some words but less than 45% of them, which suggests a rephrased request | +1 beta |
| Stagnation | Two consecutive replies share half their words or more | +1 beta |
| Tool failure or tool loop | A tool result marked as an error, or the same tool call a third time | +1 or +0.5 beta |

The request type (code generation, writing, analytical reasoning and four others) comes from regular expressions on the last user message.

The demo uses two made-up models of equal rank. The simulated user gives up on one and thanks the other.

[`14d_adaptive_router.py`](examples/14d_adaptive_router.py)

```python
"""Adaptive router: a bandit learns from conversation signals which model users are happy with."""
import asyncio
import random
from collections import Counter

from litellm import Router
from litellm.types.router import RequestType

from _mock import LIVE

SESSIONS, BLOCK = 60, 10
TIER_2 = {"adaptive_router_preferences": {"quality_tier": 2}}
ANSWERS = ["Here is a first draft.", "Revised version with details below.", "Glad to help."]


def build_router():
    """Return a Router whose 'auto' group chooses between two equally rated models."""
    return Router(model_list=[
        {"model_name": "solid", "litellm_params": {"model": "openai/solid-llm"}, "model_info": TIER_2},
        {"model_name": "flaky", "litellm_params": {"model": "openai/flaky-llm"}, "model_info": TIER_2},
        {"model_name": "auto", "litellm_params": {
            "model": "auto_router/adaptive_router",
            "adaptive_router_config": {"available_models": ["solid", "flaky"]}}},
    ])


def user_reply(turn, previous_model):
    """Simulated user: gives up on flaky answers, thanks solid ones."""
    if previous_model == "flaky-llm":
        return "Wrong. Forget it."
    return "Go on." if turn == 2 else "Thanks, perfect!"


async def run_session(router, session_id):
    """Play one three-turn conversation; return the model that answered the first turn."""
    messages = [{"role": "user", "content": "Tell me about tides."}]
    first = None
    for turn, answer in enumerate(ANSWERS, start=1):
        resp = await router.acompletion(model="auto", messages=messages, mock_response=answer,
                                        litellm_session_id=session_id)
        await asyncio.sleep(0.05)
        first = first or resp.model
        messages += [{"role": "assistant", "content": answer},
                     {"role": "user", "content": user_reply(turn + 1, resp.model)}]
    return first


async def main():
    if LIVE:
        raise SystemExit("this demo uses made-up models and only runs offline")
    random.seed(7)
    router = build_router()
    bandit = router.registry().plugins("adaptive")["auto"][0].strategy
    for start in range(0, SESSIONS, BLOCK):
        picks = Counter([await run_session(router, f"s{i}") for i in range(start, start + BLOCK)])
        print(f"sessions {start + 1:>2}-{start + BLOCK:<2} first-turn picks: {dict(sorted(picks.items()))}")
    for name in ("solid", "flaky"):
        cell = bandit.cell(RequestType.GENERAL, name)
        print(f"{name:5} Beta(alpha={cell.alpha:g}, beta={cell.beta:g})  mean={cell.mean:.2f}")


asyncio.run(main())
```

```text
sessions  1-10 first-turn picks: {'flaky-llm': 2, 'solid-llm': 8}
sessions 11-20 first-turn picks: {'solid-llm': 10}
sessions 21-30 first-turn picks: {'solid-llm': 10}
sessions 31-40 first-turn picks: {'solid-llm': 10}
sessions 41-50 first-turn picks: {'solid-llm': 10}
sessions 51-60 first-turn picks: {'solid-llm': 10}
solid Beta(alpha=64, beta=5)  mean=0.93
flaky Beta(alpha=5, beta=8)  mean=0.38
```

What to notice:

- **It learned within ten sessions.** After the first block, `flaky` never answered a first turn again. `solid` went from its starting score of Beta(5, 5) to Beta(64, 5).
- **The starting scores come from `adaptive_router_preferences`.** A `quality_tier` of 1, 2 or 3 gives a mean of 0.3, 0.5 or 0.7, plus 0.3 for each request type listed in `strengths` (capped at 0.95), weighted as if from 10 calls. Exercise 14d.1 checks this.
- **Pass `litellm_session_id`.** Without a session ID, conversations with fewer than four messages are not learned from.
- **Only conversation text teaches it.** Provider errors such as a 429 leave the scores unchanged (exercise 14d.2), and there is no API for explicit feedback.
- **The signals are word-overlap heuristics.** In my first draft, the replies "That is wrong. Forget it." and "Thanks, that worked!" shared the word "that", which counted as a rephrase and blamed the wrong model. Identical replies on consecutive turns count as stagnation, so a test that mocks the same text twice blames that model.
- **Recording happens in the background logging worker.** Without the short `asyncio.sleep` between turns, the next call can run before the last turn is recorded, and the results change.
- What it learns is kept in memory per process. The proxy saves it to Postgres every 10 seconds, reloads it at startup, and shows it at the admin endpoint `GET /adaptive_router/state`.

#### Exercises

**14d.1 ★ `ex14d_1_cold_start.py`: starting scores and weights**

Give an adaptive router three candidates: `fast` (`_env.FAST`, tier 1, `input_cost_per_token` 1e-6), `alt` (`_env.ALT`, tier 2, 0.3e-6) and `smart` (`_env.SMART`, tier 3, 5e-6, `strengths: ["analytical_reasoning"]`). Before sending anything, print the Beta scores of each model for the `general` and `analytical_reasoning` request types. Then send "What is the probability of rolling two sixes with two dice?" 200 times offline (40 live) with weights quality 0.9 and cost 0.1, and again with quality 0.1 and cost 0.9, counting which model answered.

Checks:
- Every starting score has `alpha + beta == 10`; `fast` on `general` has mean 0.3, and `smart` on `analytical_reasoning` has mean 0.95.
- `classify_prompt(PROMPT)` (from `litellm.router_strategy.adaptive_router.classifier`) is `RequestType.ANALYTICAL_REASONING`.
- With quality first, `smart` answers most calls; with cost first, `alt` does.

<details><summary>Hint</summary>

`router.registry().plugins("adaptive")["auto"][0].strategy.cell(RequestType.GENERAL, "fast")` returns a score with `alpha`, `beta` and `mean`. Single calls with no session ID teach the router nothing, so these counts depend only on the starting scores. The classifier is narrow: "Analyze the pros and cons..." counts as `general`, while "probability" or "suppose" counts as analytical reasoning. Call `random.seed()` for repeatable offline counts.
</details>

**14d.2 ★★ `ex14d_2_learn_from_feedback.py`: it learns from users, not from errors**

Two tier-2 candidates, `fast` and `alt`. Run 40 three-turn sessions offline (6 live), each with its own `litellm_session_id`. The simulated user replies "Wrong. Forget it." after an answer from `_env.ALT`, otherwise "Go on." on turn 2 and "Thanks, perfect!" on turn 3. Then send five calls offline that fail with `mock_response=litellm.RateLimitError(...)`.

Checks:
- `fast`'s `general` alpha and `alt`'s `general` beta have both grown past their starting value of 5.
- Offline: `fast` answers the first turn of at least 9 of the last 10 sessions.
- Offline: the five rate-limit errors leave all four numbers unchanged.

<details><summary>Hint</summary>

Give each turn a different mocked answer, or the identical replies count as stagnation. `await asyncio.sleep(0.05)` after each call lets the background recorder catch up. Pass `num_retries=0` with the error mock so the router doesn't retry.
</details>

## 15. The MCP gateway: one endpoint for every tool server

**Use case:** your agents and apps use several MCP tool servers. Put them behind the proxy, so clients connect to one endpoint with their LiteLLM key, each key sees only the servers and tools it is allowed, and every tool call is logged and priced.

The [Model Context Protocol](https://modelcontextprotocol.io) (MCP) is the standard way to expose tools to LLM clients. The proxy's MCP gateway:

- **Registers servers in config.** The top-level `mcp_servers:` key lists them by name, with `transport: http` (the default), `sse` or `stdio`.
- **Serves them at `/mcp`.** Any MCP client connects there with a LiteLLM key in the `x-litellm-api-key` header (or `Authorization`). `/<server>/mcp` serves one server, and `/catalog,mathbox/mcp` a chosen set.
- **Prefixes tool names** with the server name: `catalog-lookup_price`. The separator is `-`, so server names may not contain one.
- **Controls access per key and team.** A key's `object_permission` lists its `mcp_servers` and, optionally, `mcp_tool_permissions` per server.
- **Prices tool calls** from `mcp_info.mcp_server_cost_info`, and logs each one as its own `call_mcp_tool` event.
- **Runs MCP tools inside chat completions** sent to the proxy, with `tools=[{"type": "mcp", "server_url": "litellm_proxy/mcp/<server>"}]`.

None of this needs a licence. Authenticating MCP clients to the gateway with JWTs or OAuth2 tokens, instead of LiteLLM keys, does.

The examples live in [`examples/mcp/`](examples/mcp/): two tiny MCP servers, a proxy config, a callback that prints costs, and three clients. The `mcp` package installed with the proxy is SDK version 2: its server class is `MCPServer` (there is no `FastMCP`), and results use snake_case fields such as `is_error`.

```bash
cd examples/mcp
uv run python catalog_server.py http &                 # HTTP MCP server on port 4111
export LITELLM_MASTER_KEY=sk-master-demo OPENAI_API_KEY=unused LITELLM_LOCAL_MODEL_COST_MAP=True
export LITELLM_ENABLE_MCP_STDIO=true                   # stdio servers are off without this
uv run litellm --config mcp_config.yaml --port 4000    # run from this folder: it starts math_server.py
```

```bash
# in another shell, same folder and the same exports
uv run python 15a_list_and_call.py
uv run python 15b_chat_with_mcp.py
```

15a and 15b need no database. 15c creates keys, so it does: start section 13's Postgres (`docker start litellm-tutorial-db`), stop the proxy, `export DATABASE_URL=postgresql://postgres:demo@localhost:55432/litellm` in the proxy's shell, start the proxy again, and then run `uv run python 15c_mcp_keys.py`. When you finish the section, stop the proxy and the catalog server (`kill %1`).

[`catalog_server.py`](examples/mcp/catalog_server.py) (`math_server.py` is the same with `add` and `multiply`)

```python
"""A tiny MCP server with two shop tools, served over HTTP or stdio."""
import sys

from mcp.server.mcpserver import MCPServer

PRICES = {"apple": 0.5, "pear": 0.8}

mcp = MCPServer("catalog")


@mcp.tool()
def lookup_price(sku: str) -> float:
    """Return the unit price of a product in dollars."""
    return PRICES[sku]


@mcp.tool()
def in_stock(sku: str, quantity: int = 1) -> bool:
    """Say whether at least `quantity` units of a product are available."""
    return sku in PRICES and quantity <= 10


if __name__ == "__main__":
    if sys.argv[1:] == ["http"]:
        mcp.run("streamable-http", host="127.0.0.1", port=4111)
    else:
        mcp.run()
```

[`mcp_config.yaml`](examples/mcp/mcp_config.yaml)

```yaml
model_list:
  - model_name: chat
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY
      mock_response: "An apple costs $0.50."   # delete for real calls
  - model_name: chat-tools                    # same model, but the mock first "calls" a tool
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY
      mock_response: "An apple costs $0.50."
      mock_tool_calls:                        # delete for real calls
        - id: call_1
          type: function
          function: {name: catalog-lookup_price, arguments: '{"sku": "apple"}'}

mcp_servers:
  catalog:
    url: http://127.0.0.1:4111/mcp
    transport: http
    description: Product prices and stock
    mcp_info:
      mcp_server_cost_info:
        default_cost_per_query: 0.001
        tool_name_to_cost_per_query:
          lookup_price: 0.01
  mathbox:
    transport: stdio                          # needs LITELLM_ENABLE_MCP_STDIO=true
    command: python
    args: ["math_server.py"]

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY

litellm_settings:
  callbacks: cost_logger.proxy_handler_instance
```

[`_gateway.py`](examples/mcp/_gateway.py), the connection helper the three clients share

```python
"""Connect the official MCP client to the LiteLLM gateway with a LiteLLM key."""
import os

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

GATEWAY = os.environ.get("GATEWAY", "http://localhost:4000/mcp")


def connect(key, url=GATEWAY, **headers):
    """Return an MCP client that authenticates to the gateway with a LiteLLM key."""
    http = httpx2.AsyncClient(headers={"x-litellm-api-key": f"Bearer {key}", **headers})
    return Client(streamable_http_client(url, http_client=http))
```

[`15a_list_and_call.py`](examples/mcp/15a_list_and_call.py)

```python
"""List and call MCP tools through the LiteLLM gateway with the official MCP client."""
import asyncio
import os

from _gateway import connect


async def main():
    async with connect(os.environ["LITELLM_MASTER_KEY"]) as client:
        tools = (await client.list_tools()).tools
        print("server :", client.server_info.name)
        print("tools  :", sorted(t.name for t in tools))
        for name, args in [("catalog-lookup_price", {"sku": "apple"}),
                           ("mathbox-multiply", {"a": 6, "b": 7})]:
            result = await client.call_tool(name, args)
            print(f"{name}({args}) -> {result.content[0].text}  is_error={result.is_error}")


if __name__ == "__main__":
    asyncio.run(main())
```

```text
server : litellm-mcp-server
tools  : ['catalog-in_stock', 'catalog-lookup_price', 'mathbox-add', 'mathbox-multiply']
catalog-lookup_price({'sku': 'apple'}) -> 0.5  is_error=False
mathbox-multiply({'a': 6, 'b': 7}) -> 42  is_error=False
```

The client sees one MCP server, `litellm-mcp-server`, holding the tools of both upstream servers, each prefixed with its server name. The proxy's [`cost_logger.py`](examples/mcp/cost_logger.py) callback printed one event per MCP operation, priced from `mcp_server_cost_info`:

```text
[cost] list_mcp_tools  MCP: list_tools              $0.0
[cost] call_mcp_tool   MCP: catalog-lookup_price    $0.01
[cost] call_mcp_tool   MCP: mathbox-multiply        $0.0
```

**MCP tools inside a chat completion.** [`15b_chat_with_mcp.py`](examples/mcp/15b_chat_with_mcp.py) sends an ordinary OpenAI request whose `tools` entry points at the gateway:

```python
"""Let the proxy run an MCP tool during a chat completion, with a mocked model."""
import os

from openai import OpenAI

client = OpenAI(base_url="http://localhost:4000", api_key=os.environ["LITELLM_MASTER_KEY"])

resp = client.chat.completions.create(
    model="chat-tools",
    messages=[{"role": "user", "content": "How much is an apple?"}],
    tools=[{"type": "mcp", "server_url": "litellm_proxy/mcp/catalog", "require_approval": "never"}],
)
msg = resp.choices[0].message
meta = msg.model_extra.get("provider_specific_fields") or {}
print("answer     :", msg.content)
print("tools sent :", [t["function"]["name"] for t in meta.get("mcp_list_tools", [])])
print("tool calls :", [c["function"]["name"] for c in meta.get("mcp_tool_calls", [])])
print("results    :", meta.get("mcp_call_results"))
```

```text
answer     : An apple costs $0.50.
tools sent : ['catalog-lookup_price', 'catalog-in_stock']
tool calls : ['catalog-lookup_price']
results    : [{'tool_call_id': 'call_1', 'result': '0.5', 'name': 'catalog-lookup_price'}]
```

The proxy listed the catalog's tools, sent them to the model, ran the tool call the model made against the real MCP server, and called the model again with the result. The `chat-tools` deployment fakes the model's tool call with `mock_tool_calls` in its config. The mock has to go there: by default the proxy strips `mock_response` and `mock_tool_calls` from client requests. Setting `allow_client_mock_response: true` in the key's or the team's metadata lifts that.

**Access per key.** [`15c_mcp_keys.py`](examples/mcp/15c_mcp_keys.py) needs the database. It creates three keys with different `object_permission` values and lists what each one sees:

```python
"""Give virtual keys different MCP servers and tools, then list what each key sees."""
import asyncio
import os
import time

import httpx

from _gateway import connect

PROXY = "http://localhost:4000"
ADMIN = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
SCOPES = {
    "no-scope": None,
    "catalog-only": {"mcp_servers": ["catalog"]},
    "price-tool-only": {"mcp_servers": ["catalog"], "mcp_tool_permissions": {"catalog": ["lookup_price"]}},
}


def make_key(alias, permission):
    """Create a virtual key with an optional MCP object permission."""
    body = {"key_alias": f"{alias}-{int(time.time())}", "object_permission": permission}
    r = httpx.post(f"{PROXY}/key/generate", headers=ADMIN, json=body)
    r.raise_for_status()
    return r.json()["key"]


async def visible_tools(key):
    """Return the tool names the gateway lists for a key."""
    try:
        async with connect(key) as client:
            return sorted(t.name for t in (await client.list_tools()).tools)
    except ExceptionGroup:
        return "refused (HTTP 403 on initialize)"


async def main():
    for alias, permission in SCOPES.items():
        key = make_key(alias, permission)
        print(f"{alias:16} {await visible_tools(key)}")
    key = make_key("price-call", SCOPES["price-tool-only"])
    async with connect(key) as client:
        result = await client.call_tool("catalog-in_stock", {"sku": "apple"})
        print("call in_stock   :", result.is_error, result.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())
```

```text
no-scope         refused (HTTP 403 on initialize)
catalog-only     ['catalog-in_stock', 'catalog-lookup_price']
price-tool-only  ['catalog-lookup_price']
call in_stock   : True Error: Tool 'in_stock' is not allowed for your key/team on server 'catalog'. Contact proxy admin for access.
```

What to notice:

- **stdio servers need `LITELLM_ENABLE_MCP_STDIO=true`.** Without it, the proxy logs a warning at startup, the server's tools are missing from the list, and calling one returns an error result.
- **A key with no MCP grant and no team is refused**, unless a server sets `allow_all_keys: true`. That is the case 15c shows. A key in a team inherits the team's grant when it has none of its own, and when both have a list the two are intersected. `general_settings.require_key_mcp_access_defined: true` turns the inheritance off, so every key needs its own grant. The master key sees everything.
- **Tool errors are results, not exceptions.** An unknown or forbidden tool comes back with `is_error=True` and a message, so an agent can read it and recover.
- **Tools run automatically only with `require_approval: "never"`** on every MCP entry. Without it, the reply carries the model's `tool_calls` and nothing runs. Both model rounds are billed; the tool's own price is a separate log event.
- **Upstream credentials** are set per server with `auth_type` (`bearer_token`, `api_key`, `oauth2` and others) or `static_headers`. Clients can pass their own as `x-mcp-<server>-<header>`, for example `x-mcp-github-authorization`. I only read this part in the source; the demo servers need no credentials.
- In the SDK, `litellm.mcp_client.load_mcp_tools(session, format="openai")` and `call_openai_tool(session, tool_call)` convert an MCP session's tools to OpenAI format and run a tool call. `litellm.experimental_mcp_client` is a deprecated alias.

### Exercises

**15.1 ★ `shop_server.py`, `mcp_proxy_config.yaml` and `ex15_1_gateway_tools.py`: your own MCP gateway**

Write an MCP server `shop` with two tools, `price(item)` and `stock(item)`, using `MCPServer` from `mcp.server.mcpserver`. Register it over stdio in a proxy config with a `fast` model group (`bedrock/us.anthropic.claude-haiku-5-5` with a `mock_response`), and start the proxy from `exercises/` with `LITELLM_ENABLE_MCP_STDIO=true`. Then, with the `mcp` client and the master key: list the tools on `/mcp`, call `shop-price` for `notebook`, call a tool that doesn't exist, and connect to `/shop/mcp` and call `shop-stock` for `pen`.

Checks:
- The tool names are exactly `["shop-price", "shop-stock"]`.
- `shop-price` returns `3.0`, and the made-up tool comes back with `is_error` true instead of raising.
- The per-server endpoint `/shop/mcp` works and returns `"0"` for `pen`.

<details><summary>Hint</summary>

Copy `_gateway.py` from the example and point it at port 4000. Without `LITELLM_ENABLE_MCP_STDIO=true` in the proxy's shell, the shop's tools are simply missing from the list. The stdio `command` runs in the proxy's working directory, so start the proxy from the folder that holds `shop_server.py`.
</details>

**15.2 ★★ `ex15_2_mcp_in_chat.py`: MCP tools inside a chat completion**

Add a `fast-tools` deployment to your config whose `mock_tool_calls` calls `shop-price` with `{"item": "notebook"}`. Using only the `openai` package, send the same question to `fast-tools` twice with `tools=[{"type": "mcp", "server_url": "litellm_proxy/mcp/shop", ...}]`: once with `require_approval: "never"` and once without it. Read `provider_specific_fields` on the message and the `x-litellm-response-cost` header (use `with_raw_response`).

Checks:
- With `"never"`, `mcp_call_results` contains the tool's real result `"3.0"`.
- Without it, the reply has `tool_calls` and no `mcp_call_results`.
- Offline: the auto-run request costs exactly twice the other one, because both model rounds are billed.

<details><summary>Hint</summary>

The fake tool call has to live in the deployment's `litellm_params`; the proxy strips mocks from request bodies. The tool name in it must be the prefixed name, `shop-price`.
</details>

## 16. The skills and agent gateways: share skills and agents through the proxy

Besides models (sections 12–14) and MCP tool servers (section 15), the proxy can host two more things agents use: **skills**, folders of instructions that any model can be given (16a), and **agents themselves**, reached over the A2A protocol with the same keys, limits and spend tracking as models (16b).

| | 16a. Skills gateway | 16b. Agent gateway |
| --- | --- | --- |
| What it serves | `SKILL.md` folders, stored by Anthropic or in the proxy's database | A2A agents running anywhere, or any model presented as an agent |
| Routes | `/v1/skills`, `/.well-known/agent-skills/index.json` | `/v1/agents`, `/a2a/<agent>`, `/a2a/<agent>/.well-known/agent-card.json` |
| SDK | `litellm.create_skill`, `list_skills`, ... | `litellm.a2a_protocol`, `completion(model="a2a/...")` |
| Access | Each skill belongs to its creator | Keys and teams list the agent IDs they may call |

### 16a. Skills gateway

A note on names: the current docs use "Skills Gateway" for the Skills Hub (`/skill-hub/...`), a catalog with publishing, admin review and version history that 1.110.0 added. This subsection covers the `/v1/skills` API, which the docs describe on their Skills page and which 1.110.2 still ships; the Skills Hub is not covered here.

**Use case:** your team writes [agent skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview), folders with a `SKILL.md` of instructions plus optional files. You want to store them once and attach them to requests for any model, or publish them for tools to download.

LiteLLM has two skill backends behind one API:

| | Anthropic Skills API | Skills hosted by the proxy |
| --- | --- | --- |
| Where skills live | Your Anthropic account | The proxy's Postgres (`LiteLLM_SkillsTable`) |
| IDs | Anthropic's, e.g. `skill_01...` | `litellm_skill_<uuid>` |
| How a request uses one | `container={"skills": [...]}` is passed to Anthropic, which runs it | The proxy puts `SKILL.md` into the system prompt and adds a tool per skill, for any model |
| Select it with | `custom_llm_provider="anthropic"` (the default) | `custom_llm_provider="litellm_proxy"` |

The SDK has `litellm.create_skill`, `list_skills`, `get_skill` and `delete_skill` (and `a...` versions); the proxy serves the same operations at `/v1/skills`. Anthropic is the only external provider. Nothing here is licensed.

**The Anthropic backend from the SDK.** [`16a_skills_sdk.py`](examples/16a_skills_sdk.py) runs against [`_fake_upstream.py`](examples/_fake_upstream.py), a local fake of Anthropic's API that records each request, so it needs no key and no network:

```python
"""Anthropic Skills through the LiteLLM SDK, against a local fake of Anthropic's API."""
import io
import json
import threading
import zipfile
from http.server import ThreadingHTTPServer

import httpx
import litellm

from _fake_upstream import Handler



def skill_zip(name, description, body):
    """Return a zip holding <name>/SKILL.md, the layout the Anthropic Skills API uses."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{name}/SKILL.md", f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n")
    return buf.getvalue()


def show_last_request():
    """Print the method, path and Anthropic headers of the newest upstream request."""
    req = httpx.get(f"{FAKE}/_seen").json()[-1]
    print(f"   -> {req['method']} {req['path']}  anthropic-beta={req['headers'].get('anthropic-beta')}")
    return req


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
FAKE = f"http://127.0.0.1:{server.server_port}"
AUTH = {"api_key": "sk-ant-fake", "api_base": FAKE}

data = skill_zip("release-notes", "Turn merged PRs into release notes.", "Group under Added, Changed, Fixed.")
skill = litellm.create_skill(display_title="Release notes",
                             files=[("release-notes.zip", data, "application/zip")], **AUTH)
print("create:", skill.id, skill.display_title)
body = show_last_request()["body"]
print("   form fields:", [line.split("; ")[1] for line in body.splitlines() if line.startswith("Content-Disposition")])

page = litellm.list_skills(limit=10, source="custom", **AUTH)
print("list  :", [s.id for s in page.data])
show_last_request()

print("get   :", litellm.get_skill(skill_id=skill.id, **AUTH).display_title)
show_last_request()

resp = litellm.completion(
    model="anthropic/claude-sonnet-5-5",
    messages=[{"role": "user", "content": "Release notes for PR #12"}],
    container={"skills": [{"type": "custom", "skill_id": skill.id, "version": "latest"}]},
    tools=[{"type": "code_execution_20250825", "name": "code_execution"}],
    **AUTH,
)
print("chat  :", resp.choices[0].message.content)
sent = json.loads(show_last_request()["body"])
print("   container:", sent["container"])

print("delete:", litellm.delete_skill(skill_id=skill.id, **AUTH).type)
show_last_request()

try:
    litellm.list_skills(custom_llm_provider="openai")
except Exception as e:
    print("openai:", type(e).__name__, str(e).split(" - ")[-1])
server.shutdown()
```

```text
create: skill_001 Release notes
   -> POST /v1/skills  anthropic-beta=skills-2025-10-02
   form fields: ['name="display_title"', 'name="files[]"']
list  : ['skill_001']
   -> GET /v1/skills?limit=10&source=custom  anthropic-beta=skills-2025-10-02
get   : Release notes
   -> GET /v1/skills/skill_001  anthropic-beta=skills-2025-10-02
chat  : fake Anthropic reply
   -> POST /v1/messages  anthropic-beta=code-execution-2025-08-25,skills-2025-10-02
   container: {'skills': [{'type': 'custom', 'skill_id': 'skill_001', 'version': 'latest'}]}
delete: skill_deleted
   -> DELETE /v1/skills/skill_001  anthropic-beta=skills-2025-10-02
openai: APIConnectionError LIST skills is not supported for openai
```

LiteLLM adds the `skills-2025-10-02` beta header to every skills call, and the code-execution beta when the request has that tool.

**Skills hosted by the proxy.** These need the database from section 13. [`proxy/skills_config.yaml`](examples/proxy/skills_config.yaml) points three model groups at the fake upstream, turns on the public index and names an embedding model for search:

```yaml
# Section 16: skills hosted on the proxy. Needs DATABASE_URL (section 13) and _fake_upstream.py on port 4011.
model_list:
  - model_name: gpt
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: fake
      api_base: http://127.0.0.1:4011/v1
  - model_name: claude
    litellm_params:
      model: anthropic/claude-sonnet-5-5
      api_key: fake
      api_base: http://127.0.0.1:4011
  - model_name: embed
    litellm_params:
      model: openai/text-embedding-3-small
      api_key: fake
      api_base: http://127.0.0.1:4011/v1

litellm_settings:
  public_skills_index: true             # serve /.well-known/agent-skills/index.json
  skill_search_embedding_model: embed   # enables GET /v1/skills?query=

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

```bash
cd examples
uv run python _fake_upstream.py 4011 &
export DATABASE_URL=postgresql://postgres:demo@localhost:55432/litellm LITELLM_MASTER_KEY=sk-master-demo LITELLM_LOCAL_MODEL_COST_MAP=True
uv run litellm --config proxy/skills_config.yaml --port 4000
uv run python 16a_skills_proxy.py        # in another shell, same exports
```

[`16a_skills_proxy.py`](examples/16a_skills_proxy.py)

```python
"""Host skills on the LiteLLM proxy, attach them to requests, search them and publish them."""
import io
import json
import os
import time
import zipfile

import httpx

PROXY = "http://localhost:4000"
UPSTREAM = "http://127.0.0.1:4011"
ADMIN = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
HOSTED = {"custom_llm_provider": "litellm_proxy"}
SKILLS = {
    "release-notes": ("Turn a list of merged pull requests into user-facing release notes.",
                      "Group changes under Added, Changed and Fixed. One line per change, past tense."),
    "sql-review": ("Review a SQL migration for locking and rollback problems.",
                   "Flag ALTER TABLE on large tables, missing indexes and irreversible steps."),
}


def skill_zip(name, description, body):
    """Return a zip holding <name>/SKILL.md, the layout the Anthropic Skills API uses."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{name}/SKILL.md", f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n")
    return buf.getvalue()


def last_upstream_body(path):
    """Return the JSON body of the newest request the fake upstream got on path."""
    seen = httpx.get(f"{UPSTREAM}/_seen").json()
    return json.loads(next(r for r in reversed(seen) if r["path"].startswith(path))["body"])


with httpx.Client(base_url=PROXY, headers=ADMIN, timeout=30) as http:
    print("== 1. upload two skills to the proxy's database")
    ids = {}
    for name, (description, body) in SKILLS.items():
        r = http.post("/v1/skills", params=HOSTED, data={"display_title": name, "description": description},
                      files={"files[]": (f"{name}.zip", skill_zip(name, description, body), "application/zip")})
        ids[name] = r.json()["id"]
        print(f"{name:14} -> {ids[name]}")

    print("== 2. list them")
    listed = http.get("/v1/skills", params=HOSTED).json()["data"]
    print([s["display_title"] for s in listed])

    print("== 3. chat completion with container.skills, model behind it is OpenAI-style")
    skills = [{"type": "custom", "skill_id": ids["release-notes"]}]
    http.post("/v1/chat/completions", json={
        "model": "gpt", "messages": [{"role": "user", "content": "Notes for PR #12"}],
        "container": {"skills": skills}})
    sent = last_upstream_body("/v1/chat/completions")
    print("system :", sent["messages"][0]["content"][:70].replace("\n", " | "))
    print("tools  :", [t["name"] for t in sent["tools"]])
    print("tool keys:", sorted(sent["tools"][0]))
    print("container forwarded:", "container" in sent)

    print("== 4. /v1/messages with the same skill, model behind it is Anthropic")
    r = http.post("/v1/messages", json={
        "model": "claude", "max_tokens": 200, "messages": [{"role": "user", "content": "Notes for PR #12"}],
        "container": {"skills": skills}})
    sent = last_upstream_body("/v1/messages")
    print("reply  :", r.json()["content"][0]["text"])
    print("system :", sent["system"][:70].replace("\n", " | "))
    print("tools  :", [t["name"] for t in sent["tools"]])
    print("container forwarded:", "container" in sent)

    print("== 5. semantic search over the hosted skills")
    found = http.get("/v1/skills", params={**HOSTED, "query": "review my SQL migration", "top_k": 2}).json()
    for s in found["data"]:
        print(f"{s['display_title']:14} score={s['search_score']:.3f}")

    print("== 6. public Agent Skills discovery index (no credentials)")
    index = httpx.get(f"{PROXY}/.well-known/agent-skills/index.json").json()
    entry = index["skills"][0]
    print(index["$schema"])
    print({k: entry[k] for k in ("name", "type", "url")}, entry["digest"][:20] + "...")
    archive = httpx.get(entry["url"])
    print("archive files:", zipfile.ZipFile(io.BytesIO(archive.content)).namelist())

    print("== 7. a key for another user cannot see these skills")
    key = http.post("/key/generate", json={"user_id": f"alice-{int(time.time())}"}).json()["key"]
    other = {"Authorization": f"Bearer {key}"}
    print("alice lists:", http.get("/v1/skills", params=HOSTED, headers=other).json()["data"])
    r = http.get(f"/v1/skills/{ids['sql-review']}", params=HOSTED, headers=other)
    print("alice gets :", r.status_code, r.json()["error"]["message"])

    print("== 8. delete them")
    for skill_id in ids.values():
        print(http.delete(f"/v1/skills/{skill_id}", params=HOSTED).json())
```

```text
== 1. upload two skills to the proxy's database
release-notes  -> litellm_skill_8743452f-a835-4b46-8659-1989bf77c14a
sql-review     -> litellm_skill_1b446782-8c56-4ac2-baa8-394aa375f97d
== 2. list them
['sql-review', 'release-notes']
== 3. chat completion with container.skills, model behind it is OpenAI-style
system : --- |  | # Available Skills |  | ## Skill: release-notes |  | --- | name: release-no
tools  : ['litellm_skill_8743452f_a835_4b46_8659_1989bf77c14a', 'litellm_code_execution']
tool keys: ['description', 'input_schema', 'name']
container forwarded: False
== 4. /v1/messages with the same skill, model behind it is Anthropic
reply  : fake Anthropic reply
system : --- |  | # Available Skills |  | ## Skill: release-notes |  | --- | name: release-no
tools  : ['litellm_skill_8743452f_a835_4b46_8659_1989bf77c14a', 'litellm_code_execution']
container forwarded: False
== 5. semantic search over the hosted skills
sql-review     score=0.645
release-notes  score=0.196
== 6. public Agent Skills discovery index (no credentials)
https://schemas.agentskills.io/discovery/0.2.0/schema.json
{'name': 'release-notes', 'type': 'archive', 'url': 'http://localhost:4000/v1/skills/litellm_skill_8743452f-a835-4b46-8659-1989bf77c14a/archive'} sha256:b06eb579ca4eb...
archive files: ['SKILL.md']
== 7. a key for another user cannot see these skills
alice lists: []
alice gets : 500 litellm.APIConnectionError: APIConnectionError: Litellm_proxyException - Skill not found: litellm_skill_1b446782-8c56-4ac2-baa8-394aa375f97d
== 8. delete them
{'id': 'litellm_skill_8743452f-a835-4b46-8659-1989bf77c14a', 'type': 'skill_deleted'}
{'id': 'litellm_skill_1b446782-8c56-4ac2-baa8-394aa375f97d', 'type': 'skill_deleted'}
```

What to notice:

- **Without `custom_llm_provider=litellm_proxy`, `/v1/skills` goes to Anthropic.** With no Anthropic key, that is a 500: `ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN is required for Skills API`.
- **A hosted skill becomes prompt text and a tool.** The proxy's `litellm_skills` hook adds `# Available Skills` and the `SKILL.md` text to the system prompt (or the `system` field on `/v1/messages`), adds one tool per skill, and removes `container` before the request leaves. It also adds a `litellm_code_execution` tool for every hosted skill, because `SKILL.md` itself counts as a file; running that code needs the `llm-sandbox` package and Docker, which this project doesn't install.
- **Known problems in 1.110.2.** The hook always builds Anthropic-shaped tools (`name`, `description`, `input_schema`), even for an OpenAI-style model, which a real OpenAI endpoint may reject; I didn't test that live. A request that mixes hosted and Anthropic-native skills loses the native ones, because `container` is removed. An unknown hosted skill ID is skipped with only a log warning.
- **Ownership, not allowlists.** Each skill belongs to its creator (user, else team, org or key). Others can't list it, and fetching it gives a 500 `Skill not found`, the same as a missing ID. Proxy admins see everything.
- **The public index is unauthenticated and lists every user's skills.** `/.well-known/agent-skills/index.json` returns 404 until `public_skills_index: true` is set. Archives are repacked with `SKILL.md` at the root and fixed timestamps, so the `sha256:` digest is the same on every run.
- **Search** (`?query=`) works only on hosted skills, and needs `skill_search_embedding_model`. It embeds each skill's title, description and instructions.

#### Exercises

**16a.1 ★ `ex16a_1_skill_prompt.py`: what a hosted skill becomes on the wire**

Build a skill zip in memory holding `haiku-writer/SKILL.md` (front matter `name` and `description`, and a body asking for three lines of 5, 7 and 5 syllables). Wrap it in `LiteLLM_SkillsTable(skill_id="litellm_skill_demo-haiku", display_title="Haiku writer", description="Answer as a haiku", file_content=<zip bytes>)` from `litellm.models.skills`. Use `SkillPromptInjectionHandler` from `litellm.proxy.hooks.litellm_skills` to get the skill text, the tool definition and the messages with the skill injected, which is what the proxy does for every request with `container.skills`. Send those messages to `_env.FAST`.

Checks:
- The first message has `role == "system"` and starts with `"---\n\n# Available Skills\n\n## Skill: Haiku writer"`, followed by the `SKILL.md` body.
- The tool name is the skill ID with `-` replaced by `_` (`litellm_skill_demo_haiku`), and its description is the skill's `description`.
- Offline, the reply has three lines.

<details><summary>Hint</summary>

Call `extract_skill_content`, then `convert_skill_to_tool`, then `inject_skill_content_to_messages(data, [content])`. `convert_skill_to_tool` returns the OpenAI shape, so the name is at `tool["function"]["name"]`; on `/v1/messages` the hook uses `convert_skill_to_anthropic_tool` instead. The source is `llms/litellm_proxy/skills/prompt_injection.py`. No database is involved.
</details>

**16a.2 ★★ `ex16a_2_skill_registry.py`: host, isolate and publish a skill**

With section 13's database, start a proxy from `exercises/` whose config has a `fast` model group (`bedrock/us.anthropic.claude-haiku-5-5`, `mock_response: "Hi from fast (mock)"`) and `litellm_settings.public_skills_index: true`. Build a zip with `pr-summary/SKILL.md` (front matter `name: pr-summary`) and `pr-summary/templates/summary.md`, and upload it twice with `?custom_llm_provider=litellm_proxy`. Read the public index without credentials and download one archive. Create a key for a new user `bob` and try to list and fetch the skills with it. Send a chat request to `fast` with `container.skills`, then delete both skills.

Checks:
- The two index entries are named `pr-summary` and `pr-summary-2`, their digest equals `build_skill_archive(<your zip>).digest` computed locally, and the archive holds `["SKILL.md", "templates/summary.md"]`.
- Bob's list doesn't include your skills, and his fetch is refused (record the status code in a comment).
- The chat request returns 200, and after the deletes your skills are gone from the index.

<details><summary>Hint</summary>

`build_skill_archive` is in `litellm.proxy.discovery_endpoints.agent_skills_archive`. Filter the index by URLs ending in `/<id>/archive`, because it lists every user's skills. In 1.110.2 Bob's fetch is a 500, not a 404.
</details>

**Clean up.** Stop the proxy with Ctrl-C. The fake upstream on port 4011 is used again in 16b, so leave it running, or stop it with `kill %1` and start it again there.

### 16b. Agent gateway (A2A)

**Use case:** teams build agents with different frameworks: LangGraph, Pydantic AI, Bedrock AgentCore, or plain HTTP services. You want clients to find them all in one place, one set of keys deciding who may call which agent, and one spend log. The proxy already does this for models (section 13) and MCP servers (section 15).

Agents talk to each other over [A2A (Agent2Agent)](https://a2a-protocol.org/), which is JSON-RPC 2.0 over HTTP. The parts this section uses:

| Piece | What it is |
| --- | --- |
| `GET <agent>/.well-known/agent-card.json` | The **agent card**: name, description, URL, capabilities (such as `streaming`) and skills with tags. Clients read it to decide what an agent can do and where to send requests. |
| `message/send` | One request, one reply. The reply is a `message` (or a `task`), whose `parts` hold text, files or data. |
| `message/stream` | The same request answered as server-sent events: a `task`, then `artifact-update` chunks, then a final `status-update`. |
| `tasks/get`, `tasks/cancel`, `tasks/resubscribe`, push-notification methods | Work with long-running tasks. The proxy forwards these to the agent unchanged. |

What the proxy adds on top of A2A:

| Feature | How it works | Where it is set |
| --- | --- | --- |
| Registry | Agents from the config, plus agents added at runtime with `POST /v1/agents` (stored in Postgres). `GET /v1/agents` lists only the agents the caller's key may use. | `agents:` in the config, or `/v1/agents` |
| One URL per agent | `POST /a2a/<name or id>` takes JSON-RPC. `/a2a/<id>/message/send` and `/a2a/<id>/message/stream` also work, with or without a `/v1` prefix. The card served at `/a2a/<id>/.well-known/agent-card.json` has its `url` rewritten to point at the proxy. | Automatic |
| Access control | A key or team lists the agent IDs it may call in `object_permission.agents`, or gets them through access groups. A key with no list may call every agent, unless `general_settings.agent_access_default_deny: true` is set. | `/key/generate`, `/team/new` |
| Headers for the agent | `static_headers` are always sent. `extra_headers` names headers to copy from the client request. A client header `x-a2a-<agent>-<name>` arrives at the agent as `<name>`. The proxy adds its own `x-litellm-agent-id`, `x-litellm-user-id` and `x-litellm-trace-id`. The client's key is not forwarded. | Agent entry |
| Cost | `litellm_params.cost_per_query`, or `input_cost_per_token` and `output_cost_per_token`. Without them a call costs 0. | Agent entry |
| Limits | `rpm_limit` and `tpm_limit` per agent, plus `session_rpm_limit` and `session_tpm_limit` per session. | Agent entry |
| Completion bridge | With `litellm_params.custom_llm_provider`, the proxy calls `litellm.acompletion` instead of speaking A2A to the agent. That fronts agent platforms that don't speak A2A (such as `langgraph`, `langflow` or Bedrock AgentCore), or any plain model. | Agent entry |
| Guardrails, logging | `litellm_params.guardrails` on the agent. Every call is logged with model `a2a_agent/<name>` and call type `asend_message`. | Agent entry |

The SDK has the client half: `litellm.a2a_protocol` (`aget_agent_card`, `asend_message`, `asend_message_streaming`, built on the `a2a-sdk` package, which in 1.110.2 comes with the `extra_proxy` extra that this project installs), and a provider `a2a/` that lets `completion()` call an agent like a model. Nothing here is licensed.

**The SDK against a fake agent.** [`agents/fake_agents.py`](examples/agents/fake_agents.py) serves two A2A agents on one port: `/triage` labels a ticket `billing`, `bug` or `other`, and `/billing` approves refunds. It records every request at `/_seen`. [`16b_a2a_sdk.py`](examples/agents/16b_a2a_sdk.py) starts it in a thread, so it needs no other process:

```python
"""Call A2A agents from the LiteLLM SDK: read the card, send, stream, and use completion() on an agent."""
import asyncio
import os
import threading
import uuid
from http.server import ThreadingHTTPServer

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import httpx
import litellm
from a2a.compat.v0_3.types import MessageSendParams, SendMessageRequest, SendStreamingMessageRequest
from litellm.a2a_protocol import aget_agent_card, asend_message, asend_message_streaming

from fake_agents import Handler

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
TRIAGE = f"http://127.0.0.1:{server.server_port}/triage"


def params(text):
    """Wrap text as the A2A message a client sends."""
    return MessageSendParams(message={"role": "user", "parts": [{"kind": "text", "text": text}],
                                      "messageId": uuid.uuid4().hex})


async def main():
    print("== 1. the agent card (GET /.well-known/agent-card.json)")
    card = await aget_agent_card(base_url=TRIAGE)
    print(card.name, "|", card.description, "| skills:", [s.id for s in card.skills])

    print("== 2. message/send")
    reply = await asend_message(request=SendMessageRequest(id="1", params=params("I was charged twice")),
                                api_base=TRIAGE)
    result = reply.model_dump(mode="json", exclude_none=True)["result"]
    print(result["kind"], result["role"], result["parts"])

    print("== 3. message/stream")
    request = SendStreamingMessageRequest(id="2", params=params("The app crashes on login"))
    async for chunk in asend_message_streaming(request=request, api_base=TRIAGE):
        event = chunk.model_dump(mode="json", exclude_none=True)["result"]
        text = "".join(p["text"] for p in event.get("artifact", {}).get("parts", []))
        print(f"{event['kind']:15} {event.get('status', {}).get('state', '')!s:9} {text!r}")

    print("== 4. completion() with model a2a/<agent>")
    resp = await litellm.acompletion(model="a2a/triage", api_base=TRIAGE,
                                     messages=[{"role": "user", "content": "Where is my invoice?"}])
    print(resp.choices[0].message.content, "| usage:", resp.usage.prompt_tokens, resp.usage.completion_tokens)
    sent = httpx.get(f"http://127.0.0.1:{server.server_port}/_seen").json()[-1]
    print("the agent got:", sent["method"], sent["body"]["params"]["message"]["parts"])


asyncio.run(main())
server.shutdown()
```

```text
== 1. the agent card (GET /.well-known/agent-card.json)
Ticket triage | Classifies a support ticket as billing, bug or other. | skills: ['classify']
== 2. message/send
message agent [{'kind': 'text', 'text': 'category: billing'}]
== 3. message/stream
task            submitted ''
artifact-update           'category:'
artifact-update           ' bug'
status-update   completed ''
== 4. completion() with model a2a/<agent>
category: billing | usage: 12 3
the agent got: message/send [{'kind': 'text', 'text': 'user: Where is my invoice?'}]
```

- **`aget_agent_card` returns an `a2a-sdk` object**, not a dict. `asend_message` and `asend_message_streaming` take the `a2a-sdk`'s 0.3 request types and return LiteLLM wrappers that have `model_dump()`.
- **Streaming arrives as A2A events, not text deltas.** You put the answer together from the `artifact-update` parts, and the last event is a `status-update` with `final: true`.
- **`completion(model="a2a/<name>")` turns the chat into one text part.** The agent gets `user: Where is my invoice?`: every message flattened into one prompt, with its role as a prefix. The usage numbers are LiteLLM's own token counts of that text, because A2A has no usage field. The name after `a2a/` is only a label when you pass `api_base`. On the proxy it is looked up in the agent registry instead.

**Agents behind the proxy.** These need the database from section 13 for runtime registration and keys. [`agents/agents_config.yaml`](examples/agents/agents_config.yaml) registers the two fake agents, prices the triage agent at $0.002 a call, gives it headers, and caps the billing agent at 2 requests a minute:

```yaml
# Section 16b: the agent gateway. Needs DATABASE_URL (section 13), fake_agents.py on 4016 and _fake_upstream.py on 4011.
model_list:
  - model_name: gpt
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: fake
      api_base: http://127.0.0.1:4011/v1

agents:
  - agent_name: triage
    agent_card_params:
      protocolVersion: "0.3.0"
      name: triage
      description: Classifies a support ticket as billing, bug or other.
      url: http://127.0.0.1:4016/triage
      version: "1.0.0"
      capabilities: {streaming: true}
      defaultInputModes: [text]
      defaultOutputModes: [text]
      skills: [{id: classify, name: Classify ticket, description: Return one category., tags: [support]}]
    litellm_params:
      cost_per_query: 0.002              # what the proxy charges per message/send
    static_headers:
      x-team: support                     # sent to the agent on every call
    extra_headers: [x-ticket-id]          # copied from the client request when present

  - agent_name: billing
    agent_card_params:
      protocolVersion: "0.3.0"
      name: billing
      description: Answers refund and invoice questions.
      url: http://127.0.0.1:4016/billing
      version: "1.0.0"
      capabilities: {streaming: true}
      defaultInputModes: [text]
      defaultOutputModes: [text]
      skills: [{id: refund, name: Refund status, description: Say whether a refund is due., tags: [billing]}]
    rpm_limit: 2

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

```bash
cd examples
uv run python agents/fake_agents.py 4016 &
uv run python _fake_upstream.py 4011 &
export DATABASE_URL=postgresql://postgres:demo@localhost:55432/litellm LITELLM_MASTER_KEY=sk-master-demo LITELLM_LOCAL_MODEL_COST_MAP=True
uv run litellm --config agents/agents_config.yaml --port 4000
uv run python agents/16b_agent_gateway.py        # in another shell, same exports
```

[`16b_agent_gateway.py`](examples/agents/16b_agent_gateway.py)

```python
"""Put A2A agents behind the LiteLLM proxy: discovery, calls, headers, runtime registration, access and spend."""
import os
import time
import uuid

import httpx

PROXY = "http://localhost:4000"
AGENTS = "http://127.0.0.1:4016"
UPSTREAM = "http://127.0.0.1:4011"
ADMIN = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}


def rpc(text, method="message/send"):
    """Return an A2A JSON-RPC request carrying one user text part."""
    return {"jsonrpc": "2.0", "id": uuid.uuid4().hex[:6], "method": method,
            "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": text}],
                                   "messageId": uuid.uuid4().hex}}}


def reply_text(response):
    return " ".join(p["text"] for p in response.json()["result"]["parts"])


def last_agent_request():
    return httpx.get(f"{AGENTS}/_seen").json()[-1]


with httpx.Client(base_url=PROXY, headers=ADMIN, timeout=30) as http:
    print("== 1. agents registered in the config")
    ids = {a["agent_name"]: a["agent_id"] for a in http.get("/v1/agents").json()}
    for name, agent_id in ids.items():
        print(f"{name:8} {agent_id[:16]}...")

    print("== 2. the agent card, as the proxy serves it")
    card = http.get("/a2a/triage/.well-known/agent-card.json").json()
    print("url   :", card["url"])
    print("no key:", httpx.get(f"{PROXY}/a2a/triage/.well-known/agent-card.json").status_code)

    print("== 3. message/send through the proxy, with headers for the agent")
    r = http.post("/a2a/triage", json=rpc("I was charged twice"),
                  headers={"x-ticket-id": "T-42", "x-a2a-triage-x-priority": "high", "x-other": "dropped"})
    print("reply :", r.status_code, reply_text(r))
    seen = last_agent_request()
    print("agent got:", {k: v for k, v in sorted(seen["headers"].items()) if k.startswith("x-") and k != "x-litellm-trace-id"})
    print("client key forwarded:", "authorization" in seen["headers"])

    print("== 4. message/stream through the proxy")
    with http.stream("POST", "/a2a/triage", json=rpc("The app crashes on login", "message/stream")) as r:
        kinds = [line for line in r.iter_lines() if line.startswith("data:")]
    print(r.headers["content-type"].split(";")[0], len(kinds), "events")

    print("== 5. register an agent at runtime that is really an LLM (the completion bridge)")
    writer = http.post("/v1/agents", json={
        "agent_name": "writer",
        "agent_card_params": {"protocolVersion": "0.3.0", "name": "writer", "description": "Drafts replies.",
                              "url": f"{UPSTREAM}/v1", "version": "1.0.0", "capabilities": {"streaming": False},
                              "defaultInputModes": ["text"], "defaultOutputModes": ["text"], "skills": []},
        "litellm_params": {"custom_llm_provider": "openai", "model": "gpt-4o-mini", "api_key": "fake"},
    }).json()
    print("id    :", writer["agent_id"], "| api_key shown as", writer["litellm_params"]["api_key"])
    r = http.post("/a2a/writer", json=rpc("Draft a reply to ticket T-42"))
    upstream = httpx.get(f"{UPSTREAM}/_seen").json()[-1]
    print("reply :", reply_text(r), "| upstream got", upstream["method"], upstream["path"])

    print("== 6. a key that may call only the triage agent")
    key = http.post("/key/generate", json={"object_permission": {"agents": [ids["triage"]]}}).json()["key"]
    as_key = {"Authorization": f"Bearer {key}"}
    print("lists :", [a["agent_name"] for a in http.get("/v1/agents", headers=as_key).json()])
    print("triage:", http.post("/a2a/triage", json=rpc("refund please"), headers=as_key).status_code)
    r = http.post("/a2a/billing", json=rpc("refund $20"), headers=as_key)
    print("billing:", r.status_code, r.json()["error"]["message"])

    print("== 7. the key's spend comes from cost_per_query")
    for _ in range(30):
        spend = http.get("/key/info", params={"key": key}).json()["info"]["spend"]
        if spend:
            break
        time.sleep(1)
    print("spend :", spend)

    print("== 8. billing has rpm_limit: 2")
    print("codes :", [http.post("/a2a/billing", json=rpc("refund $5")).status_code for _ in range(3)])

    print("== 9. delete the runtime agent")
    print(http.delete(f"/v1/agents/{writer['agent_id']}").json())
```

```text
== 1. agents registered in the config
triage   0f916789d300a986...
billing  0c95c7ece1ce1a97...
== 2. the agent card, as the proxy serves it
url   : http://localhost:4000/a2a/triage
no key: 401
== 3. message/send through the proxy, with headers for the agent
reply : 200 category: billing
agent got: {'x-litellm-agent-id': '0f916789d300a986c41cdb23c248926aaec1f73a9bbae0a7efae074f16480baf', 'x-litellm-user-id': 'default_user_id', 'x-priority': 'high', 'x-team': 'support', 'x-ticket-id': 'T-42'}
client key forwarded: False
== 4. message/stream through the proxy
text/event-stream 4 events
== 5. register an agent at runtime that is really an LLM (the completion bridge)
id    : f80b1878-47d3-4c0f-b327-4cb88b45033c | api_key shown as REDACTED_BY_LITELM
reply : fake OpenAI reply | upstream got POST /v1/chat/completions
== 6. a key that may call only the triage agent
lists : ['triage']
triage: 200
billing: 403 Agent 'billing' is not allowed for your key/team. Contact proxy admin for access.
== 7. the key's spend comes from cost_per_query
spend : 0.002
== 8. billing has rpm_limit: 2
codes : [200, 200, 429]
== 9. delete the runtime agent
{'message': 'Agent f80b1878-47d3-4c0f-b327-4cb88b45033c deleted successfully'}
```

What to notice:

- **A config agent's ID is a hash, and a runtime agent's ID is a UUID.** Agents from `agents:` get a stable 64-character ID derived from the entry. `POST /v1/agents` returns a UUID. `/a2a/<...>` accepts either the ID or the `agent_name`.
- **The proxy needs a key even for the card.** `/a2a/<id>/.well-known/agent-card.json` returns 401 without one, and 403 for a key that may not use the agent. The card the client gets is the one in the proxy's config, with `url` set to the proxy, so a client following the card keeps going through the gateway.
- **Errors stay in JSON-RPC.** A denied, missing or rate-limited agent returns a JSON-RPC `error` object with code `-32000`, and the HTTP status is 403, 404 or 429. A malformed request (`jsonrpc` not `"2.0"`) returns code `-32600`, and an unknown method returns `-32601`, both with HTTP 400.
- **Only the headers you name reach the agent.** In step 3 `x-ticket-id` (listed in `extra_headers`), `x-priority` (sent as `x-a2a-triage-x-priority`) and the static `x-team` arrived, but `x-other` did not. The client's `Authorization` header never reaches the agent. To authenticate the proxy to the agent, put the credential in `static_headers` or `litellm_params.api_key`.
- **The completion bridge makes any model an A2A agent.** In step 5, the agent `writer` has `custom_llm_provider: openai`, so the proxy turned the A2A message into a chat completion against the card's `url`. `GET /v1/agents` shows its `api_key` as `REDACTED_BY_LITELM`.
- **Spend lands on the key, and on the spend log row for the call.** `cost_per_query` is charged per `message/send`. In my run the spend log row's model was `a2a_agent/Ticket triage`: the name came from the card the agent itself serves, not the name in the proxy's config.
- **Known problems in 1.110.2.**
  - `object_permission.agents` matches agent IDs only. A key that lists `triage` by name is refused (exercise 16b.2).
  - `PATCH /v1/agents/<id>` with `enabled: false` returns 200, but the agent keeps answering. `enabled` is checked only for agents with a managed identity.
  - Agents from the config can't be changed through the API. A `PATCH` on one returns 404 `Agent with ID ... not found`.

#### Exercises

**16b.1 ★ `ex16b_1_echo_agent.py`: write your own A2A agent**

Start the script with `import _env`. With `http.server`, write an agent named `echo`, run it in a thread on a free port, and have it:
- answer `GET` with an agent card (`protocolVersion: "0.3.0"`, one skill with ID `shout`);
- answer a `message/send` `POST` with a `message` whose single text part is the input in upper case;
- record every request body.

Call it three ways: `aget_agent_card`, `asend_message`, and `litellm.acompletion(model="a2a/echo", api_base=...)`.

Checks:
- The card's name is `echo` and its skill IDs are `["shout"]`.
- `asend_message` with the text `hello` returns the parts `[{"kind": "text", "text": "HELLO"}]`.
- The `completion()` reply is `"USER: HELLO"`. Explain in a comment why it isn't `"HELLO"`.
- Every recorded request has `jsonrpc == "2.0"`, `method == "message/send"` and a non-empty `messageId`.

<details><summary>Hint</summary>

Copy the card fields and reply shape from `examples/agents/fake_agents.py`; the `url` in the card can be built from the `Host` header. The request types are `SendMessageRequest` and `MessageSendParams` from `a2a.compat.v0_3.types`.
</details>

**16b.2 ★★ `ex16b_2_agent_access.py`: register agents and decide who may call them**

With the proxy from this subsection running, register two agents with `POST /v1/agents`. Give them unique names (`t-<random>` pointing at `http://127.0.0.1:4016/triage` with `cost_per_query: 0.005`, and `b-<random>` pointing at `/billing`). Create one key whose `object_permission.agents` lists the triage agent by **name**, and a second key that lists it by **ID**. Call the agents with both keys, then delete both agents.

Checks:
- The key that lists the agent by name gets 403 from its own agent.
- The key that lists it by ID gets the reply `category: billing` for `refund my invoice`. The same key gets 403 from the billing agent, with JSON-RPC error code `-32000`.
- `GET /v1/agents` with the ID key lists the triage agent and not the billing agent.
- That key's spend becomes `0.005`; poll `/key/info`, because spend is written in batches.
- After the deletes, a call to the triage agent's name returns 404.

<details><summary>Hint</summary>

The permission check is `AgentRequestHandler.is_agent_allowed` in `proxy/agent_endpoints/auth/agent_permission_handler.py`. It compares the stable agent ID, not the name.
</details>

**16b.3 ★★ `ex16b_3_agent_headers.py`: what reaches the agent**

Register an agent that points at the fake triage agent, with `static_headers: {"x-env": "tutorial"}` and `extra_headers: ["x-request-source"]`. Send `my invoice is wrong` with the headers `x-request-source: web`, `x-a2a-<agent name>-x-locale: fr` and `x-unlisted: 1`. Read the fake agent's `/_seen` to see what arrived. Then send the same text with `message/stream`, rebuild the answer from the events, and delete the agent (in a `finally`).

Checks:
- The agent got `x-env: tutorial`, `x-request-source: web` and `x-locale: fr`, and `x-litellm-agent-id` equal to the agent's ID.
- It got neither `x-unlisted` nor `authorization`.
- The streamed text equals the `message/send` text (`category: billing`), and the last event is a `status-update` with `final` true and state `completed`.

<details><summary>Hint</summary>

Each `data:` line of the stream is a whole JSON-RPC response; the event is its `result`. Header forwarding is in `invoke_agent_a2a` in `proxy/agent_endpoints/a2a_endpoints.py`.
</details>

**16b.4 ★★ `ex16b_4_agent_router.py`: route a ticket to the right agent**

Write `handle(ticket)`, which asks the `triage` agent for a category, then passes the ticket to the agent whose card has a skill tag equal to that category, if there is one. Build the tag-to-agent map from `GET /v1/agents`, leaving out `triage` itself. Make every agent call with `litellm.completion(model="a2a/<name>", api_base=f"{PROXY}/a2a/<name>", api_key=<key>)`, using a key that may call only `triage` and `billing`. Reset the fake agents' log with `GET /_reset` before you start.

Checks:
- The map is `{"billing": "billing"}`. Run this with no runtime agents left over.
- `handle("Please refund $40 for invoice 7")` returns `("billing", "refund of $40 approved")`.
- `handle("The app crashes on start")` returns `("bug", None)`.
- The fake agents' `/_seen` shows the agents called in the order `["triage", "billing", "triage"]`.

<details><summary>Hint</summary>

The `a2a/` provider sends `api_key` as a bearer token, which is what the proxy expects. The skills are in each agent's `agent_card_params["skills"]`.
</details>

**Clean up.** Stop the proxy with Ctrl-C and the two helpers with `kill %1 %2` (`jobs` lists them). The skills, agents and keys these runs created stay in section 13's Postgres; `docker rm -f litellm-tutorial-db` deletes them along with everything else in it.

## 17. Prompt management: templates outside the code

**Use case:** product owners edit prompts without a code change, prompts are versioned, and the same template can pin its own model.

On any call, `prompt_id=` (with `prompt_variables=`, and optionally `prompt_version=` or `prompt_label=`) hands the request to a prompt manager. The manager renders the template and returns the model, messages and parameters to use. Three ways to provide one:

| Manager | How it is chosen | Where prompts live |
| --- | --- | --- |
| Dotprompt (built in) | The model string starts with `dotprompt/` | `.prompt` files in `litellm.global_prompt_directory` |
| Your own `CustomPromptManagement` subclass | Registered in `litellm.callbacks` | Anywhere: a dict, a database, an API |
| Hosted integrations | A model prefix such as `langfuse/` or `humanloop/`, or `prompt_integration` on the proxy | Langfuse, Humanloop, GitLab, Bitbucket, Arize Phoenix, a generic HTTP API |

A `.prompt` file is YAML front matter plus a template. [`examples/prompts/support.prompt`](examples/prompts/support.prompt):

```text
---
model: openai/gpt-4o-mini
temperature: 0.2
input:
  schema:
    product: string
    plan: string
---
System: You are the support assistant for {{product}}. The customer is on the {{plan}} plan.
{% if plan == "free" %}Answer in under 50 words and do not promise refunds.{% endif %}
```

[`support.v2.prompt`](examples/prompts/support.v2.prompt) is version 2 of the same prompt, with `model: openai/gpt-4o` and a different system line. [`17a_prompt_files.py`](examples/17a_prompt_files.py) renders them and prints what reaches a fake provider:

```python
"""Prompt templates in .prompt files: render with prompt_id/prompt_variables and see what the provider gets."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import litellm

REPLY = {
    "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "fake",
    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
    "usage": {"prompt_tokens": 30, "completion_tokens": 1, "total_tokens": 31},
}


class FakeProvider(BaseHTTPRequestHandler):
    """Answer like OpenAI and print the model, parameters and messages that arrived."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        params = {k: v for k, v in body.items() if k not in ("model", "messages")}
        print(f"  server got  model={body['model']!r}  params={params}")
        for m in body["messages"]:
            print(f"    {m['role']:9} {m['content']!r}")
        data = json.dumps(REPLY).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), FakeProvider)
threading.Thread(target=server.serve_forever, daemon=True).start()
fake = {"api_base": f"http://127.0.0.1:{server.server_port}/v1", "api_key": "sk-fake"}

litellm.global_prompt_directory = str(Path(__file__).parent / "prompts")
question = [{"role": "user", "content": "How do I reset my password?"}]

print("1. prompt_id + prompt_variables: template messages first, then yours; the file's model wins")
litellm.completion(model="dotprompt/openai/gpt-3.5-turbo", messages=question, temperature=0.9,
                   prompt_id="support", prompt_variables={"product": "Acme", "plan": "free"}, **fake)

print("2. prompt_version=2 loads support.v2.prompt")
litellm.completion(model="dotprompt/openai/gpt-3.5-turbo", messages=question, prompt_version=2,
                   prompt_id="support", prompt_variables={"product": "Acme"}, **fake)

print("3. Variables are HTML-escaped")
litellm.completion(model="dotprompt/openai/gpt-3.5-turbo", messages=question,
                   prompt_id="support", prompt_variables={"product": "Tom & Jerry's <Shop>", "plan": "pro"}, **fake)

print("4. A wrong type fails before any request is sent")
try:
    litellm.completion(model="dotprompt/openai/gpt-3.5-turbo", messages=question,
                       prompt_id="support", prompt_variables={"product": 42, "plan": "pro"}, **fake)
except ValueError as e:
    print(f"  {type(e).__name__}: {e}")

server.shutdown()
```

```text
1. prompt_id + prompt_variables: template messages first, then yours; the file's model wins
  server got  model='gpt-4o-mini'  params={'temperature': 0.9}
    system    'You are the support assistant for Acme. The customer is on the free plan.\nAnswer in under 50 words and do not promise refunds.'
    user      'How do I reset my password?'
2. prompt_version=2 loads support.v2.prompt
  server got  model='gpt-4o'  params={}
    system    "You are Acme's senior support engineer. Ask one clarifying question first."
    user      'How do I reset my password?'
3. Variables are HTML-escaped
  server got  model='gpt-4o-mini'  params={}
    system    'You are the support assistant for Tom &amp; Jerry&#39;s &lt;Shop&gt;. The customer is on the pro plan.'
    user      'How do I reset my password?'
4. A wrong type fails before any request is sent
  ValueError: Error compiling prompt 'support': Invalid type for field 'product': expected str, got int
```

What to notice:

- **The template's messages go first, then yours, and the file's model wins.** You asked for `gpt-3.5-turbo` and got `gpt-4o-mini`.
- **The file's `temperature: 0.2` was not sent; the caller's 0.9 was.** Through the SDK, template parameters never reach the provider in 1.110.2. The proxy does apply them.
- **Templates are Jinja2, not Handlebars,** so blocks are `{% if %}`, and variables are HTML-escaped: `Tom & Jerry's` became `Tom &amp; Jerry&#39;s`. Keep variables to plain text, or escape-proof your template.
- **`prompt_version=2` loads `support.v2.prompt`.** If that file doesn't exist, it silently falls back to the base prompt.
- **The input schema only checks types.** A wrong type fails before any request; a missing variable renders as an empty string.
- In the front matter, `model`, `input` and `output` are reserved; any other top-level key becomes a call parameter.

**Your own manager.** Subclass `CustomPromptManagement` and override `get_chat_completion_prompt`, which returns `(model, messages, params)`. [`17b_custom_prompt_manager.py`](examples/17b_custom_prompt_manager.py) serves versioned templates from a dict, with labels:

```python
"""A custom prompt manager: serve versioned, labelled templates from your own store."""
import litellm
from litellm.integrations.custom_prompt_management import CustomPromptManagement

from _mock import mock

PROMPTS = {
    ("summarise", 1): {"model": "openai/gpt-4o-mini", "system": "Summarise in {words} words."},
    ("summarise", 2): {"model": "anthropic/claude-haiku-5-5", "system": "Summarise in {words} words, as bullets."},
}
LABELS = {"production": 1, "staging": 2}


class DictPromptManager(CustomPromptManagement):
    """Look up a template by id and version (or label) and put it before the caller's messages."""

    def get_chat_completion_prompt(self, model, messages, non_default_params, prompt_id,
                                   prompt_variables, dynamic_callback_params, prompt_label=None,
                                   prompt_version=None, **kwargs):
        version = prompt_version or LABELS[prompt_label or "production"]
        template = PROMPTS[(prompt_id, version)]
        system = template["system"].format(**(prompt_variables or {}))
        print(f"  manager: {prompt_id} v{version} -> {template['model']}, system={system!r}")
        return template["model"], [{"role": "system", "content": system}, *messages], non_default_params


litellm.callbacks = [DictPromptManager()]
article = [{"role": "user", "content": "LiteLLM is a Python SDK and proxy that ..."}]

for how in ({}, {"prompt_label": "staging"}, {"prompt_version": 1}):
    print(how or "(no label: production)")
    resp = litellm.completion(model="openai/gpt-4o-mini", messages=article, prompt_id="summarise",
                              prompt_variables={"words": 20}, **how, **mock("A short summary."))
    print(f"  response model: {resp.model}")

print("no prompt_id: the manager is not called")
resp = litellm.completion(model="openai/gpt-4o-mini", messages=article, **mock("A short summary."))
print(f"  response model: {resp.model}")
```

```text
(no label: production)
  manager: summarise v1 -> openai/gpt-4o-mini, system='Summarise in 20 words.'
  response model: gpt-4o-mini
{'prompt_label': 'staging'}
  manager: summarise v2 -> anthropic/claude-haiku-5-5, system='Summarise in 20 words, as bullets.'
  response model: claude-haiku-5-5
{'prompt_version': 1}
  manager: summarise v1 -> openai/gpt-4o-mini, system='Summarise in 20 words.'
  response model: gpt-4o-mini
no prompt_id: the manager is not called
  response model: gpt-4o-mini
```

What to notice:

- **The manager runs only when `prompt_id` is set.** If no manager handles the ID, the call goes out unchanged, with no error.
- **Don't override both the sync and the async hook** (`get_chat_completion_prompt` and `async_get_chat_completion_prompt`). With `acompletion`, LiteLLM runs the async hook and then the sync one, so a manager that overrides both, or a `DotpromptManager` registered in `litellm.callbacks`, applies the template twice. The `dotprompt/` prefix and a sync-only manager apply it once.
- **On the proxy,** prompts go in a top-level `prompts:` list in the config (`prompt_id`, `prompt_integration: dotprompt`, `prompt_file`), and clients send `prompt_id` and `prompt_variables` in the request body. `GET /prompts/list` works without a database; creating prompts with `POST /prompts` needs an admin key and a database. A prompt's `ignore_prompt_manager_model` and `ignore_prompt_manager_optional_params` keep the client's model and parameters.
- The log payload records `metadata["prompt_management_metadata"]`: the prompt ID, variables and integration.

### Exercises

**17.1 ★ `ex17_1_prompt_file.py`: move a prompt into a `.prompt` file**

Have the script write `prompts/triage.prompt` next to itself. Its front matter sets `model` to `_env.SMART` and an input schema with `product: string`, `ticket: string` and `urgent: boolean`. The body has a `System:` line naming the product, a sentence that appears only when `urgent` is true, and a `User: Ticket: {{ticket}}` line. Point `litellm.global_prompt_directory` at the folder and call `completion(model=f"dotprompt/{_env.FAST}", prompt_id="triage", prompt_variables=..., messages=[<your question>])`. Record what LiteLLM sends with a `CustomLogger`.

Checks:
- The request has 3 messages (system, user, user): the template's first, your question last. The system message names the product and includes the urgent sentence.
- The model sent is the file's (`_env.SMART`), not the one in the call.
- `ticket=123` raises `ValueError` containing `Invalid type for field 'ticket'`.

<details><summary>Hint</summary>

Use an absolute directory path: a missing directory makes the call fail with "Unmapped LLM provider ... custom_llm_provider=dotprompt". Override `log_pre_api_call(self, model, messages, kwargs)`, which runs synchronously, even with mocks.
</details>

**17.2 ★★ `ex17_2_prompt_registry.py`: a versioned prompt registry with labels**

Write `RegistryPromptManager(CustomPromptManagement)` serving prompts from `{prompt_id: {version: {"model", "system"}}}`: version 1 uses `_env.FAST`, version 2 uses `_env.ALT`, with labels `{"production": 1, "canary": 2}`. Precedence is `prompt_version`, then `prompt_label`, then `production`. Implement `should_run_prompt_management` (True only for known IDs) and `_compile_prompt_helper` (returning a `PromptManagementClient`), and let `PromptManagementBase` do the rest. Call with no label, with `prompt_label="canary"`, with `prompt_version=1`, and with `prompt_id="unknown"`.

Checks:
- The default and `prompt_version=1` calls go to `_env.FAST` with identical messages; the canary call goes to `_env.ALT` with the v2 system prompt.
- The unknown ID passes through untouched: the call's own model (`_env.SMART`) and the original messages.
- The three managed calls' log entries carry `prompt_management_metadata["prompt_integration"] == "RegistryPromptManager"`.

<details><summary>Hint</summary>

`DotpromptManager` in `litellm/integrations/dotprompt/dotprompt_manager.py` shows how to delegate `get_chat_completion_prompt` to `PromptManagementBase`. Success hooks run in the background, so sleep briefly before checking. The unknown ID is logged with the integration name too, so filter by prompt ID.
</details>

## 18. Observability: traces, metrics and logging platforms

**Use case:** see every LLM call in the tools your team already uses: traces in Jaeger, Tempo or Honeycomb, metrics and alerts in Prometheus and Grafana, conversations in Langfuse or LangSmith.

Section 10 wrote a callback by hand. The built-in integrations are callbacks too, and every one of them is fed from the same record: the **standard logging payload**, `kwargs["standard_logging_object"]`. It holds the call's ID, trace and session IDs, model and model group, tokens, `response_cost`, timings, `cache_hit`, `request_tags`, `metadata` (including section 14's routing decision), the messages and the response, and the error on failure. Turn one on with its name:

```python
litellm.callbacks = ["otel", "langsmith"]          # SDK; each reads its own env vars
```

```yaml
litellm_settings:                                   # proxy config
  callbacks: ["prometheus", "otel"]
```

**OpenTelemetry traces.** [`pyproject.toml`](pyproject.toml) installs `opentelemetry-sdk`, the OTLP/HTTP exporter and, for the Prometheus part below, `prometheus-client`. Run the script from `examples` with `uv run python 18a_otel_traces.py`. [`18a_otel_traces.py`](examples/18a_otel_traces.py) captures spans in memory and prints them as a tree:

```python
"""Trace LiteLLM calls with OpenTelemetry and inspect the spans in memory."""
import asyncio
import os

import litellm
from litellm.integrations.opentelemetry import OpenTelemetry, OpenTelemetryConfig
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from _mock import mock

# Without this, a call made inside your own span writes its attributes onto your span.
os.environ["USE_OTEL_LITELLM_REQUEST_SPAN"] = "true"
KEYS = ("gen_ai.system", "gen_ai.request.model", "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens", "gen_ai.cost.total_cost", "error.type")

litellm.suppress_debug_info = True
exporter = InMemorySpanExporter()
litellm.callbacks = [OpenTelemetry(config=OpenTelemetryConfig(exporter=exporter))]
tracer = trace.get_tracer("support-bot")
msgs = [{"role": "user", "content": "My order #1234 never arrived."}]


async def main():
    with tracer.start_as_current_span("handle_ticket"):
        await litellm.acompletion(model="openai/gpt-4o-mini", messages=msgs,
                                  **mock("Sorry! Let me check order #1234."))
        await litellm.acompletion(model="anthropic/claude-haiku-5-5", messages=msgs,
                                  metadata={"generation_name": "summarise"},
                                  **mock("Customer reports a missing order."))
    await asyncio.sleep(0.5)
    litellm.turn_off_message_logging = True
    await litellm.acompletion(model="openai/gpt-4o-mini", messages=msgs, **mock("Redacted reply."))
    try:
        await litellm.acompletion(model="openai/gpt-4o", messages=msgs, mock_response=litellm.RateLimitError(
            "slow down", llm_provider="openai", model="gpt-4o"))
    except litellm.RateLimitError:
        pass
    await asyncio.sleep(0.5)


def show(span, children, depth=0):
    """Print one span and its children as an indented tree."""
    attrs = span.attributes
    kv = "  ".join(f"{k.split('.')[-1]}={attrs[k]}" for k in KEYS if k in attrs)
    content = "content" if "gen_ai.input.messages" in attrs else ""
    print(f"{'  ' * depth}{span.name:<{24 - 2 * depth}} {span.status.status_code.name:5} {content:7} {kv}")
    for child in children.get(span.context.span_id, []):
        show(child, children, depth + 1)


asyncio.run(main())
spans = sorted(exporter.get_finished_spans(), key=lambda s: s.start_time)
children = {}
for s in spans:
    if s.parent:
        children.setdefault(s.parent.span_id, []).append(s)
for root in (s for s in spans if s.parent is None):
    show(root, children)
print(f"\n{len(spans)} spans, {len({s.context.trace_id for s in spans})} traces")
```

```text
handle_ticket            UNSET         
  litellm_request        OK    content system=openai  model=gpt-4o-mini  input_tokens=10  output_tokens=20  total_cost=1.35e-05
    raw_gen_ai_request   OK            
  summarise              OK    content system=anthropic  model=claude-haiku-5-5  input_tokens=10  output_tokens=20  total_cost=1.1e-05
    summarise            OK            
litellm_request          OK            system=openai  model=gpt-4o-mini  input_tokens=10  output_tokens=20  total_cost=1.35e-05
litellm_request          ERROR         system=openai  model=gpt-4o  type=RateLimitError
7 spans, 3 traces
```

What to notice:

- **Each call is a `litellm_request` span** with `gen_ai.*` attributes: system, model, token counts and cost. The child `raw_gen_ai_request` span carries the raw provider request and response. `metadata={"generation_name": "summarise"}` renamed both.
- **Calls inside your span become its children** because of `USE_OTEL_LITELLM_REQUEST_SPAN=true`. Without it, LiteLLM writes the attributes onto your span instead, and with `acompletion` that span has often ended, so you get "Setting attribute on ended span" warnings and lose them.
- **The parent comes from**, in order: `metadata["litellm_parent_otel_span"]`, the request's W3C `traceparent` header, the active span, else a new root.
- **`litellm.turn_off_message_logging = True`** removed the message content (no `content` mark on the third call) and the raw span. A failed call is a span with status ERROR and `error.type`.
- **To export,** set `OTEL_EXPORTER=otlp_http` and `OTEL_ENDPOINT=<collector URL>` (or the standard `OTEL_EXPORTER_OTLP_*` variables, which win). The default exporter is `console`. `request_tags` don't become span attributes; metadata keys do, as `metadata.<key>`.

**Prometheus metrics and OTel through the proxy.** [`proxy/observability_config.yaml`](examples/proxy/observability_config.yaml) turns on both:

```yaml
model_list:
  - model_name: chat
    litellm_params:
      model: anthropic/claude-sonnet-5-5
      api_key: os.environ/ANTHROPIC_API_KEY
      mock_response: "Hi from Claude (via the proxy)"
  - model_name: chat-cheap
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY
      mock_response: "Hi from GPT-4o mini (via the proxy)"

litellm_settings:
  callbacks: ["prometheus", "otel"]
  custom_prometheus_tags: ["support"]       # adds a tag_support="true"/"false" label

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

[`proxy/fake_otlp_collector.py`](examples/proxy/fake_otlp_collector.py) is a fake OTLP/HTTP collector on port 4141 that prints the spans it receives. [`proxy/observability_client.py`](examples/proxy/observability_client.py) sends three tagged requests with a `traceparent` header, then reads `/metrics`:

```python
"""Call the proxy with a W3C traceparent and tags, then scrape its Prometheus /metrics."""
import os
import re

import httpx
from openai import OpenAI

BASE = os.environ.get("PROXY_URL", "http://localhost:4000")
KEY = os.environ["LITELLM_KEY"]
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
WANT = ("litellm_requests_metric_total", "litellm_spend_metric_total", "litellm_total_tokens_metric_total")

client = OpenAI(base_url=BASE, api_key=KEY)
for alias, tags in (("chat", ["support"]), ("chat", ["billing"]), ("chat-cheap", ["support"])):
    client.chat.completions.create(
        model=alias, messages=[{"role": "user", "content": "hello"}],
        extra_body={"metadata": {"tags": tags}},
        extra_headers={"traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01"})

print("without a key:", httpx.get(f"{BASE}/metrics/").status_code)
text = httpx.get(f"{BASE}/metrics/", headers={"Authorization": f"Bearer {KEY}"}).text
for line in text.splitlines():
    name = line.split("{")[0]
    if name in WANT:
        labels = dict(re.findall(r'(\w+)="([^"]*)"', line))
        print(f"{name:34} requested_model={labels['requested_model']:10} "
              f"tag_support={labels.get('tag_support', '-'):5} {line.rsplit(' ', 1)[1]}")
```

```bash
cd examples/proxy
uv run python fake_otlp_collector.py &
export LITELLM_MASTER_KEY=sk-master-demo ANTHROPIC_API_KEY=unused OPENAI_API_KEY=unused LITELLM_LOCAL_MODEL_COST_MAP=True
OTEL_EXPORTER=otlp_http OTEL_ENDPOINT=http://127.0.0.1:4141 uv run litellm --config observability_config.yaml --port 4000
LITELLM_KEY=sk-master-demo uv run python observability_client.py     # in another shell
```

The client prints the metrics below. The span listing after them is printed by `fake_otlp_collector.py`, so it appears in the first shell, between the proxy's log lines. When you are done, stop the proxy with Ctrl-C and the collector with `kill %1`.

```text
without a key: 401
litellm_spend_metric_total         requested_model=chat       tag_support=true  0.00022
litellm_spend_metric_total         requested_model=chat       tag_support=false 0.00022
litellm_spend_metric_total         requested_model=chat-cheap tag_support=true  1.35e-05
litellm_total_tokens_metric_total  requested_model=chat       tag_support=true  30.0
litellm_total_tokens_metric_total  requested_model=chat       tag_support=false 30.0
litellm_total_tokens_metric_total  requested_model=chat-cheap tag_support=true  30.0
litellm_requests_metric_total      requested_model=chat       tag_support=true  1.0
litellm_requests_metric_total      requested_model=chat       tag_support=false 1.0
litellm_requests_metric_total      requested_model=chat-cheap tag_support=true  1.0
```

The collector received the proxy's spans, all in the client's trace (`4bf92f35`, from the `traceparent` header):

```text
trace=4bf92f35 parent=2b716b98 auth                           
trace=4bf92f35 parent=2b716b98 proxy_pre_call                 
trace=4bf92f35 parent=2b716b98 router                         
trace=4bf92f35 parent=2b716b98 router                         
trace=4bf92f35 parent=2b716b98 litellm_request                model=claude-sonnet-5-5  total_tokens=30  total_cost=0.00022
trace=4bf92f35 parent=468ed6b0 raw_gen_ai_request             
trace=4bf92f35 parent=00f067aa Received Proxy Server Request
```

What to notice:

- **Prometheus needs no licence in 1.110.2,** and `/metrics` **requires a key by default** (`require_auth_for_metrics_endpoint: false` makes it public). It is a mounted app, so `/metrics` redirects to `/metrics/`; use `curl -L`. The rejected scrape is itself counted as a failed request.
- **Metrics carry labels** such as `requested_model`, `model`, `api_key_alias`, `team` and `status_code`. `custom_prometheus_tags: ["support"]` adds a `tag_support` label, `"true"` or `"false"` per request, so you can split spend by tag.
- **The proxy adds its own spans** (`auth`, `proxy_pre_call`, `router`) around `litellm_request`, all under the caller's trace.
- **A missing package is fatal on the proxy but not in the SDK.** Without `opentelemetry-sdk`, the proxy refuses to start with `Could not build the 'otel' callback`; the SDK logs a "Non-Blocking Error" and carries on without traces.
- **Logging platforms.** LangSmith (`LANGSMITH_API_KEY`, `LANGSMITH_BASE_URL`) posts batches to `/api/v1/runs/batch` and sends the whole standard logging payload; batch loggers flush every 5 seconds or 512 events. Langfuse needs the `langfuse` package, which this project doesn't install. Datadog (`DD_API_KEY`, `DD_SITE`) and the generic HTTP logger need a running event loop: with sync `completion()` they log nothing, so use `acompletion`.
- **Redaction:** `litellm.turn_off_message_logging` globally, `turn_off_message_logging=True` per call (the text becomes `redacted-by-litellm`), or the `litellm-enable-message-redaction` and `litellm-disable-message-redaction` request headers. The proxy honours the disable header only for a key or team whose metadata has `allow_client_message_redaction_opt_out: true`; for any other key it drops the header and the messages stay redacted.
- **Per-key or per-team logging** goes in the key's or team's `metadata.logging` (needs the database). The docs mark both team and key logging as Enterprise features; I did not run them without a licence. A key's setting replaces the team's; they are not merged.

### Exercises

**18.1 ★ `ex18_1_otel_spans.py`: trace a three-model pipeline**

Register LiteLLM's `OpenTelemetry` logger with an `InMemorySpanExporter`. Inside one span of your own called `pipeline`, call `_env.FAST`, `_env.SMART` and `_env.ALT` with `acompletion`. Then set `litellm.turn_off_message_logging = True` and make one more call outside the span. Print each `litellm_request` span's model, parent, total tokens, cost, and whether it holds message content.

Checks:
- The three pipeline spans are children of `pipeline` and share its trace ID.
- Each span's `gen_ai.cost.total_cost` equals that response's `_hidden_params["response_cost"]`.
- The fourth span has no `gen_ai.input.messages` and no parent.

<details><summary>Hint</summary>

`OpenTelemetry(config=OpenTelemetryConfig(exporter=InMemorySpanExporter()))` exports synchronously. Set `USE_OTEL_LITELLM_REQUEST_SPAN=true`, or LiteLLM writes onto your `pipeline` span instead of creating children. Sleep briefly after the calls: async callbacks finish after `acompletion` returns.
</details>

**18.2 ★★ `ex18_2_langsmith_sink.py`: audit what a built-in logger ships**

Start a fake LangSmith server on `127.0.0.1:4142` in a thread that records every run posted to it. Point `litellm.callbacks = ["langsmith"]` at it with `LANGSMITH_BASE_URL` and `LANGSMITH_API_KEY="fake-key"`. Make three concurrent tagged calls, one per model, with a prompt containing an email address, then one call with `turn_off_message_logging=True` and one mocked failure. Print each run's tag, model, status, cost and messages.

Checks:
- Exactly 5 runs arrive, all at `/api/v1/runs/batch`, all with `x-api-key: fake-key`.
- The logged `outputs.usage_metadata.total_cost` of the three tagged calls sums to their `_hidden_params["response_cost"]`.
- The failure run has `inputs.status == "failure"` and an `error`; the email appears in the normal runs and nowhere in the redacted one.

<details><summary>Hint</summary>

The logger batches and flushes every 5 seconds, so poll for up to 10 seconds. `inputs` is the whole standard logging payload, and `tags` is its `request_tags`. Use `acompletion`: the periodic flush needs a running event loop.
</details>

## 19. Lens: reviewing agent runs

**Use case:** your agents are in production and you can't read every run. You want a list of runs with their steps, a way to ask questions across all of them, the gateway's recorded cost next to each model call, and an AI reviewer that reads the runs against what the agent is supposed to do and tells you where it falls short, with quotes you can check.

[LiteLLM Lens](https://docs.litellm.ai/docs/proxy/lens) is that reviewer. Section 18 sent LiteLLM's own spans to tracing backends that store and display them. Lens stores agent traces too, but its point is what it does with them:

- **Traces.** Each agent run is one trace: its input and answer, every model call and tool call, latency, tokens and, through a connected proxy, the recorded cost. Lens reads the common span conventions (OpenTelemetry GenAI, OpenInference, LangSmith, Logfire, Traceloop, Vercel AI SDK and Claude Code) and turns them into agent, LLM and tool steps.
- **Investigations.** You describe the expected behaviour, or give named checks. An analysis model reads the runs, groups similar problems into **findings** and cites the exact spans behind each one. Lens checks every quote against the stored span before it keeps a finding. Investigations run once or on a schedule, each with a monthly budget.
- **Datasets and model comparisons.** Runs can be saved as datasets with expected answers and exported as JSONL, and *Model optimizations* compares models on live traffic or a saved dataset. This section doesn't run those.

| | |
| --- | --- |
| Release used here | Lens 0.1.0 (2026-11-19, the first release), [`BerriAI/lens`](https://github.com/BerriAI/lens), MIT licence |
| Status | Early access. The API, the UI and their limits may change between releases |
| Runs as | Its own service with ClickHouse for storage, from a release bundle (Docker Compose) or a Helm chart. It needs no LiteLLM proxy and no Postgres |
| With LiteLLM | A proxy from v1.108.0 connects to it, opens it in the Admin UI sidebar, serves its API under the proxy's own keys, and sends it every request's cost. This tutorial's 1.110.2 has that code built in |
| Docs | [Overview](https://docs.litellm.ai/docs/proxy/lens), [Set up](https://docs.litellm.ai/docs/proxy/lens/deployment), [Add Lens to LiteLLM](https://docs.litellm.ai/docs/proxy/lens/deployment/litellm), [API](https://docs.litellm.ai/docs/proxy/lens/api), [First trace](https://docs.litellm.ai/docs/proxy/lens/first-trace), [Investigations](https://docs.litellm.ai/docs/proxy/lens/investigations) |

### How it works

```mermaid
%% fig: lens
flowchart LR
    agent["Your agent<br/>OTel spans + tracing key"] -- "model calls (virtual key)" --> proxy["LiteLLM proxy"]
    proxy --> providers["Model providers"]
    agent -- "OTLP spans (tracing key)" --> lens["Lens<br/>ingest, normalize, review"]
    proxy -- "request records with cost" --> lens
    you["You<br/>UI, API, SQL"] --> lens
    lens <--> ch[("ClickHouse")]
    lens -- "selected trace content" --> analysis["Analysis model"]
    analysis -. "or through the proxy" .- proxy
```

- **Agents send traces straight to Lens,** as OTLP/HTTP to `<lens>/v1/traces`, with `Authorization: Bearer <tracing key>`. A tracing key only uploads spans and checks their delivery; it can't read anything back. The proxy's own upload routes answer 410, so exporters always point at Lens.
- **Lens normalizes the spans** into steps of type `agent`, `llm`, `tool` (and `chain`, `embedding`, `retriever` and so on), keeps the input and output text without truncation, and stores them in ClickHouse: one row per span in `otel_traces`, a run summary per trace, and the proxy's request records in `spend_logs`. Traces are kept for 14 days by default (`AGENT_TRACING_RETENTION_DAYS`).
- **A connected proxy adds cost and identity.** It exports a record for every request it serves (the same standard logging payload as section 18) to Lens, and Lens matches each record to the agent's model-call span. The proxy also forwards `/lens/...` and `/v1/traces/...` requests from anyone with a proxy key, signed with that caller's identity, so the proxy's users and teams decide who sees which runs.
- **Investigations** send selected trace content to an analysis model that the Lens server holds credentials for: a provider called directly, or a model on your LiteLLM proxy. Each run screens the recent traces, investigates the candidates, groups them into findings, and verifies every quote. Provider charges apply, capped by the investigation's monthly budget.

**Starting Lens.** The release bundle pulls the release image by digest. Lens listens on 4318 by default, which is also the standard OTLP/HTTP port; if a collector already uses it on your machine (as one did on mine), give Lens another port, as here:

```bash
mkdir -p ~/lens && cd ~/lens
gh release download v0.1.0 -R BerriAI/lens -p 'lens-install-0.1.0.tar.gz' -p manifest.txt
grep lens-install manifest.txt | sha256sum -c -        # lens-install-0.1.0.tar.gz: OK
tar -xzf lens-install-0.1.0.tar.gz && cd lens-0.1.0
LENS_PORT=4319 LENS_PUBLIC_URL=http://localhost:4319 ./start
# the first start writes deploy/lens/.env with the default address; keep the new port across restarts
sed -i 's#^LENS_PUBLIC_URL=.*#LENS_PUBLIC_URL=http://localhost:4319#' deploy/lens/.env
echo LENS_PORT=4319 >> deploy/lens/.env
export LENS_ADMIN_TOKEN=$(grep ^LENS_ADMIN_TOKEN= deploy/lens/.env | cut -d= -f2-)
```

```text
Lens is ready at http://localhost:4319/ui/
Sign in with LENS_ADMIN_TOKEN from deploy/lens/.env. Keep the file private and retain it across restarts.
```

The first start pulls Lens and ClickHouse (it took under two minutes here), writes `LENS_ADMIN_TOKEN` and the ClickHouse password into `deploy/lens/.env`, and binds Lens to `127.0.0.1` only; ClickHouse is on an internal network with no host port. Open `http://localhost:4319/ui/` and sign in with the admin token. `docker compose -f deploy/lens/compose.yaml down` stops it and keeps the data; adding `--volumes` deletes every trace, investigation and dataset.

### 19a. Trace an agent into Lens

The examples in [`examples/lens/`](examples/lens/) share three files:

- [`fake_support_llm.py`](examples/lens/fake_support_llm.py) is an OpenAI-compatible fake model on port 4017 for a small support agent. It calls the `lookup_order` tool, and has one planted bug for the investigation in 19c to find: when the customer says "quick", it answers without looking the order up.
- [`support_agent.py`](examples/lens/support_agent.py) is the agent. Each run is an `invoke_agent support_agent` span; model calls go through LiteLLM, and each tool call is an `execute_tool` span with its arguments and result:

```python
"""A small tool-using support agent, traced with OpenTelemetry GenAI spans."""
import asyncio
import json
import uuid

import litellm
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

ORDERS = {"1001": "shipped", "1002": "processing", "1003": "delivered"}
TOOLS = [{"type": "function", "function": {
    "name": "lookup_order", "description": "Look up an order's status by its 4-digit ID.",
    "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}},
                   "required": ["order_id"]}}}]
tracer = trace.get_tracer("support-agent")


def lookup_order(call_id: str, order_id: str) -> dict:
    """Run the tool inside an execute_tool span."""
    args = json.dumps({"order_id": order_id})
    with tracer.start_as_current_span("execute_tool lookup_order", attributes={
            "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "lookup_order",
            "gen_ai.tool.call.id": call_id, "gen_ai.tool.call.arguments": args}) as span:
        if order_id in ORDERS:
            result = {"order_id": order_id, "status": ORDERS[order_id]}
        else:
            result = {"order_id": order_id, "error": "order not found"}
            span.set_status(Status(StatusCode.ERROR, "order not found"))
        span.set_attribute("gen_ai.tool.call.result", json.dumps(result))
        return result


async def _call(messages: list[dict], model: str, **llm: object):
    """One model call; the same call ID goes to LiteLLM and, as a header, to a proxy."""
    call_id = str(uuid.uuid4())
    return await litellm.acompletion(model=model, messages=messages, tools=TOOLS, litellm_call_id=call_id,
                                     extra_headers={"x-litellm-call-id": call_id}, **llm)


async def run(question: str, model: str, attributes: dict | None = None, **llm: object) -> tuple[str, str]:
    """Answer one question inside an invoke_agent span; return the answer and the trace ID."""
    with tracer.start_as_current_span("invoke_agent support_agent", attributes={
            "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "support_agent",
            **(attributes or {})}) as span:
        messages = [{"role": "system", "content": "You answer questions about orders. "
                     "Always use lookup_order before stating an order's status."},
                    {"role": "user", "content": question}]
        for _ in range(4):
            message = (await _call(messages, model, **llm)).choices[0].message
            messages.append(message.model_dump(exclude_none=True))
            if not message.tool_calls:
                break
            for call in message.tool_calls:
                result = lookup_order(call.id, json.loads(call.function.arguments)["order_id"])
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})
        span.set_attribute("gen_ai.output.messages", json.dumps([{"role": "assistant", "content": message.content}]))
        return message.content, format(span.get_span_context().trace_id, "032x")


async def run_all(questions: list[str], model: str, **llm: object) -> list[str]:
    """Run each question in order, print its answer, and return the trace IDs."""
    trace_ids = []
    for question in questions:
        answer, trace_id = await run(question, model, **llm)
        trace_ids.append(trace_id)
        print(f"{trace_id[:8]}  {question:36} -> {answer}")
    await asyncio.sleep(1)  # LiteLLM's async callbacks end their spans after acompletion returns
    return trace_ids
```

- [`_lens.py`](examples/lens/_lens.py) holds the addresses and the tracer setup. LiteLLM's `OpenTelemetry` logger is given the same `TracerProvider` as the agent's own spans, so its model-call spans land under `invoke_agent` in the same trace:

```python
"""Shared helpers for the Lens examples: addresses, credentials and an OTLP tracer that sends to Lens."""
import os

import httpx
import litellm
from litellm.integrations.opentelemetry import OpenTelemetry
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

LENS_URL = os.environ.get("LENS_URL", "http://localhost:4319")
PROXY_URL = os.environ.get("PROXY_URL", "http://localhost:4000")
FAKE_LLM = "http://127.0.0.1:4017/v1"


def admin() -> httpx.Client:
    """Return a client for the Lens API, signed in with the standalone admin token."""
    return httpx.Client(base_url=LENS_URL, timeout=30,
                        headers={"Authorization": f"Bearer {os.environ['LENS_ADMIN_TOKEN']}"})


def gateway(key: str) -> httpx.Client:
    """Return a client for the proxy, which serves the same Lens API once connected."""
    return httpx.Client(base_url=PROXY_URL, timeout=30, headers={"Authorization": f"Bearer {key}"})


def setup_tracing(service: str, tracing_key: str) -> TracerProvider:
    """Send this process's spans, LiteLLM's included, to Lens; return the provider to flush."""
    # Without it LiteLLM names async calls "acompletion", which Lens does not count as a model call.
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")
    os.environ["USE_OTEL_LITELLM_REQUEST_SPAN"] = "true"
    exporter = OTLPSpanExporter(endpoint=f"{LENS_URL}/v1/traces",
                                headers={"Authorization": f"Bearer {tracing_key}"})
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    litellm.suppress_debug_info = True
    litellm.callbacks = [OpenTelemetry(tracer_provider=provider)]
    return provider


def setup_gateway_agent(master: httpx.Client) -> tuple[str, str]:
    """Create the support team, its admin owner, the agent's virtual key and a tracing key; return both keys."""
    if master.get("/team/info", params={"team_id": "support"}).status_code != 200:
        master.post("/team/new", json={"team_id": "support", "team_alias": "support"}).raise_for_status()
    if master.get("/user/info", params={"user_id": "agent-owner"}).status_code != 200:
        master.post("/user/new", json={"user_id": "agent-owner", "user_role": "proxy_admin"}).raise_for_status()
    agent_key = master.post("/key/generate", json={"user_id": "agent-owner", "team_id": "support",
                                                   "models": ["support"]}).json()["key"]
    # A tracing key takes its owner from the key that creates it, so create it with the agent's key.
    created = gateway(agent_key).post("/lens/tracing/keys",
                                      json={"name": "support-agent", "team_id": "support"}).json()
    return agent_key, created["key"]


def delivered(tracing_key: str, trace_ids: list[str]) -> list[bool]:
    """Ask Lens whether each trace arrived; the exporter drops a rejected batch without retrying."""
    with httpx.Client(base_url=LENS_URL, headers={"Authorization": f"Bearer {tracing_key}"}) as client:
        return [client.post("/v1/traces/receipt", json={"trace_id": t}).json()["received"] for t in trace_ids]
```

[`19a_trace_agent.py`](examples/lens/19a_trace_agent.py) creates a tracing key with the admin token, runs four questions, and checks that each trace arrived:

```python
"""Run the support agent against a fake model and send its traces to a standalone Lens."""
import asyncio

import httpx

import fake_support_llm
import support_agent
from _lens import FAKE_LLM, LENS_URL, admin, delivered, setup_tracing

QUESTIONS = ["Can you check order 1003 for me?", "Where is order 1002?",
             "Quick one: has order 1004 shipped?", "What's the status of order 9999?"]

created = admin().post("/lens/tracing/keys", json={"name": "support-agent 19a"}).json()
tracing_key = created["key"]
print(f"tracing key {created['record']['name']!r} owned by {created['record']['tenant']['user_id']}")
provider = setup_tracing("support-agent", tracing_key)
fake_support_llm.start()

trace_ids = asyncio.run(support_agent.run_all(QUESTIONS, "openai/gpt-4o-mini",
                                              api_base=FAKE_LLM, api_key="unused"))
provider.force_flush()

print("delivered:", delivered(tracing_key, trace_ids))
read = httpx.get(f"{LENS_URL}/v1/traces", headers={"Authorization": f"Bearer {tracing_key}"})
print("read traces with the tracing key:", read.status_code)
```

```bash
cd examples/lens
export LENS_ADMIN_TOKEN=...            # from ~/lens/lens-0.1.0/deploy/lens/.env, as above
LITELLM_LOCAL_MODEL_COST_MAP=True uv run python 19a_trace_agent.py
```

```text
tracing key 'support-agent 19a' owned by lens-admin
d4259747  Can you check order 1003 for me?     -> Order 1003 is delivered.
3baa1850  Where is order 1002?                 -> Order 1002 is processing.
4ad46c9d  Quick one: has order 1004 shipped?   -> Order 1004 was delivered yesterday.
466627e7  What's the status of order 9999?     -> Sorry, I couldn't find order 9999.
delivered: [True, True, True, True]
read traces with the tracing key: 401
```

[`19a_read_traces.py`](examples/lens/19a_read_traces.py) reads the runs back with the admin token: the run list, the steps of the run that failed, one step in full, the agents, and a SQL query:

```python
"""Read the support agent's runs back from Lens: run list, one run's steps, one step, agents and SQL."""
from _lens import admin

lens = admin()
runs = lens.get("/v1/traces").json()["data"]
print(f"{'trace':9}{'agent':15}{'llm':>4}{'tools':>6}{'errors':>7}  input")
for run in runs:
    print(f"{run['trace_id'][:8]} {','.join(run['agent_names']):15}{run['llm_calls']:>4}"
          f"{run['tool_calls']:>6}{run['error_count']:>7}  {run['input_preview'][:44]}")

failed = next(r for r in runs if r["error_count"])
detail = lens.get(f"/v1/traces/{failed['trace_id']}", params={"trace_ref": failed["trace_ref"]}).json()
print(f"\nrun {failed['trace_id'][:8]}: {len(detail['spans'])} spans")
children = {}
for span in detail["spans"]:
    children.setdefault(span["parent_span_id"], []).append(span)


def show(parent: str | None, depth: int = 0) -> None:
    """Print the spans under a parent as an indented tree, in start order."""
    for span in sorted(children.get(parent, []), key=lambda s: s["start_offset_ms"]):
        print(f"{'  ' * depth}{span['type']:6} {span['name']:<{30 - 2 * depth}} {span['status']:6}"
              f" {span['model'] or '':12} {span['input_tokens']:>4}/{span['output_tokens']:<4}")
        show(span["span_id"], depth + 1)


show(None)
tool = next(s for s in detail["spans"] if s["type"] == "tool")
step = lens.get(f"/v1/traces/{failed['trace_id']}/spans/{tool['span_id']}",
                params={"trace_ref": failed["trace_ref"]}).json()
print("\ntool step input: ", step["input"], "\ntool step output:", step["output"])

print("\nagents:", lens.get("/v1/traces/agents").json()["agents"])

sql = """
SELECT TraceId, countIf(ObservationType = 'llm') AS llm_calls, countIf(ObservationType = 'tool') AS tool_calls
FROM otel_traces
WHERE Timestamp >= now() - INTERVAL 1 DAY AND ServiceName = 'support-agent'
GROUP BY TraceId HAVING tool_calls = 0
LIMIT 20"""
print("\nruns that answered without calling a tool:")
for row in lens.post("/v1/traces/query", json={"sql": sql}).json()["data"]:
    print(" ", row)
```

```text
trace    agent           llm tools errors  input
466627e7 support_agent     2     1      1  What's the status of order 9999?
4ad46c9d support_agent     1     0      0  Quick one: has order 1004 shipped?
3baa1850 support_agent     2     1      0  Where is order 1002?
d4259747 support_agent     2     1      0  Can you check order 1003 for me?

run 466627e7: 4 spans
agent  invoke_agent support_agent     unset                  0/0   
  llm    chat gpt-4o-mini             ok     gpt-4o-mini    47/44  
  tool   execute_tool lookup_order    error                  0/0   
  llm    chat gpt-4o-mini             ok     gpt-4o-mini   117/17  

tool step input:  {"order_id": "9999"} 
tool step output: {"order_id": "9999", "error": "order not found"}

agents: [{'name': 'support_agent', 'runs': 4, 'failed_runs': 1, 'last_seen': '2026-11-21T02:23:55.317Z', 'frameworks': []}]

runs that answered without calling a tool:
  {'TraceId': '4ad46c9d6b2a6c20dd9f3a1007acd000', 'llm_calls': 1, 'tool_calls': 0}
```

What to notice:

- **Turn on LiteLLM's latest GenAI conventions.** By default LiteLLM writes `gen_ai.operation.name=acompletion` on async calls. Lens doesn't recognise that name, so the model calls became `chain` steps, the run reported `llm_calls: 0` and no models, and each call carried an extra `raw_gen_ai_request` span. With `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` (set in `_lens.py` before the logger is created) the spans are named `chat <model>`, Lens counts them as LLM calls, and the first user message becomes the run's `input_preview`.
- **Pass your `TracerProvider` to LiteLLM** with `OpenTelemetry(tracer_provider=provider)`. One provider and one exporter carry both the agent's spans and LiteLLM's, and `USE_OTEL_LITELLM_REQUEST_SPAN=true` (section 18) makes each model call a child of the current span.
- **A tracing key writes; it never reads.** It belongs to whoever created it (`lens-admin` for the standalone admin token, a user and a team through the proxy), and uploading with it puts the runs in that owner's scope. Reading the runs back with it gave 401. `POST /v1/traces/receipt` with a trace ID (and optionally up to 1,000 span IDs) answers only `received: true` or `false`, so an exporter can confirm delivery without read access.
- **The API.** `GET /v1/traces` lists runs from the last 24 hours, up to 50 per page (pass `next_cursor` back as `cursor`; `start_ms` and `end_ms` change the window). `GET /v1/traces/{trace_id}?trace_ref=...` returns the run's spans with their type, model, tokens, status, and cost when there is any. `GET /v1/traces/{trace_id}/spans/{span_id}` returns one step's full input and output. `GET /v1/traces/agents` counts runs and failed runs per agent name.
- **SQL.** `POST /v1/traces/query` runs read-only ClickHouse SQL over `otel_traces` (one row per span), `agent_traces_by_key` (run summaries), `spend_logs` (the proxy's request records), `otel_logs` and `lens_task_profiles`. `GET /v1/traces/query/help` returns the live schema, examples and rules: bound `Timestamp`, add `LIMIT`, no `FORMAT` clause, `Duration` is in nanoseconds, `StatusCode` values are `STATUS_CODE_OK`, `STATUS_CODE_ERROR` and `STATUS_CODE_UNSET`, and `spend_logs FINAL` before summing cost. A query gets 256 MiB and 10 seconds. The query above found the planted bug before any AI looked at it: one run answered with no tool call.

#### Exercises

**19a.1 ★ `ex19a_1_source_links.py`: link runs to the conversation that started them**

Put the [`examples/lens/`](examples/lens/) folder on `sys.path` and reuse `support_agent.run()`, whose `attributes` argument adds attributes to the run's root span. Create your own tracing key and make three runs with service name `ticket-bot`: one with `agent.source.type="jira"`, `agent.source.url` (an `https://` link to a ticket) and `agent.source.title`; one with a `custom` source whose URL is `http://`; and one about an order that doesn't exist. Read the three summaries back.

Checks:
- The first run's summary has `source == {"type": "jira", "url": ..., "title": ...}`.
- The second run has no `source`: Lens keeps only `https` links.
- The third run has `error_count == 1`, and its one `tool` span has status `error`.

<details><summary>Hint</summary>

Traces can take a moment to appear in `GET /v1/traces` after `force_flush()`; poll for a few seconds. `source` is left out of a summary rather than set to `null`, so test with `"source" not in run`.
</details>

**19a.2 ★★ `ex19a_2_trace_sql.py`: rebuild the run summaries with SQL**

With `POST /v1/traces/query`, compute for every `support-agent` run in the last day its LLM calls, tool calls, error spans, and input and output tokens. Compare each with that run's summary from `GET /v1/traces`, following `next_cursor` through every page. Then list the runs that answered without a tool call, and print the average and p95 duration per step type. Finally send `DROP TABLE otel_traces`.

Checks:
- Every run's SQL counts and token totals equal its summary's `llm_calls`, `tool_calls`, `error_count`, `input_tokens` and `output_tokens`.
- The runs without a tool call are exactly the ones that asked a "quick" question.
- `DROP TABLE` is refused, and the table still answers queries afterwards.

<details><summary>Hint</summary>

Group `otel_traces` by `TraceId` and use `countIf(ObservationType = 'llm')` and `countIf(StatusCode = 'STATUS_CODE_ERROR')`. Sum the tokens over all of a run's spans, not only the LLM ones: that is what the summary does, and it matters for traces whose model calls were recorded as `chain`. Against standalone Lens 0.1.0 the query endpoint answered 503, not 400, both for SQL it can't parse and for statements it won't run. The docs say SQL that does not parse returns 400 and a query ClickHouse rejects returns 503, so accept either code for a parse error.
</details>

### 19b. Connect Lens to the proxy

Connected, the proxy and Lens share two secrets: `LITELLM_LENS_SERVICE_TOKEN` authenticates the proxy's internal calls to Lens (request records, reads), and `LENS_GATEWAY_SECRET` lets Lens verify the identity the proxy forwards. Both must be at least 32 characters (the proxy also caps `LENS_GATEWAY_SECRET` at 512) and the same on both sides. Add them to Lens and restart it:

```bash
cd ~/lens/lens-0.1.0
printf 'LITELLM_LENS_SERVICE_TOKEN=%s\nLENS_GATEWAY_SECRET=%s\n' $(openssl rand -hex 32) $(openssl rand -hex 32) >> deploy/lens/.env
docker compose -f deploy/lens/compose.yaml up -d --wait
```

[`lens_config.yaml`](examples/lens/lens_config.yaml) is the proxy's config. `support` is the agent's model (the fake), and `analysis` is a real Bedrock model for 19c:

```yaml
# The proxy connected to Lens. LITELLM_LENS_URL (set in the environment) turns the connection on;
# tracing.store.type: lens says the same thing in the config.
model_list:
  - model_name: support                     # the support agent's model: fake_support_llm.py
    litellm_params:
      model: openai/gpt-4o-mini
      api_base: http://127.0.0.1:4017/v1
      api_key: unused
  - model_name: analysis                    # the model Lens investigations use (19c); real Bedrock
    litellm_params:
      model: bedrock/us.anthropic.claude-haiku-5-5
      aws_region_name: us-west-2

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  tracing:
    store:
      type: lens
```

Start the fake model and the proxy with section 13's Postgres (Lens works with a proxy without a database, but teams, users and virtual keys need one):

```bash
cd examples/lens
set -a; source <(grep -E '^(LITELLM_LENS_SERVICE_TOKEN|LENS_GATEWAY_SECRET)=' ~/lens/lens-0.1.0/deploy/lens/.env); set +a
export LITELLM_LENS_URL=http://localhost:4319 LITELLM_LENS_PUBLIC_URL=http://localhost:4319
export LITELLM_MASTER_KEY=sk-master-demo DATABASE_URL=postgresql://postgres:demo@localhost:55432/litellm
export LITELLM_LOCAL_MODEL_COST_MAP=True AWS_PROFILE=<your-profile>     # AWS only for 19c
uv run python fake_support_llm.py &
uv run litellm --config lens_config.yaml --port 4000
```

`LITELLM_LENS_URL` is the address the proxy calls, and setting it is what turns the connection on. `LITELLM_LENS_PUBLIC_URL` is the address exporters are told to use. Neither ends in `/ui/` or `/v1/traces`. In Docker, the proxy can't reach Lens at `localhost`: attach the proxy's container to the external network `lens_default` and use `LITELLM_LENS_URL=http://lens:4318`. On Kubernetes, the LiteLLM chart's `lens.*` values connect the proxy, but the chart doesn't install Lens.

[`19b_gateway_agent.py`](examples/lens/19b_gateway_agent.py) checks the connection, runs the agent through the proxy, and reads each model call's cost back through the proxy. `setup_gateway_agent()` in `_lens.py` creates the `support` team, an admin user `agent-owner`, the agent's virtual key in that team, and a tracing key made with that virtual key:

```python
"""Trace the support agent through the proxy and read each model call's recorded cost back from Lens."""
import asyncio
import os
import time

import fake_support_llm
import support_agent
from _lens import PROXY_URL, gateway, setup_gateway_agent, setup_tracing

QUESTIONS = ["Can you check order 1001 for me?", "Quick one: is order 1002 delivered?"]

master = gateway(os.environ["LITELLM_MASTER_KEY"])
service = master.get("/lens/service").json()
print("lens connection:", "connected" if service["connected"] else "NOT connected", service["status"])

agent_key, tracing_key = setup_gateway_agent(master)
provider = setup_tracing("support-agent", tracing_key)
fake_support_llm.start()
trace_ids = asyncio.run(support_agent.run_all(QUESTIONS, "litellm_proxy/support",
                                              api_base=PROXY_URL, api_key=agent_key))
provider.force_flush()
time.sleep(5)  # the proxy exports request records to Lens in the background

owner = gateway(agent_key)
for run in owner.get("/v1/traces").json()["data"]:
    if run["trace_id"] not in trace_ids:
        continue
    print(f"\nrun {run['trace_id'][:8]}: spend={run['spend']} priced_calls={run['priced_calls']}/{run['llm_calls']}")
    detail = owner.get(f"/v1/traces/{run['trace_id']}", params={"trace_ref": run["trace_ref"]}).json()
    for span in sorted(detail["spans"], key=lambda s: s["start_offset_ms"]):
        print(f"  {span['type']:6} {span['name']:28} spend={span['spend']}  match={span['spend_match']}")
```

```bash
LITELLM_MASTER_KEY=sk-master-demo LITELLM_LOCAL_MODEL_COST_MAP=True uv run python 19b_gateway_agent.py
```

```text
lens connection: connected {'storage_ready': True, 'credentials_ready': True, 'release': '0.1.0', 'protocol_version': 7, 'public_contract': 1}
3a3380e7  Can you check order 1001 for me?     -> Order 1001 is shipped.
0596577e  Quick one: is order 1002 delivered?  -> Order 1002 was delivered yesterday.

run 0596577e: spend=1.725e-05 priced_calls=1/1
  agent  invoke_agent support_agent   spend=None  match=None
  llm    chat support                 spend=1.725e-05  match=matched

run 3a3380e7: spend=5.91e-05 priced_calls=2/2
  agent  invoke_agent support_agent   spend=None  match=None
  llm    chat support                 spend=3.345e-05  match=matched
  tool   execute_tool lookup_order    spend=None  match=None
  llm    chat support                 spend=2.565e-05  match=matched
```

What to notice:

- **`GET /lens/service` is the connection check.** A working connection reports `connected: true`, `storage_ready`, `credentials_ready` (the service token and the gateway secret are accepted) and `public_contract: 1`. With the connection on, the proxy serves the same `/v1/traces` and `/lens` API as the standalone service, under its own keys. The docs add that Lens then opens from the Admin UI's sidebar for proxy admins, with no separate admin token, and that runs uploaded before the connection keep their standalone owner; I checked the API, not the UI.
- **Cost attaches per model call.** Each `llm` span shows the proxy's recorded `spend` and `match=matched`, and the run sums them (`priced_calls` 2 of 2). Lens never prices calls itself: a call with no proxy record stays unpriced, and token counts are not cost.
- **The call ID must reach both sides.** Lens matches a span to a request record by the provider's response ID and by LiteLLM's call ID. When the agent uses the LiteLLM SDK against the proxy, the SDK and the proxy each make their own call ID, so the span carried two keys that pointed different ways and every call came out `ambiguous`. `_call()` in `support_agent.py` passes one ID as `litellm_call_id=` and as the `x-litellm-call-id` header, which the proxy adopts.
- **Ownership must line up too.** A request record matches only spans whose tracing key belongs to the same team and the same user (or the same key) as the virtual key that made the call. I made the tracing key with the master key instead, so it belonged to `default_user_id`, and every call came out `no_spend_log`. Only proxy admins can create tracing keys, so the user who owns an agent's virtual key and creates its tracing key needs the `proxy_admin` role.
- **Who can read what.** Proxy admins (and admin viewers) read every run; other users read their own runs, plus a team's runs when the team grants its members `/spend/logs` (`POST /team/permissions_update` with `team_member_permissions: ["/spend/logs"]`; `default_team_params` in the config sets it for new teams). A team service-account key with no user gets 403 on trace reads. Per the docs, a team admin (a licensed role) always sees the team's traces without that grant. Everything under `/lens`, including tracing keys and investigations, can be changed by proxy admins only; the docs say read-only admins can read investigations, findings and history. Exercise 19b.2 checks each rule.

#### Exercises

These exercises need the proxy from 19b running, with Lens connected.

**19b.1 ★ `ex19b_1_preflight.py`: a preflight check for a connected proxy**

Write the check you would run after deploying: Lens's `/health/ready`; through the proxy, `/lens/service`'s `configured`, `storage_ready`, `credentials_ready`, `public_contract == 1` and `connected`; an admin can create a tracing key; a span sent with it to the public URL that `/lens/service` reports arrives; and the test key is revoked. Print one PASS or FAIL line per check, and exit 1 if any fails.

Checks:
- Against the running setup every line passes and the exit code is 0.
- With `LENS_URL=http://localhost:9` the readiness check fails with the connection error instead of a traceback, and the exit code is 1.

<details><summary>Hint</summary>

Send the span with a plain `TracerProvider`, a `SimpleSpanProcessor` and an `OTLPSpanExporter`; LiteLLM isn't needed. `provider.shutdown()` flushes it. Revoke the key with `DELETE /lens/tracing/keys/{record.id}`.
</details>

**19b.2 ★★ `ex19b_2_team_access.py`: who can read the support team's runs**

Make one support-agent run through the proxy. Create an `internal_user` called `teammate`, add them to the `support` team, and give them a key in that team. Also create a team service-account key (team, no user). Check what each key can read, before and after the team shares its runs, then set the team's permissions back to empty.

Checks:
- Without `/spend/logs` the teammate's `GET /v1/traces` doesn't include the run; with it, it does. The run's owner sees it either way.
- The teammate gets 403 on `GET /lens` and on `POST /lens/tracing/keys`.
- The service-account key gets 403 on `GET /v1/traces`.

<details><summary>Hint</summary>

`POST /team/member_add` with `{"team_id": "support", "member": {"role": "user", "user_id": "teammate"}}`, and `POST /team/permissions_update` with `{"team_id": "support", "team_member_permissions": [...]}`. Neither needs a licence in 1.110.2.
</details>

### 19c. Investigations: let a model review the runs

This subsection and exercise 19c.1 call a real model: you need AWS Bedrock access, and each investigation run cost me $0.05 to $0.13. There is no offline path, so skip to section 20 if you have no Bedrock access. Run the commands in a new shell, with `LITELLM_MASTER_KEY` and `LENS_ADMIN_TOKEN` exported again.

An investigation needs an analysis model on the Lens server. Here Lens uses the proxy's `analysis` model (Claude Haiku 5.5 on Bedrock) through a virtual key that can call nothing else and has a $2 budget. Lens runs in a container, so it reaches the proxy on your machine at `host.docker.internal`, which Docker Desktop provides. On Linux without Docker Desktop, add `extra_hosts: ["host.docker.internal:host-gateway"]` to the `lens` service (I didn't run that variant). Sign in to AWS first (`aws sso login --profile <your-profile>`), because the proxy makes the calls:

```bash
AK=$(curl -s localhost:4000/key/generate -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'content-type: application/json' \
  -d '{"key_alias":"lens-analysis","models":["analysis"],"max_budget":2}' | jq -r .key)
cd ~/lens/lens-0.1.0
printf 'LENS_GATEWAY_API_BASE=http://host.docker.internal:4000\nLENS_GATEWAY_API_KEY=%s\n' "$AK" >> deploy/lens/.env
docker compose -f deploy/lens/compose.yaml up -d --wait
curl -s localhost:4319/lens/gateway -H "Authorization: Bearer $LENS_ADMIN_TOKEN"
```

```text
{"configured":true,"connected":true,"api_base":"http://host.docker.internal:4000","evaluation_models":0,"analysis_models":1,"error":null,"last_refreshed":"2026-11-21T02:23:32.478479188Z"}
```

Lens asks the proxy's `/model_group/info` which models the key can use, and offers each chat model with a known price and output limit for analysis. To call a provider directly instead, set `LENS_ANALYSIS_MODELS` with an `api_key_env` naming the variable that holds the key (the [analysis guide](https://github.com/BerriAI/lens/blob/v0.1.0/docs/analysis.md) has examples). The docs' check in the UI is **Settings > Analysis > Check configuration**; `GET /lens/gateway` and `GET /lens/models` give the same answer over the API.

[`19c_investigate.py`](examples/lens/19c_investigate.py) makes six more runs through the proxy, waits for them to settle, starts a one-off investigation with a description of the expected behaviour, and prints the findings:

```python
"""Send the support agent's runs through the proxy, ask Lens to investigate them, and print the findings."""
import asyncio
import os
import time

import fake_support_llm
import support_agent
from _lens import PROXY_URL, delivered, gateway, setup_gateway_agent, setup_tracing

QUESTIONS = ["Can you check order 1001 for me?", "Where is order 1003?",
             "Quick one: has order 1002 shipped?", "What's the status of order 1002?",
             "Quick question, did order 1001 arrive?", "Is order 4242 on its way?"]
EXPECTED = ("support_agent answers customers' questions about their orders. Before it states an order's "
            "status it must call lookup_order and report exactly the status the tool returned. If the "
            "order does not exist it must say so.")
TERMINAL = {"completed", "partial", "failed", "cancelled"}

master = gateway(os.environ["LITELLM_MASTER_KEY"])
agent_key, tracing_key = setup_gateway_agent(master)
provider = setup_tracing("support-agent", tracing_key)
fake_support_llm.start()
trace_ids = asyncio.run(support_agent.run_all(QUESTIONS, "litellm_proxy/support",
                                              api_base=PROXY_URL, api_key=agent_key))
provider.force_flush()
arrived = delivered(tracing_key, trace_ids)
print(f"{sum(arrived)} of {len(trace_ids)} runs reached Lens")
if not all(arrived):
    raise SystemExit("Lens rejected a span batch; run the script again")
print("waiting for the runs to settle")
time.sleep(150)  # Lens skips traces received in the last two minutes, so a run can finish first

investigation = master.post("/lens", json={
    "name": "Support agent order lookups", "model": "analysis", "agent_name": "support_agent",
    "context": EXPECTED, "lookback_hours": 1, "enabled": False, "monthly_budget": 1}).json()
print("\ninvestigation", investigation["id"], "queued")

started = time.monotonic()
while True:
    state = master.get(f"/lens/{investigation['id']}").json()
    job = state["jobs"][0] if state["jobs"] else {}
    if job.get("status") in TERMINAL or time.monotonic() - started > 900:
        break
    time.sleep(15)

cover = job.get("coverage") or {}
print(f"run {job.get('status')} after {time.monotonic() - started:.0f}s: screened {cover.get('screened')} runs, "
      f"investigated {cover.get('investigated')}, failed tasks {cover.get('failed_tasks')}, cost ${job.get('cost'):.4f}")
if job.get("error"):
    print("run error:", job["error"][:150])
for finding in state["findings"]:
    print(f"\n[{finding['priority']}] {finding['title']}  ({finding['kind']}, {finding['status']})")
    print("  ", finding["description"])
    print("   suggestion:", finding["suggestion"])
    for evidence in finding["evidence"][:3]:
        print(f"   evidence span {evidence['span_id']}: {evidence['quote']!r}")
```

```bash
LITELLM_MASTER_KEY=sk-master-demo LITELLM_LOCAL_MODEL_COST_MAP=True uv run python 19c_investigate.py
```

```text
07fce647  Can you check order 1001 for me?     -> Order 1001 is shipped.
de69bb50  Where is order 1003?                 -> Order 1003 is delivered.
8243f588  Quick one: has order 1002 shipped?   -> Order 1002 was delivered yesterday.
c737bb56  What's the status of order 1002?     -> Order 1002 is processing.
53a6292a  Quick question, did order 1001 arrive? -> Order 1001 was delivered yesterday.
91b6b610  Is order 4242 on its way?            -> Sorry, I couldn't find order 4242.
6 of 6 runs reached Lens
waiting for the runs to settle

investigation 6ed71b9a-166d-4eb1-8f67-98190a8affdc queued
run completed after 120s: screened 12 runs, investigated 2, failed tasks 0, cost $0.0523

[high] Agent gave order status without looking it up  (issue, open)
   The user asked about an order's status. The agent answered with a delivery status, but the recording has no lookup_order call before that answer. This breaks the rule to look up the order before stating its status. Only the recorded spans are visible, so an unrecorded lookup cannot be fully ruled out.
   suggestion: Check whether lookup_order ran in the flagged sessions. Confirm that tool calls are recorded in the trace. If they did not run, make the agent call lookup_order before any status reply.
   evidence span d2b4453f645ce742: 'Order 1002 was delivered yesterday.'
   evidence span 1e7673e6df6b7c82: 'Order 1004 was delivered yesterday.'
   evidence span 651786a866355b91: 'Output: [{"role": "assistant", "content": "Order 1001 was delivered yesterday."}]'
```

What to notice:

- **It found the planted bug,** as a high-priority `issue`, from runs it had never been told about, with the quotes behind it and a suggestion. Each finding also has a `brief` with the user's goal, what happened, and test cases that can seed a dataset. Read the evidence, not only the title: a finding groups several runs (here three, from more than one script), and in an earlier run its title named one order while its quotes came from another.
- **New runs wait two minutes.** Lens skips traces received in the last two minutes so that it doesn't analyse a run that is still going. Started straight after the runs, the first investigation screened 0 runs and cost nothing. The script sleeps 150 seconds.
- **Check delivery before you investigate.** In one of about a dozen runs while writing this, Lens answered a span upload with 400 and the exporter dropped the whole batch, six runs, without retrying; the investigation then reviewed only older runs. It didn't happen again, and I didn't find the cause. The script asks for receipts and stops if any run is missing.
- **`completed` can hide a failed task.** A run's `coverage` counts the runs screened, investigated, grouped and failed. When the model cites a span that doesn't exist, Lens retries, then drops that task, keeps the verified findings, and here still reported `completed`, with the problem in the job's `error`. The docs describe such a run as **Partial**, so check `failed_tasks` and `error` yourself rather than trusting the status.
- **The API.** `POST /lens` creates an investigation and queues its first run: `name`, `model`, `agent_name` (or `service`), `context` or `checks` (each check has an `id` and an `instruction`), `lookback_hours` (default 24), `interval_minutes` (default 15), `monthly_budget` (default 100 USD), and `enabled: false` for a single run. `GET /lens/{id}` returns its `settings`, `jobs` and `findings`; `POST /lens/{id}/runs` with `{}` runs it again, and `POST /lens/{id}/cancel` stops a run. Only proxy admins can call the ones that change anything; per the docs, read-only admins can read.
- **Cost and privacy.** This run cost $0.05 for 12 runs (between $0.05 and $0.13 across my runs); the budget reserves money before each call and stops the investigation when it runs out, not the tracing. The content goes to whichever analysis model you configure. Lens's own calls through the proxy are logged like any others, and one of them was too large for the proxy's export to Lens (`dropped request records (record exceeds the export budget)` in the proxy log; requests carry on).
- **Automatic analysis.** Once an analysis model is configured, Lens also creates an automatic investigation per agent it sees: it waits for 10 traces from the last 24 hours, then runs hourly over up to 10 traces with a $10 monthly budget. You can change or pause it under **Findings > Configure**.

#### Exercises

**19c.1 ★★ `ex19c_1_checked_findings.py`: investigate with named checks, then verify every quote**

Start a one-off investigation of `support_agent` with two `checks` instead of a `context`: `lookup_before_status` (an order status stated without a lookup earlier in the run, or different from what the tool returned) and `missing_order` (a status given after the tool said the order wasn't found). Wait for it to finish. Then, for every piece of evidence, find its trace and verify the quote against the stored span yourself.

Checks:
- The run finishes `completed` or `partial`; print its cost, failed tasks and error.
- Every finding's `check_id` is one of your two check IDs, and at least one `lookup_before_status` finding is an `issue`.
- Every quote is found in its span.

<details><summary>Hint</summary>

An evidence item's `execution_id` is base64-encoded JSON: `["traces", "", trace_id, trace_ref]`. Lens shows the model each span as `Input: ...`, `Output: ...` and `Status: <StatusCode> <StatusMessage>` lines, and a quote can cover more than one line, so split the quote on newlines, strip those prefixes, and look for each part. The read API doesn't return the status line, so get `StatusCode` and `StatusMessage` from `otel_traces` with SQL, and validate the IDs before you put them in the query. Run it within an hour of 19c, or make new runs first. It costs about $0.12.
</details>

**Clean up.** Stop the proxy with Ctrl-C and the fake support model with `kill %1`. Stop Lens from the bundle folder with `docker compose -f deploy/lens/compose.yaml down`; add `-v` to delete the stored traces as well. Section 20 uses the Postgres container again, so leave it running.

## 20. Access control and secret handling

**Use case:** the proxy holds every provider key your organisation has. Before anyone outside your laptop can reach it, you need to know exactly who can call which model, who can create and revoke keys, how people sign in with the identity provider you already run, and where each secret lives, how it rotates and what happens when its store is down.

This section opens with what is free and what needs a licence, and then has three parts: the proxy's own access model (20a), connecting an identity provider and giving each person a spend cap (20b), and secret handling (20c). Section 21 then covers guardrails and the rest of a production deployment.

**What is free and what needs a licence.** Many access-control features of LiteLLM 1.110.2 check for an Enterprise licence (`LITELLM_LICENSE`). I checked each feature below against the installed source and, where the table says so, against a running proxy. The licence column matters when you plan a deployment: several gated features do not fail at startup, they fail when the first request uses them.

| Feature | Licence in 1.110.2 | How it fails without one |
| --- | --- | --- |
| Master key, virtual keys, teams, users, roles, `key_type`, key `allowed_routes`, key expiry (`duration`) | Free | — |
| `custom_auth` (your own auth function) | Free | — |
| Per-user budgets (`max_budget`, `budget_duration`) and their scheduled reset | Free | — |
| `allowed_ips` (proxy-wide IP allowlist) | Enterprise | The proxy refuses to start: `allowed_ips is an Enterprise Feature` (run) |
| Admin UI single sign-on (Google, Microsoft, generic OIDC) | Free for up to 5 users | The 6th SSO user is not created |
| Header identity from oauth2-proxy (`enable_oauth2_proxy_auth`) | Free (no licence check in the source; not run here) | — |
| JWT auth for API callers (`enable_jwt_auth`) | Enterprise | 403 on every JWT request (run below) |
| OAuth2 token introspection (`enable_oauth2_auth`) | Enterprise | 403 |
| SCIM v2 user provisioning (`/scim/v2`) | Enterprise | 403 |
| `/key/regenerate` for virtual keys | Enterprise | 500 (run below); the master key itself can be regenerated for free |
| `enforced_params` | Enterprise | The key is created; every call with it fails (run below) |
| Key `tags`, per-key `guardrails`, `model_max_budget` | Enterprise | `/key/generate` refuses the request (403 for `tags` and `guardrails`; from the source, not shown in the run below) |
| Organizations and the `org_admin` role, assigning a team `admin` | Enterprise | 403 from `/organization/*`; adding a team member as `admin` is refused |
| Proxy-wide `allowed_routes`, `admin_only_routes`, `public_routes` | Enterprise | `allowed_routes` logs an error but is still enforced; the other two are ignored |
| Secret managers: AWS Secrets Manager, Azure Key Vault, custom class | Free | — |
| Secret managers: HashiCorp Vault, Google Secret Manager, CyberArk, AWS KMS-encrypted env | Enterprise | Startup error |

### Open source vs. Enterprise: when you need a licence

*Checked in November 2026 against the [LiteLLM Enterprise page](https://docs.litellm.ai/docs/enterprise) and the installed 1.110.2 source. Licensing terms change, so check again before relying on this.*

LiteLLM is open core. Running the proxy in production, commercially too, is free under the MIT licence. You need a commercial licence only when you turn on features from the Enterprise tier.

**What's free.** The open-source gateway includes virtual keys, teams and users with their roles, budgets and rate limits per key, user and team, spend tracking, the Admin UI, load balancing, guardrails, the MCP gateway, and an OpenAI-compatible API that clients in any language can call. The Python SDK is open source too: 100+ providers, the router and fallbacks, cost per call, and logging callbacks. Everything about cost calculation in this tutorial is free.

**What needs a licence.** Enterprise is a licence key for the same Docker image and version, so there's nothing to migrate. Set it in the environment and restart the proxy:

```env
LITELLM_LICENSE="eyJ..."
```

The licensed features most likely to matter for an internal gateway, as the Enterprise page lists them. Where 1.110.2 behaves differently, the item says so:

- **Identity:** Admin UI SSO is free for up to 5 users and needs a licence beyond that. JWT auth with your identity provider's tokens and SCIM provisioning are licensed. So are organizations and the team-admin role. Teams, users and their roles (`proxy_admin`, `internal_user` and so on) are free, although the Enterprise page lists "role-based access control (organizations, teams, user roles)" as a whole.
- **Security:** audit logs with retention, IP allowlists (`allowed_ips`; in 1.110.2 the proxy refuses to start with it and no licence), public and private route controls, and automated virtual-key rotation. For secret managers, the Enterprise page lists all of them, but 1.110.2 checks for a licence only for HashiCorp Vault, Google Secret Manager, CyberArk and AWS KMS-encrypted environment values. AWS Secrets Manager, Azure Key Vault and a custom secret manager have no licence check in its source.
- **Cost governance:** tag-based budgets, per-model budgets on a virtual key (`model_max_budget`), temporary budget increases, soft-budget email alerts, and programmatic spend reports (`/global/spend/report`) by key, team, tag or model. Basic spend tracking and budgets are free.
- **Logging:** per-team logging destinations, turning logging off per team, and log export to GCS or Azure Blob.
- **Guardrails:** the open-source framework includes custom guardrails, the content filter used in section 21 and Presidio for PII masking. Per the Enterprise page, the built-in integrations `llmguard_moderations`, `llamaguard_moderations`, `hide_secrets`, `openai_moderations`, `google_text_moderation`, `lakera_prompt_injection` and `aporia_prompt_injection` need a licence. Guardrails set per key or per team are licensed too. In 1.110.2, the first five check for a licence at startup; the `lakera_prompt_injection` and `aporia_prompt_injection` callbacks have no check in the source (I didn't run them).
- **Operations:** multi-region deployment, request and response size limits, custom Swagger and email branding, and support SLAs.

To check that a key is active, open the proxy's root URL. With a valid licence, the API docs page says **Enterprise Edition** in its description.

**Cost and buying.** There's no public price list: pricing depends on deployment size, and sales gives you a quote. There's a 30-day trial, arranged through sales. You can buy through AWS Marketplace or Azure Marketplace, or directly by invoice.

**Design note.** If you plan to authenticate gateway users with your company's identity provider, the obvious LiteLLM features for that (JWT auth, SSO beyond 5 users, SCIM) are licensed. Two free alternatives:
- Validate your IdP's tokens in a `custom_auth` function. 20b below does this, including per-person spend caps.
- Keep authentication in your own service, and have it issue or map LiteLLM virtual keys.

**Read the licence files.** The repository's top-level `LICENSE` applies MIT to everything except the `enterprise/` directory, which has its own commercial licence. On PyPI that code ships as a separate package, `litellm-enterprise`, and `litellm[proxy]` installs it (version 0.1.83.post1 with 1.110.2). Its licence is `LicenseRef-Proprietary`: the software "may only be used in production" under BerriAI's Enterprise terms. Copying that code, or removing the licence check to use its features without a key, falls outside the MIT grant. Read both licence files for the version you deploy, and have your legal team review them before you commit.

### 20a. Who can do what: the proxy's access model

Every request carries one credential, in `Authorization: Bearer`, `x-api-key` or `x-litellm-api-key`. The proxy knows four kinds:

| Credential | What it is | Where it is checked |
| --- | --- | --- |
| Master key | The admin credential, from `general_settings.master_key` | Compared with the configured value; it can do everything |
| Virtual key | `sk-...` minted by `/key/generate`, stored as a SHA-256 hash in Postgres | Looked up in the database (then cached in memory) |
| Identity-provider token | A JWT from Okta, Entra ID, Keycloak and so on | `custom_auth` or JWT auth (20b) |
| UI session | A cookie from the admin UI login or SSO | The UI routes only |

The proxy runs its checks in a fixed order. The first one that fails decides the status code:

```text
request
  1. request size (Enterprise), body safety (no api_base / base_url / model_list from clients), allowed_ips (Enterprise)
  2. credential: master key | custom_auth | JWT | virtual key (DB) -> 401 if unknown, expired or deleted
  3. route permission: user role, key_type, the key's allowed_routes -> 403
  4. model access: the key's models, then its team's models -> 403
  5. budgets and limits: key, user, team, end user -> 422 budget / 429 rate limit
  6. guardrails (section 21) -> 400
  -> the model call
```

**Roles.** A user's `user_role` decides which management routes their keys may call:

| Role | Can do | Typical holder |
| --- | --- | --- |
| `proxy_admin` | Everything, like the master key | The platform team |
| `proxy_admin_viewer` | Read every key, team, user and spend report; change nothing | Auditors, finance, on-call |
| `org_admin` | Manage teams and users inside their organisation. Needs a licence, as organizations do | A department lead |
| `internal_user` | Create and manage keys for themselves, inside their teams; call models | Engineers |
| `internal_user_viewer` | See their own keys and spend; no key creation. The docs mark this role deprecated in favour of team and organisation roles | Read-only users |

Inside a team, members are `admin` (manage the team's members and keys; assigning one needs a licence) or `user`.

**Scoping a key.** The fields that matter most on `/key/generate`:

| Field | Effect |
| --- | --- |
| `models` | Allowed model aliases; empty means "everything the team allows" |
| `team_id`, `user_id` | Owner; the team's `models`, budget and limits apply on top of the key's |
| `key_type` | `llm_api` (model routes only), `management`, `read_only` or `default` |
| `allowed_routes` | An explicit route list, such as `["/v1/chat/completions"]` |
| `duration` | Expiry, such as `"30d"` or `"8h"`; an expired key gets 401 |
| `max_budget`, `budget_duration`, `rpm_limit`, `tpm_limit`, `max_parallel_requests` | Spend and rate limits (section 13) |
| `metadata` | Free-form owner, cost centre or ticket; shows up in logs and spend reports |

[`examples/security/access_config.yaml`](examples/security/access_config.yaml) is the section 12 config with a database. [`examples/security/access_demo.py`](examples/security/access_demo.py) builds a small organisation and tries to cross each boundary. Its helpers send one request and print the status and the proxy's reason:

```python
team = httpx.post(f"{BASE}/team/new", headers=ADMIN, json={"team_alias": f"search-{RUN}", "models": ["chat-cheap"]}).json()["team_id"]
httpx.post(f"{BASE}/user/new", headers=ADMIN, json={
    "user_id": f"alice-{RUN}", "user_role": "internal_user", "teams": [team]})
alice = new_key(user_id=f"alice-{RUN}", team_id=team, key_alias=f"alice-app-{RUN}")
show("model outside the team", chat(alice, model="chat"))
show("internal_user: key for someone else", call("POST", "/key/generate", alice, user_id="mallory"))
llm_only = new_key(key_type="llm_api", key_alias=f"llm-only-{RUN}")
chat_route = new_key(allowed_routes=["/v1/chat/completions"], key_alias=f"chat-route-{RUN}")
temp = new_key(duration="3s", key_alias=f"temp-{RUN}")
```

Run it against a proxy with Postgres (section 13's container, or any database):

```bash
cd examples/security
export LITELLM_MASTER_KEY="sk-$(openssl rand -hex 32)" LITELLM_SALT_KEY="sk-$(openssl rand -hex 32)"
echo "$LITELLM_MASTER_KEY"                 # copy it: the other shell must export the same value
export DATABASE_URL=postgresql://postgres:demo@localhost:55432/litellm ANTHROPIC_API_KEY=unused OPENAI_API_KEY=unused
uv run litellm --config access_config.yaml --port 4101
PROXY_URL=http://localhost:4101 DB_CONTAINER=litellm-tutorial-db uv run python access_demo.py   # in another shell, after exporting the same LITELLM_MASTER_KEY
```

```text
== 1. a team owns the model list; users and keys inherit it
  team model                                   200
  model outside the team                       403 The requested model 'chat' is not available for this API key, or the model name is invalid. Che
== 2. roles decide what a user may manage
  internal_user: key for herself               200
  internal_user: key for someone else          403 User can only create keys for themselves. Got user_id=mallory, Your ID=alice-1794896132
  internal_user: create a user                 401 Authentication Error, Only proxy admin can be used to generate, delete, update info for new key
  proxy_admin_viewer: list keys                200
  proxy_admin_viewer: create a key             403 user not allowed to access this route, role= proxy_admin_viewer. Trying to access: /key/generat
== 3. key types and route allowlists
  llm_api key: chat                            200
  llm_api key: /key/generate                   403 Virtual key is not allowed to call this route. Only allowed to call routes: ['llm_api_routes'].
  allowed_routes=[chat]: chat                  200
  allowed_routes=[chat]: /v1/models            403 Virtual key is not allowed to call this route. Only allowed to call routes: ['/v1/chat/completi
== 4. an Enterprise-only key field is accepted at creation and fails at call time
  create key with enforced_params              200
  call with 'user' in the body                 500 Enforced Params is an Enterprise feature. Enforced Params: ['user']. You must be a LiteLLM Ente
== 5. short-lived keys expire on their own
  before expiry                                200
  after expiry                                 401 Authentication Error - Expired Key. Key Expiry time 2026-11-17 06:15:36.587000+00:00 and curren
== 6. rotation without an Enterprise licence: issue, switch, delete
  /key/regenerate                              500 Regenerating Virtual Keys is an Enterprise feature, You must be a LiteLLM Enterprise user to us
  old key after delete                         401 Authentication Error, Invalid API key provided.
  new key                                      200
== 7. what the database stores for a key
  stored token == sha256(key): True   key_name: sk-...asnA   plaintext stored: False
```

What this shows:

- **Give apps `llm_api` keys.** An app key that can also call `/key/generate` lets anyone who steals it mint new keys. `key_type: llm_api` closes that, and `allowed_routes` narrows a key further, down to one route.
- **Put the model list on the team, not on each key.** The key inherits it. Moving a model in or out of a team then changes every key in the team at once.
- **An `internal_user` can serve themselves and nothing more.** They can create keys for their own `user_id` only, and can't create users. Use `proxy_admin_viewer` for anyone who needs to see everything but change nothing.
- **Issue keys with an expiry.** `duration` makes a forgotten key stop working by itself. Combine it with rotation (exercise 20.4) for keys that must live longer.
- **Rotation is free; `/key/regenerate` isn't.** Without a licence, rotate by issuing a new key with the same scope, switching the caller, then blocking and deleting the old key. Rotating the master key is free too, and how you do it depends on `LITELLM_SALT_KEY` (20c). With a salt key set, which is the recommended setup, the master key is only an auth credential: change `LITELLM_MASTER_KEY` and restart every proxy. Do not call `/key/regenerate` with `new_master_key` in that setup on 1.110.2: before v1.112.0 it re-encrypts the stored credentials under the new master key while the proxy keeps decrypting with the salt key, so every stored credential becomes unreadable (the docs' master-key rotation page carries this warning). Only when no salt key is set, so that the master key is also the encryption key, use `/key/regenerate` with `new_master_key`, after backing up the database; it re-encrypts stored credentials, and the old master key keeps working until you restart the proxy with the new one.
- **One Enterprise field fails late, not at creation.** `/key/generate` accepted `enforced_params` and returned 200; every call with that key then returned 500. The other licensed key fields (`tags`, `guardrails`, `model_max_budget`) are refused when the key is created. Test a new key with a real call before handing it out.
- **The database never sees a virtual key.** `LiteLLM_VerificationToken.token` holds `sha256(key)` and `key_name` holds a masked form (`sk-...asnA`). A database dump doesn't leak usable keys, but it can't give a lost key back either: show the key once, at creation.
- **The status codes tell callers what to do:** 401 means fix the credential, 403 means this key may not do this, 422 means out of budget, 429 means slow down.

### 20b. Connecting your identity provider

Organisations already run an identity provider (IdP): Okta, Microsoft Entra ID, Google Workspace, Auth0, Keycloak, AWS Cognito, Ping Identity or OneLogin. LiteLLM connects to it in four places, and each place has a different licence situation:

| Integration point | Who it is for | LiteLLM feature | Licence |
| --- | --- | --- | --- |
| Admin UI sign-in | People who manage keys, teams and spend in `/ui` | SSO with `GOOGLE_*`, `MICROSOFT_*` or `GENERIC_*` (any OIDC IdP) environment variables | Free for up to 5 users |
| API callers with IdP tokens | Apps and users that already hold an OIDC token | `custom_auth` that validates the token (run below) | Free |
| | | `enable_jwt_auth` with `litellm_jwtauth` mappings | Enterprise |
| | | An identity-aware proxy (oauth2-proxy, Pomerium) in front, with `enable_oauth2_proxy_auth` | Free (not run here) |
| Spend per person | A cap on what each signed-in person can spend, reset on a schedule | User rows with `max_budget` and `budget_duration`, created by `custom_auth` on first sign-in (run below) | Free |
| User and group provisioning | Joiners, movers and leavers synced from the IdP | SCIM v2 at `/scim/v2` (Okta and Entra ID provisioning apps) | Enterprise |
| The proxy's own identity at the provider | The proxy calling Bedrock, Azure OpenAI or Vertex AI | Cloud IAM instead of static keys | Free |

Every OIDC provider publishes the same three things: an **issuer** URL, a **JWKS** URL with its public signing keys, and **claims** in its tokens that say who the user is and which groups or roles they have. Where these live for the common IdPs (I could not test against live tenants, so check the values against your tenant's `/.well-known/openid-configuration`):

| IdP | Issuer (`iss`) | JWKS | Groups or roles claim | Watch out for |
| --- | --- | --- | --- | --- |
| Okta | `https://<org>.okta.com/oauth2/default` (a custom authorization server) | `<issuer>/v1/keys` | `groups`, after you add a groups claim to the authorization server | The org authorization server (`https://<org>.okta.com`) issues tokens meant only for Okta's own APIs, so you can't validate them |
| Microsoft Entra ID | `https://login.microsoftonline.com/<tenant-id>/v2.0` | `https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys` | `roles` (app roles), or `groups` (object IDs) | Past about 200 groups, Entra drops `groups` and sends an overage claim. Prefer app roles. `aud` is the application ID URI or client ID |
| Google Workspace / Cloud Identity | `https://accounts.google.com` | `https://www.googleapis.com/oauth2/v3/certs` | None for groups; `hd` holds the Workspace domain | Restrict on `hd` and `email_verified`, and resolve groups through the Directory API |
| Auth0 | `https://<tenant>.<region>.auth0.com/` | `<issuer>.well-known/jwks.json` | `permissions` (RBAC), or a namespaced custom claim | The issuer has a trailing slash, and issuer matching is exact |
| Keycloak | `https://<host>/realms/<realm>` | `<issuer>/protocol/openid-connect/certs` | `realm_access.roles`, or `groups` through a Group Membership mapper | Nested claims need a dotted path |
| AWS Cognito | `https://cognito-idp.<region>.amazonaws.com/<user-pool-id>` | `<issuer>/.well-known/jwks.json` | `cognito:groups` | Access tokens carry `client_id`, not `aud`. Check `token_use` too |
| Ping Identity, OneLogin | The issuer from their discovery document | From discovery | Configurable | Standard OIDC; nothing special |

**The free path: `custom_auth` that validates IdP tokens.** `general_settings.custom_auth` points at an async function that gets every request and its credential. It returns a `UserAPIKeyAuth` describing the caller, or raises. To run it offline, [`examples/security/fake_idp.py`](examples/security/fake_idp.py) plays the IdP: it publishes a discovery document and a JWKS, and signs RS256 tokens, exactly as Okta or Keycloak would. [`examples/security/oidc_auth.py`](examples/security/oidc_auth.py) is the auth function:

```python
ISSUER = os.environ["OIDC_ISSUER"]
AUDIENCE = os.environ["OIDC_AUDIENCE"]
MASTER_KEY = os.environ["LITELLM_MASTER_KEY"]

# First matching group wins, so list the most privileged group first.
GROUP_POLICY = [
    ("llm-admins", {"user_role": LitellmUserRoles.PROXY_ADMIN, "models": []}),
    ("ml-eng", {"user_role": LitellmUserRoles.INTERNAL_USER, "models": ["chat", "chat-cheap"], "rpm_limit": 60}),
    ("support", {"user_role": LitellmUserRoles.INTERNAL_USER, "models": ["chat-cheap"], "rpm_limit": 20}),
]


def _jwks_client() -> jwt.PyJWKClient:
    """Discover the IdP's signing keys once; PyJWKClient caches them and refetches on an unknown kid."""
    global _jwks
    if _jwks is None:
        config = httpx.get(f"{ISSUER}/.well-known/openid-configuration", timeout=5).json()
        _jwks = jwt.PyJWKClient(config["jwks_uri"], cache_keys=True, lifespan=600)
    return _jwks


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
```

[`examples/security/idp_config.yaml`](examples/security/idp_config.yaml) turns it on:

```yaml
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  custom_auth: oidc_auth.user_api_key_auth      # oidc_auth.py, next to this file
  custom_auth_run_common_checks: true           # still enforce model lists, budgets and limits
```

```bash
cd examples/security
uv run python fake_idp.py 4013 &
export LITELLM_MASTER_KEY=sk-master-demo ANTHROPIC_API_KEY=unused OPENAI_API_KEY=unused
export OIDC_ISSUER=http://127.0.0.1:4013 OIDC_AUDIENCE=litellm-proxy
uv run litellm --config idp_config.yaml --port 4102
uv run python idp_client.py            # in another shell, with the same exports
```

[`idp_client.py`](examples/security/idp_client.py) signs in as several users, then tries the attacks a gateway must refuse. It takes about 35 seconds, because one token has to expire:

```text
alice (ml-eng)  -> chat                200 Hi from Claude
bob (support)   -> chat-cheap          200 Hi from GPT-4o mini
bob (support)   -> chat                403 {'error': "oidc: model 'chat' not allowed for your group"}
carol (no LLM group)                   403 {'error': "oidc: no LLM access for groups ['finance']"}
token for another app (aud)            401 {'error': 'oidc: token was issued for another application'}
expired token                          401 {'error': 'oidc: token expired'}
bob edits his groups claim             401 {'error': 'oidc: invalid token (InvalidSignatureError)'}
a random string                        401 {'error': 'oidc: invalid token (DecodeError)'}
master key still works                 200 Hi from Claude
```

What I learned building it:

- **The proxy does not check a custom-auth token's `models` against the request.** My first version only returned `models=["chat-cheap"]` for the support group, and bob's request for `chat` got a 200, even with `custom_auth_run_common_checks: true`. The key-level model check only runs for virtual keys from the database; the common checks enforce team models only when the team exists in the database. So the auth function checks the requested model itself, using `_read_request_body`, which reads the already-parsed body. The docs name a second switch for this, which I did not run: `litellm_settings.enable_post_custom_auth_checks: true`, together with `custom_auth_run_common_checks`, makes the proxy enforce the `models`, `expires` and `model_max_budget` of the object your function returns.
- **`custom_auth` replaces all of the proxy's key checks, including the master key.** Without the `hmac.compare_digest` branch, the master key is just another invalid JWT and you lock yourself out of the admin API. Virtual keys from the database stop working too, unless your function looks them up itself. With a licence, `custom_auth_settings.mode: auto` tries your function first and falls back to normal virtual-key authentication.
- **Validate everything, and pin the algorithm.** `algorithms=["RS256"]` refuses `alg: none` and the trick of signing an HS256 token with the IdP's public key (exercise 20.2 tries both). `audience` stops a token issued for another app (payroll, in the run above) from working here. `issuer` stops a token from another tenant. `require` refuses tokens that leave out a claim.
- **Return a stable per-user `api_key`.** Rate limits and spend attach to `api_key`. Using the token's `jti` gives every new token a fresh limit; `oidc:<sub>` makes `rpm_limit` apply per person (exercise 20.2 shows the 429).
- **Plan for signing-key rotation.** IdPs rotate signing keys. PyJWT's `PyJWKClient` refetches the JWKS when it sees an unknown `kid`, but not within `cooldown_duration` (30 seconds) of its last fetch. A token signed with a just-published key can be refused for up to 30 seconds. IdPs usually publish new keys before they use them, so this rarely shows in practice; exercise 20.2 reproduces it.
- **Don't block the event loop.** `PyJWKClient` fetches with blocking `urllib`, so the call runs in `asyncio.to_thread`. The keys are cached, so only the first request and each refresh go to the network.

**The Enterprise path: built-in JWT auth.** With a licence, the proxy validates IdP tokens itself, and maps claims to users, teams and roles, without your code:

```yaml
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  enable_jwt_auth: true
  litellm_jwtauth:
    user_id_jwt_field: sub
    user_email_jwt_field: email
    team_ids_jwt_field: groups              # Entra: roles; Cognito: cognito:groups; Keycloak: realm_access.roles
    admin_jwt_scope: litellm_proxy_admin    # a token with this scope is a proxy admin
    user_allowed_email_domain: example.com
    enforce_team_based_model_access: true
```

```bash
export JWT_PUBLIC_KEY_URL=https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys   # comma-separate several IdPs
export JWT_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0
export JWT_AUDIENCE=api://litellm-proxy
```

Without a licence, the proxy starts, and every request with a JWT gets this (from a run against `fake_idp.py`):

```json
{"error":{"message":"JWT Auth is an enterprise only feature. You must be a LiteLLM Enterprise user to use this feature. If you have a license please set `LITELLM_LICENSE` in your env. ...","type":"auth_error","param":"premium_user","code":"403"}}
```

**Admin UI sign-in with your IdP.** The UI needs a database and `PROXY_BASE_URL`, the public URL that the IdP redirects back to (`<PROXY_BASE_URL>/sso/callback`, which you register in the IdP). Set one group of variables. I did not run these against live tenants:

```bash
export PROXY_BASE_URL=https://llm.example.com
# Google Workspace
export GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=...
# Microsoft Entra ID
export MICROSOFT_CLIENT_ID=... MICROSOFT_CLIENT_SECRET=... MICROSOFT_TENANT=<tenant-id>
# Any OIDC IdP: Okta, Keycloak, Auth0, Ping, OneLogin
export GENERIC_CLIENT_ID=... GENERIC_CLIENT_SECRET=...
export GENERIC_AUTHORIZATION_ENDPOINT=https://<org>.okta.com/oauth2/default/v1/authorize
export GENERIC_TOKEN_ENDPOINT=https://<org>.okta.com/oauth2/default/v1/token
export GENERIC_USERINFO_ENDPOINT=https://<org>.okta.com/oauth2/default/v1/userinfo
export GENERIC_SCOPE="openid email profile groups"
export GENERIC_ROLE_MAPPINGS_GROUP_CLAIM=groups GENERIC_ROLE_MAPPINGS_DEFAULT_ROLE=internal_user_viewer
```

Without a licence, SSO creates at most 5 users; the source counts every user row except SCIM-deactivated ones. `DISABLE_ADMIN_UI=True` turns the UI sign-in off altogether (section 21).

**The proxy's own identity at the providers.** The other half of access control is how the proxy proves itself to Bedrock, Azure OpenAI and Vertex AI. Use the cloud's workload identity instead of long-lived keys. Nothing then needs rotating, and a leaked config file holds no secret. These are standard LiteLLM parameters; I didn't run them here:

```yaml
model_list:
  - model_name: claude                     # AWS: EKS Pod Identity, IRSA or an instance role; no key in the config
    litellm_params:
      model: bedrock/us.anthropic.claude-sonnet-5-5
      aws_region_name: us-west-2
      aws_role_name: arn:aws:iam::123456789012:role/litellm-bedrock   # optional: assume a narrower role
      aws_session_name: litellm-proxy
  - model_name: gpt                        # Azure: an Entra ID service principal instead of an API key
    litellm_params:
      model: azure/<deployment>
      api_base: https://<resource>.openai.azure.com
      tenant_id: os.environ/AZURE_TENANT_ID
      client_id: os.environ/AZURE_CLIENT_ID
      client_secret: os.environ/AZURE_CLIENT_SECRET
  - model_name: gemini                     # Google: Workload Identity / application default credentials
    litellm_params:
      model: vertex_ai/gemini-2.5-flash
      vertex_project: <project>
      vertex_location: us-central1
```

For Azure with a managed identity, leave out the three Entra variables and set `litellm_settings.enable_azure_ad_token_refresh: true`; LiteLLM then gets tokens from `DefaultAzureCredential`. The [`exercises/_env.py`](exercises/_env.py) helper in this tutorial follows the same rule for AWS: it refuses to load when `AWS_ACCESS_KEY_ID` is in `.env.local`, warns when it is exported in the shell, and is meant to be used with SSO credentials.

#### Budgets that follow the person

**Use case:** each person who signs in gets a spending cap, for example $20 a month. When they reach it, every LLM call they make is refused until the next reset, whatever credential they use: a fresh IdP token, another laptop or a second app. Nothing here needs a licence.

**Where the cap lives.** The proxy has four budget holders, and a request is checked against every one that applies:

| Holder | Created with | Applies to |
| --- | --- | --- |
| Key | `/key/generate` with `max_budget` | Calls with that one key (section 13) |
| User | `/user/new` with `max_budget` and `budget_duration` | Calls attributed to that `user_id`, whichever key or token made them |
| Team | `/team/new` with `max_budget` | Calls with keys that belong to the team |
| End user | `/customer/new`, plus `"user": "<id>"` in the request body | People of an app that calls with its own key (exercise 13.2) |

A cap that follows the person is the user budget. `budget_duration` sets how often it resets. The proxy stores the next reset time in `budget_reset_at`, and a background job sets `spend` back to 0 once that time has passed.

**Resets fall on calendar checkpoints, not N after the first call.** I computed these with LiteLLM's own `get_next_standardized_reset_time`, for 21:07 UTC on Friday 20 November 2026:

| `budget_duration` | Next reset | Rule |
| --- | --- | --- |
| `"2m"` | 21:08 | The next whole multiple of 2 minutes |
| `"1h"` | 22:00 | The top of the next hour |
| `"1d"` | 00:00 on 21 November | The next midnight |
| `"7d"`, `"1w"` | 00:00 on Monday 23 November | The start of the next week |
| `"30d"`, `"1mo"` | 00:00 on 1 December | The first of the next month |

Midnight is in UTC unless you set `litellm_settings.timezone` (for example `America/Los_Angeles`). `litellm_settings.budget_reset_time: "09:00"` moves the day, week and month resets to that time of day. The source's docstring says `"30d"` resets "every 30 days from now". It doesn't: as the table shows, it lands on the first of the month.

**Wiring it to your IdP.** Section 20b's `custom_auth` already returns `user_id=claims["sub"]`. With `custom_auth_run_common_checks: true`, the proxy loads that user's row and checks its budget before every call. Two things are missing, and [`examples/security/budget_auth.py`](examples/security/budget_auth.py) adds them around `oidc_auth.py`:

```python
GROUP_BUDGETS = {
    "ml-eng": {"max_budget": 0.00003, "budget_duration": "2m"},
    "support": {"max_budget": 0.00002, "budget_duration": "2m"},
}


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
```

`_user_exists` calls the proxy's own `get_user_object`, which is cached, so only a person's first request reaches the database. `_provision` creates the row with the same `/user/new` call an admin would make, with the group's budget and `auto_create_key: false`. It holds a lock so that two first requests can't both create it. The budgets are tiny, and the period is 2 minutes, so the demo runs out and resets quickly. In production they would be something like `{"max_budget": 20, "budget_duration": "1mo"}`.

[`examples/security/budget_config.yaml`](examples/security/budget_config.yaml):

```yaml
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  custom_auth: budget_auth.user_api_key_auth    # budget_auth.py, next to this file
  custom_auth_run_common_checks: true           # this is what enforces the user's max_budget
  proxy_budget_rescheduler_min_time: 5          # check for due resets every 5-6 s (default: about 10 min)
  proxy_budget_rescheduler_max_time: 6
```

It needs section 13's Postgres:

```bash
cd examples/security
docker run -d --name litellm-tutorial-db -e POSTGRES_PASSWORD=demo -e POSTGRES_DB=litellm -p 55432:5432 postgres:16   # skip if it is already running
uv run python fake_idp.py 4013 &         # skip if it is still running from above
export LITELLM_MASTER_KEY=sk-master-demo ANTHROPIC_API_KEY=unused OPENAI_API_KEY=unused
export OIDC_ISSUER=http://127.0.0.1:4013 OIDC_AUDIENCE=litellm-proxy
export DATABASE_URL=postgresql://postgres:demo@localhost:55432/litellm
uv run litellm --config budget_config.yaml --port 4103
PROXY_URL=http://localhost:4103 uv run python budget_client.py      # in another shell, with the same exports
```

[`budget_client.py`](examples/security/budget_client.py) signs alice in, spends her budget, checks that a fresh token doesn't help, waits for the reset, and raises her cap as an admin. It takes up to 2 minutes, depending on how far the clock is from the next even minute:

```text
== 1. alice signs in for the first time: her user row is created from her group
call 1: 200 Hi from GPT-4o mini
{'max_budget': 3e-05, 'spend': 0.0, 'budget_duration': '2m', 'budget_reset_at': '2026-11-21T05:10:00Z'}
== 2. alice spends until her budget runs out
call 2: 200 Hi from GPT-4o mini
call 3: 200 Hi from GPT-4o mini
call 4: 422 ExceededBudget: User=alice-1795237779 over budget. Spend=3.959999999999985e-05, 
call 5: 422 ExceededBudget: User=alice-1795237779 over budget. Spend=3.959999999999985e-05, 
== 3. the cap follows the person, not the credential
alice, fresh token:         422 ExceededBudget: User=alice-1795237779 over budget. Spend=3.959999999999985e-05, 
bob (support), unaffected:  200 Hi from GPT-4o mini
== 4. wait for the next reset
alice again after 30 s: 200 Hi from GPT-4o mini
{'max_budget': 3e-05, 'spend': 0.0, 'budget_duration': '2m', 'budget_reset_at': '2026-11-21T05:12:00Z'}
== 5. an admin raises alice's cap; signing in again does not overwrite it
alice, fresh token: 200 Hi from GPT-4o mini
{'max_budget': 1.0, 'spend': 0.0, 'budget_duration': '2m', 'budget_reset_at': '2026-11-21T05:12:00Z'}
```

What I learned building it:

- **A person with no user row has no cap, and nothing tells you.** I removed the provisioning step and signed in as a user with no row: 7 calls in a row got 200. When the lookup raises `UserNotFoundError`, the proxy logs it at debug level and carries on without user limits. So the auth function must make sure the row exists (as `budget_auth.py` does), or refuse the call.
- **Section 20b's `oidc_auth.py` stops working once a database is attached.** It returns `team_id=<group>`, and with a database the proxy looks that team up: every call got 404 `Team doesn't exist in db. Team=ml-eng`. Either create a LiteLLM team per IdP group, or clear `team_id` as `budget_auth.py` does.
- **The wait depends on the clock, not on when you ran out.** Alice waited 30 s in this run and 111 s in an earlier one. Both resets landed on an even minute (`05:10:00Z`, `05:08:00Z`).
- **With default settings, the block lifts up to 10 minutes late.** The reset job runs every 597–605 s by default, so `budget_reset_at` passing doesn't end the block until the job runs. The demo sets `proxy_budget_rescheduler_min_time`/`max_time` to 5–6 s. For monthly caps the default is fine.
- **The cap is checked before a call, so the last call goes over.** Spend stopped at $0.0000396 against a $0.00003 cap, the same overshoot as section 13. Concurrent calls can go over by more.
- **`/user/info` lags behind enforcement.** It showed `spend: 0.0` right after alice was refused, for the same reason as `/key/info` in section 13: spend reaches Postgres in batches.
- **An admin change sticks.** Raising alice's `max_budget` with `/user/update` took effect immediately, and her next sign-in didn't reset it, because provisioning only creates missing rows. To suspend someone, set `max_budget` to `0` (exercise 20.5). Don't delete their row: their next sign-in creates a fresh one. In my run, the first call after the delete was still refused (422), even though the new row showed `spend: 0.0`. The source suggests the proxy's spend counter for that `user_id` still held the old spend, but I didn't confirm it.
- **Virtual keys don't work on a `custom_auth` proxy.** `custom_auth` replaces the key check, so a personal `sk-...` key got 401 `invalid token (DecodeError)`. On a proxy without `custom_auth`, keys created with `"user_id": "alice"` share alice's cap (exercise 20.5).
- **A team key skips its owner's personal cap.** The proxy only checks a team key's user budget with `general_settings.apply_user_budget_to_team_keys: true` (exercise 20.6). Without it, a person over their own cap can keep spending through any team key they hold, up to the team's budget.
- **Several replicas need `coordination_redis`.** Enforcement reads a spend counter that is shared through Redis when it is configured. Each replica otherwise counts only its own calls, as with `rpm_limit` in section 21b. I took this from the source and did not run it with several replicas.

**Rows the proxy creates itself.** Some paths create user rows without your code: Admin UI SSO sign-in (free for up to 5 users), and JWT auth with `user_id_upsert` and SCIM (both Enterprise). Those rows take their budget from `litellm_settings.default_internal_user_params` (for example `{"max_budget": 20, "budget_duration": "1mo"}`). That's one budget for every new user, not one per group. I read this in the source and did not run it.

### 20c. Secret handling

A proxy in production holds these secrets. Each one has a different job, a different blast radius and a different rotation story:

| Secret | What it protects | If it leaks | Rotation |
| --- | --- | --- | --- |
| `LITELLM_MASTER_KEY` | Full admin access | The attacker can mint keys and read spend and config | With a salt key set: change the value and restart every proxy; on 1.110.2 do **not** call `/key/regenerate` with `new_master_key`, which would make stored credentials unreadable (20a). Without a salt key: back up the database, `/key/regenerate` with `new_master_key`, then restart with the new value |
| `LITELLM_SALT_KEY` | Encrypts provider credentials that are stored in the database (models and credentials added through the API or UI) | Combined with a database dump, every stored provider key | **Never change it** after the first credential is stored (shown below) |
| `DATABASE_URL` password | Keys, users, teams, spend logs, encrypted credentials | Hashed keys and spend data; prompts too, if you store them | Rotate in Postgres, then roll the proxies |
| Provider keys (`OPENAI_API_KEY` and so on) | Your provider accounts and bills | Direct provider use at your cost | At the provider, then in the secret store, then roll the proxies |
| Virtual keys | One app's or user's access | Whatever that key's scope allows | Issue, switch, block, delete (exercise 20.4) |
| Redis password, IdP client secrets | Shared counters; SSO | Tampered limits; SSO impersonation | Rotate in the service, then roll the proxies |

**Where the values come from.** In a config file, `os.environ/NAME` reads `NAME` when the proxy starts. With `key_management_system` set, the same `os.environ/NAME` references go to a secret manager instead:

| `key_management_system` | Store | Licence in 1.110.2 |
| --- | --- | --- |
| `aws_secret_manager` | AWS Secrets Manager | Free |
| `azure_key_vault` | Azure Key Vault (`AZURE_KEY_VAULT_URI`, `DefaultAzureCredential`) | Free |
| `custom` | Your own `CustomSecretManager` class | Free |
| `hashicorp_vault`, `google_secret_manager`, `cyberark` | HashiCorp Vault, Google Secret Manager, CyberArk | Enterprise |
| `aws_kms`, `google_kms` | AWS KMS, Google Cloud KMS | No licence check on these values in the source. The check is on KMS-encrypted environment values (`LITELLM_SECRET_AWS_KMS_*`); the docs' Enterprise page lists KMS |

The docs label AWS Secrets Manager and Azure Key Vault as Enterprise features too. "Free" above means that 1.110.2 does not enforce a licence for them, not that the docs grant it.

HashiCorp Vault is Enterprise-only as a built-in, but a 30-line `CustomSecretManager` reads it for free. [`examples/security/vault_secret_manager.py`](examples/security/vault_secret_manager.py) reads Vault's KV v2 API:

```python
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
```

[`examples/security/secrets_config.yaml`](examples/security/secrets_config.yaml):

```yaml
model_list:
  - model_name: chat
    litellm_params:
      model: openai/gpt-4o-mini
      api_base: http://127.0.0.1:4012/v1          # echo_upstream.py records the Authorization header
      api_key: os.environ/OPENAI_API_KEY          # resolved from Vault, not from the environment

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  store_model_in_db: true                         # models added with /model/new are saved, encrypted
  key_management_system: custom
  key_management_settings:
    custom_secret_manager: vault_secret_manager.VaultSecretManager
    access_mode: read_only
    hosted_keys: ["OPENAI_API_KEY"]               # only these names go to Vault; everything else stays env
```

[`fake_vault.py`](examples/security/fake_vault.py) stands in for Vault, and [`echo_upstream.py`](examples/security/echo_upstream.py) stands in for the provider; it records the `Authorization` header it receives, so you can see which key the proxy really sent. [`secrets_demo.py`](examples/security/secrets_demo.py) starts and restarts the proxy itself, five times, to show what happens to secrets over time. It takes about 3 minutes:

```bash
cd examples/security
uv run python echo_upstream.py 4012 &
docker exec litellm-tutorial-db psql -U postgres -c "CREATE DATABASE salted"
export LITELLM_MASTER_KEY=sk-master-demo DATABASE_URL=postgresql://postgres:demo@localhost:55432/salted
DB_CONTAINER=litellm-tutorial-db uv run python secrets_demo.py
```

```text
== 1. a publicly known master key is refused at boot
  exit 3: LiteLLM proxy refused to start: the master key is a publicly known default.
== 2. the provider key comes from Vault; OPENAI_API_KEY is not in the environment
  upstream received: Bearer sk-from-vault-1111   vault reads: {'openai-api-key'}
== 3. rotate the key in Vault
  before restart: Bearer sk-from-vault-1111
  after restart:  Bearer sk-rotated-3333
== 4. Vault unreachable at boot, a stale env value present
  upstream received: Bearer sk-stale-env-value
  log: - LiteLLM:ERROR: main.py:484 - Defaulting to os.environ value for key=OPENAI_API_KEY. An exception occurred - [
== 5. credentials saved through the API are encrypted with LITELLM_SALT_KEY
  stored api_key: lPG3nZZPRcR91FD1JcebYmuJztJSUzCQdDOvVIU-Nfn4...
  call with the original salt: Bearer sk-provider-secret-9999
  call after the salt changed: 400 /chat/completions: Invalid model name passed in model=db-chat-1795391095. Call `
  log: - LiteLLM Router:WARNING: registry.py:1318 - Error upserting deployment db-chat-1795391095 (id=ee511332-4967-4921-be8f-70dea1250a19): litellm.BadRequestError: LL
```

What each step means for production:

- **Step 1: the proxy refuses a known default master key.** With `sk-1234`, it exits with code 3 and prints a fix (`echo "sk-$(openssl rand -hex 32)"`). It also refuses an empty or unset key. It does **not** measure strength: `sk-master-demo`, used throughout this tutorial, starts fine. Generate the key; don't make one up.
- **Step 3: the proxy reads secrets once, at startup.** After the key changed in Vault, the running proxy kept sending the old one. Rotating a provider key means: add the new key at the provider, update the store, do a rolling restart of the proxies, then revoke the old key at the provider. Revoking first causes an outage.
- **Step 4: an unreachable secret store fails open.** With Vault down, LiteLLM logged an `ERROR` and quietly used `OPENAI_API_KEY` from the environment, a stale value here. Don't leave a variable with the same name in the proxy's environment, and alert on `Defaulting to os.environ value`.
- **Step 5: the salt key must never change.** Credentials added through `/model/new` (or the UI) are stored encrypted with `LITELLM_SALT_KEY`. After a restart with a different salt, the model silently vanished: the proxy logged a `WARNING` and clients got `400 Invalid model name`. Without `LITELLM_SALT_KEY`, the master key does the encrypting, which ties master-key rotation to re-encrypting those values. Set a salt key, separate from the master key, before the first credential is stored, and back it up like a database encryption key.
- **What lives in the database:** hashed virtual keys (20a), encrypted provider credentials, spend logs, and prompts only if you turn on `store_prompts_in_spend_logs` (section 21). Encrypt the database at rest, and restrict who can read `LiteLLM_SpendLogs`.

A checklist for secrets:

- [ ] Master key and salt key generated with `openssl rand`, different from each other, stored in the secret manager, never in the config file or the image.
- [ ] Config files use `os.environ/NAME` for every key, password and URL with credentials; exercise 20.3 lints for this.
- [ ] Provider access through workload identity where the cloud supports it (Bedrock, Azure, Vertex), static keys only where it doesn't.
- [ ] `LITELLM_MODE=PRODUCTION`, so the proxy doesn't load a stray `.env` file from its working directory (it does in the default `DEV` mode).
- [ ] No secret in a shell command line, a Dockerfile `ENV`, or CI logs; `docker run -e NAME` without a value, as in section 12.
- [ ] A runbook for rotating each secret in the table above, tried once before you need it.

**Clean up.** Stop each proxy from this section with Ctrl-C (ports 4101, 4102 and 4103), and the fake identity provider and echo upstream with `kill %1 %2`. `secrets_demo.py` starts and stops its own proxies (ports 4104 and 4105) and its fake Vault (4014), so a port clash there means something else is using one of them. Drop the extra database with `docker exec litellm-tutorial-db psql -U postgres -c "DROP DATABASE IF EXISTS salted"`; without that, a second run of the `CREATE DATABASE` line fails.

### Exercises

Exercises 20.1 and 20.4 need a proxy with a database: your `proxy_config.yaml` from exercise 12.1 with `DATABASE_URL` set, as in section 13. Use a strong master key (`sk-$(openssl rand -hex 32)`).

**20.1 ★ `ex20_1_least_privilege.py`: model an organisation**

Create two teams: `search` (models `fast`) and `research` (models `fast` and `smart`). Create internal users `sam` in `search` and `rita` in `research`, and an auditor with role `proxy_admin_viewer`. Issue an `llm_api` key for each team, valid for 30 days, a personal key for `sam` and `rita`, and a key for the auditor. Then try each boundary.

Checks:
- The `search` app key gets 200 on `fast` and 403 on `smart`; the `research` app key gets 200 on `smart`.
- An `llm_api` key gets 403 on `/key/generate`.
- The auditor gets 200 on `/key/list` and 403 on `/key/delete`.
- `sam` gets 403 when he creates a key for `rita`.
- A key created with `duration: "2s"` gets 401 three seconds later, and `/key/info` shows an `expires` value for the 30-day app keys.

<details><summary>Hint</summary>

Add a timestamp to team aliases and user IDs so the script can be re-run. `/user/new` takes `user_role` and `teams`; `/key/generate` takes `team_id`, `user_id`, `key_type` and `duration`.
</details>

**20.2 ★★ `ex20_2_idp.py` + `ex20_2_auth.py` + `ex20_2_oidc_gateway.py`: an Entra-style gateway that survives key rotation**

Write your own fake IdP whose tokens carry Entra-style app roles (`"roles": ["LLM.Basic"]` or `["LLM.Power"]`) instead of groups. It has a `POST /rotate` endpoint that adds a new signing key with a new `kid`, keeps the old key in the JWKS, and signs new tokens with the new key. Write a `custom_auth` that grants `LLM.Power` the models `fast` and `smart` with `rpm_limit: 100`, and `LLM.Basic` only `fast` with `rpm_limit: 3`. Then attack it.

Checks:
- `LLM.Power` gets 200 on `smart`; `LLM.Basic` gets 403 on `smart`.
- Five `LLM.Basic` calls for the same user, **each with a freshly issued token**, give `[200, 200, 200, 429, 429]`.
- After `/rotate`, a token signed with the new key is accepted within a few seconds, without restarting the proxy, and a token signed with the old key still works.
- A token with `alg: none`, and a token signed with HS256 using the IdP's public key as the HMAC secret, both get 401.

<details><summary>Hint</summary>

Return `api_key=f"oidc:{sub}"` so the limit follows the user rather than the token. Right after rotation, a new-key token can be refused: `PyJWKClient` won't refetch the JWKS within `cooldown_duration` (30 seconds by default) of its last fetch. Pass a smaller `cooldown_duration` and check again after it. For the forged tokens, base64url-encode a header and the claims yourself; `jwt.decode(..., algorithms=["RS256"])` is what refuses them.
</details>

**20.3 ★ `ex20_3_secret_hygiene.py`: lint a deployment for secret mistakes**

Write `lint(config: dict, env: dict) -> list[str]` that reports:

- any key named like `api_key`, `master_key`, `database_url`, `password`, `secret` or `token` whose value is a literal instead of `os.environ/...`;
- `allow_client_side_credentials: true` or `dangerously_permit_weak_or_unset_master_key: true` anywhere;
- a master key that is missing, shorter than 32 characters, not `sk-`-prefixed, or a known demo value;
- a missing `LITELLM_SALT_KEY`, or one equal to the master key;
- `LITELLM_MODE` not set to `PRODUCTION`.

Run it on a deliberately bad config and environment, a clean pair, and the tutorial's own [`examples/proxy/config.yaml`](examples/proxy/config.yaml).

Checks:
- The bad pair gives one finding per problem you planted; the clean pair gives `[]`.
- A salt key equal to the master key gives exactly that one finding.
- `examples/proxy/config.yaml` is flagged for the literal `api_key: sk-invalid` on `chat-broken`.

<details><summary>Hint</summary>

Walk the YAML tree recursively and keep the dotted path, so a finding reads `model_list[2].litellm_params.api_key`. `yaml.safe_load` is enough; never load a config with `yaml.load`.
</details>

**20.4 ★★ `ex20_4_rotation.py`: zero-downtime key rotation without a licence**

Write `rotate(old_key, new_alias) -> new_key`. It reads the old key with `/key/info`, issues a new key with the same `models`, `team_id`, `user_id`, `max_budget`, `rpm_limit`, `tpm_limit`, `key_type` and `metadata` (plus `rotated_from`), and leaves the old key working. Then run the full cycle: overlap, block the old key, delete it.

Checks:
- During the overlap, both keys get 200.
- After `/key/block`, the old key is refused (record the status code you get) and the new key gets 200.
- After `/key/delete`, the old key gets 401.
- The new key's `models`, `rpm_limit` and `max_budget` equal the old key's, and its metadata keeps the old owner.

<details><summary>Hint</summary>

Blocking before deleting gives you a reversible grace period: if a forgotten caller breaks, `/key/unblock` brings it back while you find it. `/key/regenerate` would do this in one call, but it is an Enterprise feature.
</details>

**20.5 ★ `ex20_5_shared_cap.py`: one person, several keys, one cap**

Run [`examples/proxy/config.yaml`](examples/proxy/config.yaml) with `DATABASE_URL` set (no `custom_auth`). Create users `dana` and `eve`, each with `max_budget: 0.00003` and `budget_duration: "1d"`. Give `dana` three keys: two plain ones, and one with its own `max_budget: 10`. Give `eve` one key. Spend `dana`'s budget with her first key, then try the others. Finally, suspend `eve` and restore her.

Checks:
- `dana`'s `budget_reset_at` is the next midnight UTC.
- Her first key gives `[200, 200, 200, 422, 422]`.
- Her second key then gets 422, and the message names `User=<dana's id>`.
- Her key with its own $10 budget also gets 422: the user cap still applies.
- `eve` gets 200, then 422 after `/user/update` with `max_budget: 0`, then 200 again after you restore her budget.

<details><summary>Hint</summary>

Pass `"auto_create_key": false` to `/user/new`, and `"user_id"` to `/key/generate`. Each `chat-cheap` mock call costs $0.0000132, so three calls go over $0.00003.
</details>

**20.6 ★★ `ex20_6_team_keys.py`: does the cap survive a team key?**

Create a user with `max_budget: 0.00003` and a team with no budget, add the user to the team, and issue a key with both `user_id` and `team_id`. Make six calls with it. Run the script twice: once against the plain `examples/proxy/config.yaml`, and once with `apply_user_budget_to_team_keys: true` added under `general_settings`. Accept `--capped` to tell the script which result to expect.

Checks:
- Without the setting, all six calls get 200: the personal cap doesn't apply to a team key.
- With the setting, they give `[200, 200, 200, 422, 422, 422]`.

<details><summary>Hint</summary>

The check is in `_user_max_budget_check` in `litellm/proxy/auth/auth_checks.py`: it returns early for a key whose team is set. Restart the proxy after changing `general_settings`.
</details>


## 21. Guardrails and hardening the proxy for production

**Use case:** prompts carry customer data, credentials pasted by mistake, and attempts to make the model ignore its instructions; replies can carry data back out. And a proxy reachable from your network needs TLS, a closed admin surface, more than one replica, and known behaviour when its database or Redis goes down. This section covers both halves: guardrails on the content (21a) and hardening the deployment (21b).

### 21a. Guardrails: checking what goes in and what comes out

A guardrail is a check the proxy runs on every request, on every response, or on both. It can **mask** (rewrite the text and carry on) or **block** (refuse with a 400). Guardrails are declared in the config, in a `guardrails:` list:

| Setting | Meaning |
| --- | --- |
| `guardrail` | The implementation: a built-in such as `litellm_content_filter`, a vendor integration such as `bedrock` or `presidio`, or `your_module.YourClass` |
| `mode` | When it runs: `pre_call` (before the model; can mask or block), `during_call` (in parallel with the model; can only block; the reply is held until the check finishes, so it adds latency only when the check is slower than the model), `post_call` (on the reply), `logging_only` (scans after the call and records a verdict without affecting the caller; with `presidio` it also masks what logging callbacks receive), plus `pre_mcp_call`, `during_mcp_call` and `post_mcp_call` for MCP tools. A list runs it at several points |
| `default_on` | `true`: runs on every request. `false`: runs only when the request asks for it with `"guardrails": ["name"]` in the body |

The integrations fall into four groups:

| Kind | Integrations (`guardrail:` value) | Needs |
| --- | --- | --- |
| Built into LiteLLM | `litellm_content_filter` (82 prebuilt regex patterns, keyword lists, about 30 categories including prompt injection, jailbreak, SQL injection and harmful content), `tool_permission`, `block_code_execution` | Nothing; runs inside the proxy |
| Your own code | `module.Class` subclassing `CustomGuardrail` | Nothing |
| Self-hosted models | `presidio` (Microsoft Presidio PII detection), `guardrails_ai` | Their own services |
| Cloud and vendor services | `bedrock` (Amazon Bedrock Guardrails), `azure/prompt_shield`, `azure/text_moderations`, `model_armor` (Google), `openai_moderation`, `lakera`, `aporia`, `pangea`, `panw_prisma_airs`, `cisco_ai_defense`, `crowdstrike_aidr`, `hiddenlayer`, `noma` and about 45 more | An account and an API call per check (latency and cost) |

[`examples/security/guardrails_config.yaml`](examples/security/guardrails_config.yaml) puts five guardrails in front of one model. The model is [`echo_upstream.py`](examples/security/echo_upstream.py), a fake provider that echoes the last user message (and returns a customer record when the prompt says `LEAK`), and records what it received:

```yaml
model_list:
  - model_name: chat
    litellm_params:
      model: openai/gpt-4o-mini
      api_base: http://127.0.0.1:4012/v1       # echo_upstream.py: replies with what it received
      api_key: os.environ/OPENAI_API_KEY

guardrails:
  - guardrail_name: pii-mask                    # mask personal data before it leaves your network
    litellm_params:
      guardrail: litellm_content_filter
      mode: pre_call
      default_on: true
      patterns:
        - {pattern_type: prebuilt, pattern_name: email, action: MASK}
        - {pattern_type: prebuilt, pattern_name: us_ssn, action: MASK}
        - {pattern_type: prebuilt, pattern_name: credit_card, action: MASK}
        - {pattern_type: regex, name: employee_id, pattern: 'EMP-\d{6}', action: MASK}

  - guardrail_name: secrets-block               # refuse requests that carry credentials
    litellm_params:
      guardrail: litellm_content_filter
      mode: pre_call
      default_on: true
      patterns:
        - {pattern_type: prebuilt, pattern_name: aws_access_key, action: BLOCK}
        - {pattern_type: prebuilt, pattern_name: github_token, action: BLOCK}

  - guardrail_name: prompt-injection            # keyword categories shipped with LiteLLM
    litellm_params:
      guardrail: litellm_content_filter
      mode: pre_call
      default_on: true
      categories:
        - {category: prompt_injection_jailbreak, action: BLOCK, severity_threshold: medium}
        - {category: prompt_injection_system_prompt, action: BLOCK, severity_threshold: medium}

  - guardrail_name: output-pii                  # mask what the model sends back
    litellm_params:
      guardrail: litellm_content_filter
      mode: post_call
      default_on: true
      patterns:
        - {pattern_type: prebuilt, pattern_name: email, action: MASK}
        - {pattern_type: prebuilt, pattern_name: us_ssn, action: MASK}

  - guardrail_name: topic-guard                 # your own code; opt-in per request, or per key with a licence
    litellm_params:
      guardrail: custom_guardrails.TopicGuard
      mode: pre_call

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

The custom guardrail, [`custom_guardrails.py`](examples/security/custom_guardrails.py), is a class with one hook:

```python
DENIED_TOPICS = ("medical diagnosis", "legal advice", "stock tips")


class TopicGuard(CustomGuardrail):
    """Block requests whose last user message mentions a denied topic."""

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        text = str(data.get("messages", [{}])[-1].get("content", "")).lower()
        for topic in DENIED_TOPICS:
            if topic in text:
                raise HTTPException(status_code=400, detail={"error": f"topic-guard: '{topic}' is out of scope"})
        return data
```

[`guardrails_client.py`](examples/security/guardrails_client.py) sends one prompt per case through the plain OpenAI SDK, streams one reply, and then asks the fake provider what it received:

```bash
cd examples/security
uv run python echo_upstream.py 4012 &
export LITELLM_MASTER_KEY=sk-master-demo OPENAI_API_KEY=sk-fake-upstream
uv run litellm --config guardrails_config.yaml --port 4100
LITELLM_KEY=sk-master-demo uv run python guardrails_client.py       # in another shell
```

```text
PII is masked           200  You said: Email [EMAIL_REDACTED] about [EMPLOYEE_ID_REDACTED], card [CREDIT_CARD_REDACTED]
credential blocked      400  [secrets-block] Content blocked: aws_access_key pattern detected
injection blocked       400  [prompt-injection] Content blocked: prompt_injection_system_prompt conditional match 'print + previous instructions' detected (severity: high)
jailbreak blocked       400  [prompt-injection] Content blocked: prompt_injection_jailbreak conditional match 'pretend + no restrictions' detected (severity: high)
output masked           200  Customer record: [EMAIL_REDACTED], SSN [US_SSN_REDACTED]
opt-in guard off        200  You said: Any stock tips for tomorrow?
opt-in guard on         400  [topic-guard] topic-guard: 'stock tips' is out of scope
client opt-out ignored  200  You said: mail [EMAIL_REDACTED]

applied: pii-mask,secrets-block,prompt-injection,output-pii
streamed: Customer record: [EMAIL_REDACTED], SSN [US_SSN_REDACTED]

what the provider received:
   Email [EMAIL_REDACTED] about [EMPLOYEE_ID_REDACTED], card [CREDIT_CARD_REDACTED]
   LEAK the last customer record
   Any stock tips for tomorrow?
   mail [EMAIL_REDACTED]
   LEAK it again, streamed
```

How to read this:

- **Masking happens before the data leaves.** The provider received `[EMAIL_REDACTED]`, never the address. That is the point of `pre_call` masking: the provider, its logs and its retention policy never see the value.
- **Blocked requests cost nothing.** The credential, injection and topic prompts are missing from the provider's list: a `pre_call` block refuses the request before the model is called. The 400 body names the guardrail (`provider_specific_fields.guardrail_name`) and the rule that matched, so clients and dashboards can tell a guardrail refusal from a malformed request.
- **Output guardrails cover what the model invents or retrieves.** The `LEAK` prompt was clean, but the reply carried an email and an SSN, and `post_call` masked both. Streaming is covered too: the content filter holds back the first chunks (they arrived empty) until it can scan enough text, then sends the masked text.
- **Clients can't turn a `default_on` guardrail off.** `"metadata": {"disable_global_guardrails": true}` in the request was ignored. Only an admin can exempt a key or team (`disable_global_guardrails` or `opted_out_global_guardrails` in its metadata), and per-key guardrail settings are Enterprise-only in 1.110.2.
- **`x-litellm-applied-guardrails`** lists the guardrails that ran on a request. Log it, or assert it in a smoke test, to catch a config change that silently dropped one.
- **Keyword categories are a first line, not a defence.** `prompt_injection_*` matches known phrasings ("ignore all previous instructions", "pretend + no restrictions"). Rewording gets through, and an innocent prompt that mentions a phrase gets blocked. Treat them as a cheap filter for the obvious cases. Put the real defence in what the model is *allowed to do*: tool permissions (section 15's per-key MCP grants), authorization outside the model (section 5), and model-based classifiers such as Bedrock Guardrails, Azure Prompt Shields or Lakera where the risk justifies the latency.
- **Test prebuilt patterns against your own data.** Exercise 21.1 finds that the prebuilt `iban` pattern misses the printed form with spaces (`GB82 WEST 1234 ...`), and that `us_phone` leaves the opening bracket of `(415) 555-0134`. Add a `regex` pattern for every format you actually see.
- **Choose the mode by what the check needs.** Masking must be `pre_call` (`during_call` with `MASK` is flagged as unstable in the source). A slow vendor check that only blocks can run `during_call`, alongside the model, so it adds latency only when it is slower than the model. A response check is `post_call`. `logging_only` never changes what the caller sees: with Presidio it keeps PII out of your logging platforms, and with other guardrails it only records a verdict in the log record.

**Cloud guardrail services** use the same config shape. For example, Amazon Bedrock Guardrails, using the proxy's AWS identity (not run here):

```yaml
guardrails:
  - guardrail_name: bedrock-pii-and-topics
    litellm_params:
      guardrail: bedrock
      mode: [pre_call, post_call]
      guardrailIdentifier: <guardrail-id>
      guardrailVersion: "1"
      aws_region_name: us-west-2
      default_on: true
```

### 21b. Hardening the deployment

First, find out what a default proxy exposes. [`examples/security/hardening_check.py`](examples/security/hardening_check.py) audits a running proxy from outside. It needs one valid key; the run below passes the master key, and the production run later uses an ordinary key:

```python
for path, what, marker in (("/", "Swagger UI", "swagger"), ("/redoc", "ReDoc", "redoc"),
                           ("/openapi.json", "OpenAPI schema", "openapi"), ("/ui/", "admin UI", "<html")):
    r = get(path)
    check(f"{what} hidden", r.status_code != 200 or marker not in r.text[:5000].lower(), f"GET {path} -> {r.status_code}")
...
r = chat(api_base="http://169.254.169.254/latest/meta-data")
check("client api_base rejected (SSRF)", r.status_code in (400, 401, 403), f"-> {r.status_code}")
...
ok = chat()
check("version not advertised", "x-litellm-version" not in ok.headers, ...)
check("upstream address not leaked", "x-litellm-model-api-base" not in ok.headers, ...)
```

Against the guardrails proxy from 21a, which has default settings:

```bash
PROBE_KEY=sk-master-demo uv run python hardening_check.py http://localhost:4100
```

```text
FAIL  served over TLS                  http
FAIL  Swagger UI hidden                GET / -> 200
FAIL  ReDoc hidden                     GET /redoc -> 200
FAIL  OpenAPI schema hidden            GET /openapi.json -> 200
FAIL  admin UI hidden                  GET /ui/ -> 200
PASS  LLM routes need a key            GET /v1/models without key -> 401
PASS  default key sk-1234 refused      -> 400
PASS  metrics need a key               GET /metrics/ -> 401
PASS  client api_base rejected (SSRF)  -> 401
PASS  client base_url rejected         -> 401
FAIL  CORS limited to known origins    allow-origin: *
FAIL  version not advertised           x-litellm-version: 1.110.2
FAIL  upstream address not leaked      x-litellm-model-api-base: http://127.0.0.1:4012/v1

5/13 checks passed
```

The good news first: authentication, metrics and the request-body check are safe by default. A client that sends its own `api_base` or `base_url`, which would make the proxy send its provider key to the client's server, is refused unless an admin sets `allow_client_side_credentials`. The rest is exposure you have to close yourself, and environment variables alone don't close all of it (exercise 21.3):

| Exposure | Setting | Enough on its own? |
| --- | --- | --- |
| Swagger UI at `/` | `NO_DOCS=True` | Yes; `/` then returns `"LiteLLM: RUNNING"` |
| ReDoc at `/redoc` | `NO_REDOC=True` | Yes |
| The 2 MB OpenAPI schema at `/openapi.json` | `NO_OPENAPI=True` | Yes: it then returns 404. `NO_DOCS` and `NO_REDOC` alone leave it served, as the run above shows. Block it at the edge as well |
| The admin UI at `/ui` | `DISABLE_ADMIN_UI=True` | Partly: sign-in and SSO return a "disabled" page, but the UI's static files are still served; block `/ui` at the edge |
| CORS `*` | `LITELLM_CORS_ORIGINS=https://app.example.com` | Yes (credentials stay off with `*`) |
| `x-litellm-version`, `x-litellm-model-api-base` and other response headers | none in OSS | No: strip them at the edge |
| Request body size | `max_request_size_mb` | Enterprise only; without a licence it is logged and ignored. Cap it at the edge |
| Plain HTTP | `--ssl_certfile_path` / `--ssl_keyfile_path` | Works, but TLS usually terminates at a load balancer or ingress |
| Listening on every interface | `--host 127.0.0.1` | Yes; the proxy binds `0.0.0.0` by default |

So a production proxy sits behind an edge proxy (nginx, an ingress controller, or a cloud load balancer with a WAF) that terminates TLS and closes what LiteLLM can't. [`examples/security/prod/`](examples/security/prod/) is a complete reference stack:

```text
           127.0.0.1:8443 (TLS)
                 |
          +------+------+    edge network (10.89.0.0/24)
          |    nginx    |    TLS, HSTS, 2 MB body cap, per-IP flood limit,
          +------+------+    /ui /docs /openapi.json blocked, version headers stripped
                 |
       +---------+---------+
       |                   |
  +----+----+         +----+----+    litellm-non_root image (uid 65534), no capabilities,
  | proxy-1 |         | proxy-2 |    LITELLM_MODE=PRODUCTION, 2 workers each, no published port
  +----+----+         +----+----+
       |  backend network (internal: no internet route)
  +----+-------+--------------+-------------+
  | Postgres   | Redis        | upstream    |
  | keys/spend | shared limits| (stand-in   |
  |            | requirepass  |  provider)  |
  +------------+--------------+-------------+
```

[`prod/prod_config.yaml`](examples/security/prod/prod_config.yaml):

```yaml
litellm_settings:
  request_timeout: 120                        # seconds per provider call; the default is 6000
  num_retries: 2
  turn_off_message_logging: true              # prompts and replies never reach logging callbacks
  redact_user_api_key_info: true              # no key hashes or aliases in logs and traces
  json_logs: true

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  database_connection_pool_limit: 10          # per worker; replicas x workers x 10 must fit Postgres max_connections
  proxy_batch_write_at: 10
  allow_requests_on_db_unavailable: false     # true would admit requests whose keys can't be checked
  store_prompts_in_spend_logs: false
  coordination_redis:                         # shared counters: limits and budgets hold across replicas
    host: os.environ/REDIS_HOST
    port: 6379
    password: os.environ/REDIS_PASSWORD
  trusted_proxy_ranges: ["10.89.0.0/24"]      # nginx's network: trusted for identity headers and the sign-in limit
  use_x_forwarded_for: true
```

The proxy service in [`prod/docker-compose.yml`](examples/security/prod/docker-compose.yml) (the file also defines Postgres, Redis, the stand-in provider and nginx, with every password required from the shell):

```yaml
  proxy:
    image: ghcr.io/berriai/litellm-non_root:v1.110.2   # runs as uid 65534, not root
    command: ["--config", "/app/config.yaml", "--port", "4000", "--num_workers", "2"]
    deploy:
      replicas: 2
    volumes: [./prod_config.yaml:/app/config.yaml:ro]
    environment:
      LITELLM_MODE: PRODUCTION                # do not read a .env file from the working directory
      LITELLM_MASTER_KEY: ${LITELLM_MASTER_KEY:?export LITELLM_MASTER_KEY}
      LITELLM_SALT_KEY: ${LITELLM_SALT_KEY:?export LITELLM_SALT_KEY}
      DATABASE_URL: postgresql://postgres:${POSTGRES_PASSWORD}@db:5432/litellm
      REDIS_HOST: redis
      REDIS_PASSWORD: ${REDIS_PASSWORD}
      NO_DOCS: "True"
      NO_REDOC: "True"
      NO_OPENAPI: "True"
      DISABLE_ADMIN_UI: "True"
      LITELLM_CORS_ORIGINS: https://chat.example.com
    security_opt: ["no-new-privileges:true"]
    cap_drop: [ALL]
    networks: [backend, edge]
```

And the parts of [`prod/nginx.conf`](examples/security/prod/nginx.conf) that do LiteLLM's missing work:

```nginx
    client_max_body_size 2m;                          # max_request_size_mb is Enterprise-only in LiteLLM
    limit_req zone=perip burst=40 nodelay;            # coarse per-IP flood control in front of key limits

    location ~ ^/(ui|docs|redoc|openapi\.json|routes)(/|$) { return 404; }

    location / {
      proxy_pass http://litellm;
      proxy_set_header X-Forwarded-For $remote_addr;   # overwrite, never append a client-sent value
      proxy_buffering off;                             # stream tokens as they arrive
      proxy_read_timeout 300s;
      proxy_hide_header x-litellm-version;             # no OSS setting removes these
      proxy_hide_header x-litellm-model-api-base;
      proxy_hide_header x-litellm-model-id;
      proxy_hide_header llm_provider-server;
    }
```

Start it:

```bash
cd examples/security/prod
./gen_certs.sh                                     # a demo CA and a localhost certificate
chmod 644 prod_config.yaml nginx.conf ../echo_upstream.py
export POSTGRES_PASSWORD=$(openssl rand -hex 16) REDIS_PASSWORD=$(openssl rand -hex 16)
export LITELLM_MASTER_KEY=sk-$(openssl rand -hex 32) LITELLM_SALT_KEY=sk-$(openssl rand -hex 32)
docker compose up -d --wait                        # about 50 s
APP=$(curl -s --cacert certs/ca.crt https://localhost:8443/key/generate -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' -d '{"models":["chat"]}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["key"])')
cd .. && PROBE_KEY=$APP PROBE_CA=prod/certs/ca.crt uv run python hardening_check.py https://localhost:8443
```

```text
PASS  served over TLS                  https
PASS  Swagger UI hidden                GET / -> 200
PASS  ReDoc hidden                     GET /redoc -> 404
PASS  OpenAPI schema hidden            GET /openapi.json -> 404
PASS  admin UI hidden                  GET /ui/ -> 404
PASS  LLM routes need a key            GET /v1/models without key -> 401
PASS  default key sk-1234 refused      -> 401
PASS  metrics need a key               GET /metrics/ -> 401
PASS  client api_base rejected (SSRF)  -> 401
PASS  client base_url rejected         -> 401
PASS  CORS limited to known origins    allow-origin: None
PASS  version not advertised           x-litellm-version: None
PASS  upstream address not leaked      x-litellm-model-api-base: None

13/13 checks passed
```

The probe only sees the outside. [`prod/prod_checks.py`](examples/security/prod/prod_checks.py) checks the inside too: two replicas sharing one limit, the body cap, the logs, the containers, and a database outage:

```bash
cd prod && uv run python prod_checks.py
```

```text
== 1. TLS only at the edge
  plain HTTP to the TLS port -> 400
  HTTPS -> 200  server: nginx  hsts: max-age=31536000
== 2. one rate limit across two replicas (coordination Redis)
  10 calls, rpm_limit 4: [200, 200, 200, 200, 429, 429, 429, 429, 429, 429]
  calls handled per replica: [5, 5]
== 3. request size capped at the edge
  3 MB body -> 413
== 4. logs are JSON, without prompts or keys
  prompt text in logs: False   key in logs: False
  lines that say REDACTED: 0
  sample: {"message": "gc.freeze pinned 2164534 startup objects", "level": "WARNING", "timestamp": "2026-11-23T00:26:20.244743", "component"
== 5. containers
  proxy uid: 65534   effective capabilities: 0000000000000000
  backend-only container reaching the internet: urllib.error.URLError: <urlopen error [Errno -3] Temporary failure in 
== 6. the database goes away
  /health/readiness -> 503 {"status":"healthy","db":"disconnected"}
  a key no replica has cached -> 503
```

What I learned running it, in the order you'll meet it:

- **The non-root image can't read a `600` file.** The first `docker compose up` failed: both replicas exited with `PermissionError: [Errno 13] Permission denied: '/app/config.yaml'`. My umask is `077`, so every new file is `600`, and uid 65534 in the container can't read a host file owned by me. The root image used in sections 12 and 13 hides this. Make mounted config `644` (no secrets are in it, because they come from the environment), or build an image with the config baked in.
- **Python 3.13 rejects a CA certificate without key-usage extensions.** My first `gen_certs.sh` produced a CA that `openssl s_client` and curl accepted, but httpx refused with `CA cert does not include key usage extension`. Python 3.13 turns on strict X.509 checking. A real CA is fine; a home-made one needs `basicConstraints=critical,CA:TRUE` and `keyUsage=critical,keyCertSign,cRLSign`.
- **One limit across replicas needs Redis, and Redis is quietly optional.** With `coordination_redis`, `rpm_limit: 4` allowed exactly 4 of 10 calls spread over both replicas. Without Redis, each replica counts alone: the same test allowed 8, so every limit and budget is multiplied by the number of replicas. Also, LiteLLM falls back to any `REDIS_HOST`/`REDIS_PORT` it finds in the environment, so removing the config block alone didn't turn sharing off. Use the explicit `coordination_redis` block, which fails at startup if Redis is unreachable, instead of relying on the fallback, which silently does nothing if it can't connect.
- **A Redis outage fails open.** With Redis stopped, requests kept flowing, and each replica enforced its own counter again (8 of 10 allowed). A circuit breaker opens after 5 Redis failures and stays open for 60 seconds (`REDIS_CIRCUIT_BREAKER_RECOVERY_TIMEOUT`), so sharing doesn't resume the moment Redis is back. Right after Redis came back, a check still allowed 8 calls. On 1.109.1 it was back to 4 a minute later; on 1.110.2, whose Redis calls go through new Rust stores with one shared breaker, recovery was slower: 5 or 6 of 10 were allowed at 65 seconds, 5 at 130 seconds, and 4 again by 200 seconds, in two runs. Alert on `Redis circuit breaker OPENED` and `circuit breaker is open` in the logs.
- **A database outage fails closed, except for cached keys.** With Postgres stopped, a key no replica had seen got 503 (`the authentication database is temporarily unreachable`). A key a replica had already cached kept working on that replica. `allow_requests_on_db_unavailable: true` would admit unknown keys too; keep it `false` unless availability matters more than access control.
- **Read the readiness status code, not the body.** `/health/readiness` returned **503** with the body `{"status":"healthy","db":"disconnected"}`. Kubernetes and load balancers go by the code, which is right; a script that parses `status` would be fooled. Use `/health/liveliness` for liveness and `/health/readiness` for readiness. Don't use `/health` for either: it calls every model, which costs money and fails when a provider has a bad minute.
- **`allowed_ips` only matches exact strings, and needs a licence.** Without one the proxy refuses to start (section 20's licence table). With one, it compares the client address against the list with `in`, so `10.0.0.0/8` matches nothing. List exact addresses, or filter by network at the edge or with security groups. Behind a load balancer, the client address is the load balancer's unless `use_x_forwarded_for` is on. In 1.110.2 the `allowed_ips` check then reads `X-Forwarded-For` from any caller, and `trusted_proxy_ranges` does not restrict it: that setting covers header-based identity and the Admin UI sign-in limit. So the header is only trustworthy when nothing but your edge can reach the proxy and the edge overwrites it, as the nginx config here does.
- **No prompt or key reached the logs.** `turn_off_message_logging` keeps prompts out of every logging callback: the prompt marker in step 4 appeared nowhere in the proxy logs, and neither did the key. In 1.109.1 the rate-limit warnings from step 2 named the key as `REDACTED` (`429: Rate limit exceeded for REDACTED`); 1.110.2 writes no warning for a rate-limited request, only the `429` in the access log, so no line in this run named a key at all.
- **Count replicas over one connection.** nginx runs a worker per CPU, and each worker round-robins on its own, so separate connections can all land on the same replica. `prod_checks.py` sends its calls over one connection; with a new connection per call, step 2 showed `[10, 0]` as often as `[5, 5]`.

**A production checklist.** Everything above, plus the items from sections 12–20 that matter in production:

| Area | Do this | Section |
| --- | --- | --- |
| Network | TLS at the edge; the proxy on a private network, bound to it, with no published port; database and Redis on a network with no internet route | 21b |
| Edge | Block `/ui`, `/docs`, `/redoc`, `/openapi.json` and `/routes`; strip `x-litellm-version` and `x-litellm-model-api-base`; cap the body size; per-IP flood limit; overwrite `X-Forwarded-For` | 21b |
| Proxy settings | `NO_DOCS`, `NO_REDOC`, `NO_OPENAPI`, `DISABLE_ADMIN_UI` (or SSO), `LITELLM_CORS_ORIGINS`, `LITELLM_MODE=PRODUCTION`, `request_timeout` | 21b |
| Credentials | Generated master and salt keys from a secret manager; `os.environ/` in config; workload identity for providers | 20c |
| Access | Teams own model lists; apps get `llm_api` keys with an expiry and a budget; people sign in through the IdP | 20a, 20b |
| Content | `pre_call` masking of PII and credentials, `post_call` output checks, injection filters plus a stronger classifier where the risk warrants it | 21a |
| Scale | At least two replicas; `coordination_redis` so limits and budgets hold; `database_connection_pool_limit` × workers × replicas within Postgres's `max_connections` | 21b, 13 |
| Failure | Known behaviour when Postgres, Redis, the secret store or a provider is down (exercise 21.4); fallbacks across providers | 21b, 20c, 7 |
| Data | `turn_off_message_logging`, `redact_user_api_key_info`, `store_prompts_in_spend_logs: false`, database encrypted at rest, retention on spend logs | 18, 21b |
| Observability | JSON logs, Prometheus `/metrics` behind a key, OTel traces; alerts on 5xx, 429 rate, `Defaulting to os.environ`, `circuit breaker is open` | 18, 21b |
| Supply chain | Pin the image tag (better, its digest) and the Python package; run the non-root image; read the release notes before upgrading, because LiteLLM ships often | 12, 21b |

**Clean up.** Stop the guardrails proxy (port 4100) with Ctrl-C and the echo upstream with `kill %1`. Remove the production stack from `examples/security/prod` with `docker compose down -v`, which also deletes its Postgres volume.

### Exercises

Exercises 21.1 and 21.2 use one proxy. Run [`examples/security/echo_upstream.py`](examples/security/echo_upstream.py) `4012` as the provider, with a model `fast` that points at `http://127.0.0.1:4012/v1` (the section's own examples call theirs `chat`). If the echo upstream from 21a is still running on 4012, don't start it again. Exercise 21.4 needs the stack from [`examples/security/prod/`](examples/security/prod/).

**21.1 ★ `ex21_guardrails.yaml` + `ex21_1_guardrails.py`: guardrails for a support desk**

Write guardrails that:

- mask US phone numbers and IBANs before the call;
- block any prompt that mentions the unreleased product `project-titan`, whatever the capitalisation;
- mask email addresses in replies.

Send a prompt with a phone number and an IBAN **written in groups of four with spaces**, as on a printed statement; a prompt asking about `Project-Titan`; and `LEAK`. Then compare the replies with what the provider received.

Checks:
- The provider received neither the phone number nor the IBAN.
- The codename prompt gets a 400 naming your guardrail, and never reaches the provider.
- The `LEAK` reply contains no email address.

<details><summary>Hint</summary>

`blocked_words: [{keyword: project-titan, action: BLOCK}]` matches case-insensitively. Check what the prebuilt `iban` pattern actually matches: the regexes are in `litellm/proxy/guardrails/guardrail_hooks/litellm_content_filter/patterns.json`. If the spaced form gets through, add a `pattern_type: regex` entry of your own.
</details>

**21.2 ★★ `ex21_2_custom_guardrail.py`: a guardrail that works both ways**

Write one `CustomGuardrail` class, registered with `mode: [pre_call, post_call]` and `default_on: true`, that:

- before the call, refuses any request whose messages together are longer than 2,000 characters (a cost guard);
- after the call, replaces any hostname ending in `.corp.internal` in the reply with `[internal-host]`.

Checks:
- A 2,500-character prompt gets a 400 naming your guardrail, and doesn't reach the provider.
- `"ping build01.corp.internal please"` reaches the provider unchanged (it is the request), but the reply the client gets says `[internal-host]`.
- Short, clean prompts are unaffected.

<details><summary>Hint</summary>

Implement `async_pre_call_hook` (raise `HTTPException(400, ...)` to block) and `async_post_call_success_hook(self, data, user_api_key_dict, response)`, which can edit `response.choices[i].message.content` and return the response. The proxy already checks `default_on` and per-request selection before it calls a hook, which is why `TopicGuard` above has no such check; call `self.should_run_guardrail(data, GuardrailEventHooks.<mode>)` yourself only if you invoke the class outside the proxy.
</details>

**21.3 ★ `ex21_3_audit.md`: harden your own proxy**

Run `hardening_check.py` against your `proxy_config.yaml` from exercise 12.1, started with `uv run litellm`. That config has no `chat` model, so tell the probe which model to call: `PROBE_MODEL=fast`. Record the result. Then restart it with `--host 127.0.0.1` and only environment variables (`NO_DOCS`, `NO_REDOC`, `NO_OPENAPI`, `DISABLE_ADMIN_UI`, `LITELLM_CORS_ORIGINS`, `LITELLM_MODE`), and run the probe again. Write down which checks still fail, and why each one needs an edge proxy.

Checks:
- After the restart, Swagger UI, ReDoc, the OpenAPI schema and CORS pass.
- `/ui/`, `x-litellm-version` and `x-litellm-model-api-base` still fail; your notes say what in nginx (or your ingress) fixes each.
- `ss -ltn` shows the proxy listening on `127.0.0.1` only.

<details><summary>Hint</summary>

Compare what `GET /ui/` returns with and without `DISABLE_ADMIN_UI`, and try `GET /sso/key/generate` in both cases: the variable turns off sign-in, not the static files.
</details>

**21.4 ★★ `ex21_4_drills.py`: failure drills**

Against the `prod/` stack, write a script that:

1. creates a key with `rpm_limit: 4` and sends 10 calls;
2. stops Redis (`docker compose stop redis`), sends 10 calls with a fresh `rpm_limit: 4` key, then starts Redis again;
3. warms a key on both replicas, stops Postgres, then checks `/health/readiness`, the warm key and a key nobody has seen, and starts Postgres again.

Use `try`/`finally` so the stack is always restored.

Checks:
- Step 1 allows exactly 4 calls.
- Step 2 allows more than 4: the limit fails open to per-replica counters.
- In step 3, readiness is 503, the unknown key gets 503, and the warm key still gets 200.
- Run step 1 again right after step 2, then again 60 seconds later, and explain the difference in a comment.

<details><summary>Hint</summary>

The proxy wraps Redis in a circuit breaker (`REDIS_CIRCUIT_BREAKER_RECOVERY_TIMEOUT`, 60 seconds by default). To see the replica-local behaviour without stopping Redis, run the stack with a copy of `prod_config.yaml` that has no `coordination_redis` block **and** with `REDIS_HOST` removed from the proxy's environment; otherwise the environment fallback quietly re-enables sharing.
</details>


## 22. Context and memory management

**Use case:** a support assistant, or an agent that runs for hours, has more history, documents and tool output than fits in one request. It should remember a user's preferences next week, without paying for every past token on every call.

LiteLLM is a gateway, not a memory system, so it covers only part of this. This section first explains the ideas independently of any library (22a), then shows what LiteLLM does for context (22b) and for memory (22c), and what your application has to build itself. The concepts follow my note [Quick notes: context and memory in modern AI systems](https://chuan2019.github.io/posts/quick-notes-context-and-memory-in-modern-ai-systems/) (also [on Medium](https://chuan-zhang.medium.com/quick-notes-context-and-memory-in-modern-ai-systems-057ca9dfd337)), which has the reasoning and references behind them.

### 22a. The concepts: context, memory, and the system around them

**Context** is what the model sees on the current call: one bounded sequence of tokens that holds the system prompt, tools, history, retrieved notes, tool results and the new message. **Memory** is anything that survives after the call returns. The model itself is stateless. Memory changes its behaviour only when the application stores something and later loads part of it back into the context. So every memory system comes down to two pipelines around the model:

- **Write path:** after a turn, decide what to keep, in what form, and in which store.
- **Read path:** before a turn, decide what to fetch and how to fit it into the token budget. The last step of the read path, choosing, ordering and formatting the tokens that go into the window, is **context engineering**.

A computer is a useful analogy:

| Computer | AI system | What it means for design |
| --- | --- | --- |
| Firmware | Model weights | General skills and world knowledge. Fixed unless you fine-tune. |
| RAM | Context window | Fast, small, and wiped after every call. Everything the model uses must be here. |
| CPU cache | KV cache and prompt cache | Makes repeated prefixes cheaper and faster. Changes nothing about what the model knows. |
| Disk | Memory stores | Large and durable, but useless until loaded into RAM. |

Where memory can live, and how long it lasts:

| Store | Holds | Lives for | Typical form |
| --- | --- | --- | --- |
| Session (short-term) | Recent turns, plus a summary of older ones | One conversation | A list of messages; a row per session |
| Long-term, **episodic** | What happened: events, outcomes, past tasks | Months; mostly appended | Timestamped records, searchable by meaning |
| Long-term, **semantic** | What is true: facts and preferences | Until it changes; updated in place | Key-value entries or embedded facts |
| Long-term, **procedural** | How to act: system prompts, skills, tool definitions, playbooks | Versioned like code | Prompt files (section 17), skills (section 16a), tool lists |

The terms episodic, semantic and procedural come from the CoALA framework. Two things are often mistaken for memory and are not: a prompt cache (it lowers cost and latency, but the model knows nothing more), and a bigger context window (it raises the ceiling for one call, but nothing survives it).

The usual architecture puts a read path, an agent loop and a write path around the stateless model:

```mermaid
%% fig: memory
flowchart LR
    U["User message"] --> O["Orchestrator<br/>your app"] --> CA["Context assembler<br/>budget, order, cache"] --> L["LLM<br/>stateless"] --> R["Reply"]
    O --> RET["Retriever<br/>many candidates"] -->|"best few"| CA
    L <--> T["Tools<br/>incl. a memory tool"]
    R --> X["Extract, consolidate<br/>in the background"]
    subgraph S["Memory stores (outside the model)"]
        SS["Session store"]
        LT["Long-term store"]
        PR["Procedural"]
    end
    S -->|"read path"| RET
    T <-.->|"agent loop"| S
    X -.->|"write path"| S
```

- **The per-call loop** (top row) runs on every request and decides latency. The retriever aims for **recall**: fetch many candidates. The context assembler aims for **precision**: inject only the best few that fit the budget.
- **The agent loop** lets the model read and write memory itself in the middle of a turn, through a memory tool.
- **The background loop** (the write path) extracts and consolidates what to keep after the reply has gone, so it adds no latency for the user.

The context techniques, each with its cost:

| Technique | What it does | Trade-off |
| --- | --- | --- |
| Measure and budget | Count tokens per part (rules, memories, history, question) against the window, leaving room for the output | Needs the right tokenizer and window size per model |
| Sliding window | Drop the oldest turns | Cheap, but forgets facts stated early |
| Summarise (compaction) | Fold old turns into a rolling summary | Lossy, and costs a model call; keep the summary bounded by rewriting it, not appending to it |
| Retrieve | Fetch only the relevant memories or documents | Needs a relevance threshold; top-k always returns k items, relevant or not |
| Clear old tool results | Drop bulky tool output once it has been used | The model can no longer reread it, so keep a pointer or a memory of it |
| Order for caching | Stable parts first (tools, rules), volatile parts last (memories, the new message) | Anything that changes in the prefix, such as a timestamp, breaks the cache |
| A bigger window | Route an oversized request to a model that can hold it | More cost and latency; models also use the middle of a long context poorly ("lost in the middle") |

And the questions to settle early for memory:

- **Who writes it?** A pipeline (predictable and testable), or the agent through a tool (flexible, harder to bound). Many systems do both: they always inject a small profile and let the agent fetch the rest on demand.
- **When is it written?** In the hot path (available on the next turn, adds latency), or in the background (no latency, may arrive a turn later).
- **Whose is it?** Scope every entry to a user, team or tenant, and check that scope on every read. A memory that leaks across users is a data breach, not a bug.
- **How do you know it helps?** Measure recall on questions it should answer, the rate of irrelevant injections, and task success with and without memory. Unevaluated memory can quietly make answers worse.

### 22b. Context management with LiteLLM

LiteLLM sits on the read path, at the moment the request goes to the provider. Here is what it offers for each technique in 1.110.2:

| Technique | LiteLLM feature | Where | Notes |
| --- | --- | --- | --- |
| Measure | `get_model_info(model)["max_input_tokens"]`, `token_counter(model=..., messages=...)` | SDK | Works with provider-prefixed names |
| Sliding window | `trim_messages(messages, max_tokens=N)` from `litellm.utils` | SDK | Keeps the system message and trailing tool messages. Not exported as `litellm.trim_messages`, and `model="bedrock/..."` silently trims nothing |
| Summarise | Nothing general. You call a cheap model through LiteLLM yourself | SDK | Example below |
| Summarise, server side | `context_management` with `compaction` (OpenAI style) or `compact_20260112` (Anthropic style) | SDK, proxy | Passed to the Anthropic API, to `bedrock/invoke/`, and (`compact_20260112` only) to Bedrock Converse |
| Summarise, automatically | `context_compaction` in the complexity router | Router, proxy | Only behind `auto_router/complexity_router`, and the summarising model must be on the Anthropic API |
| Clear old tool results | `context_management` with `clear_tool_uses_20250919` | SDK, proxy | The Anthropic API and `bedrock/invoke/`; dropped on Bedrock Converse |
| Order for caching | `cache_control` on content blocks, or `cache_control_injection_points` | SDK, proxy | Translated to Anthropic `cache_control` or Bedrock `cachePoint`. Not the response cache of section 9 |
| A bigger window | `Router(enable_pre_call_checks=True)` and `context_window_fallbacks` | Router, proxy | Pre-call checks skip deployments whose `max_input_tokens` is too small |
| A clear failure | `ContextWindowExceededError` | SDK, proxy | Every provider's "too long" error becomes this one type, so one handler covers them all |

[`22a_context_budget.py`](examples/22a_context_budget.py) runs offline:

```python
"""Context management with the SDK: measure the window, trim, compact into a summary, and fall back to a bigger window."""
import litellm
from litellm import Router, get_model_info, token_counter
from litellm.utils import trim_messages

from _mock import mock

FAST, BIG = "anthropic/claude-haiku-5-5", "anthropic/claude-opus-5-5"
SYSTEM = {"role": "system", "content": "You are a release assistant. Answer in one line."}
HISTORY = [{"role": "user" if i % 2 == 0 else "assistant",
            "content": f"Turn {i}: " + ("notes about the payments release " * 25)} for i in range(12)]
QUESTION = {"role": "user", "content": "Which date did we pick for the release?"}

print("== 1. how big is the window, and how full is it?")
info = get_model_info(FAST)
print(f"{FAST}: input {info['max_input_tokens']:,} tokens, output {info['max_output_tokens']:,}")
messages = [SYSTEM, *HISTORY, QUESTION]
print("this request:", token_counter(model=FAST, messages=messages), "tokens in", len(messages), "messages")

print("== 2. trim_messages drops the oldest turns, keeps the system message")
trimmed = trim_messages(messages, max_tokens=800)
print("max_tokens=800       ->", len(trimmed), "messages,", token_counter(model=FAST, messages=trimmed), "tokens:",
      [m["content"][:7] for m in trimmed])
print("model=FAST, ratio    ->", len(trim_messages(messages, model=FAST, trim_ratio=0.0005)), "messages (prefixed name: not found, no trim)")
print("bare name, ratio     ->", len(trim_messages(messages, model="claude-haiku-5-5", trim_ratio=0.0005)), "messages")


class BudgetedHistory:
    """Short-term memory: keep the last turns verbatim, fold older ones into a rolling summary."""

    def __init__(self, model, budget, keep_last=2):
        self.model, self.budget, self.keep_last = model, budget, keep_last
        self.summary, self.turns = "", []

    def add(self, message):
        self.turns.append(message)
        while self.tokens() > self.budget and len(self.turns) > self.keep_last:
            evicted, self.turns = self.turns[:2], self.turns[2:]
            self.summary = self._summarise(evicted)

    def context(self, question):
        system = SYSTEM["content"]
        if self.summary:
            system += f"\n<conversation_summary>\n{self.summary}\n</conversation_summary>"
        return [{"role": "system", "content": system}, *self.turns, question]

    def tokens(self):
        return token_counter(model=self.model, messages=self.context(QUESTION))

    def _summarise(self, evicted):
        prompt = (f"Current summary:\n{self.summary or '(none)'}\n\nNew turns:\n"
                  + "\n".join(f"{m['role']}: {m['content']}" for m in evicted)
                  + "\n\nRewrite the summary in at most 60 words. Keep decisions, dates and names.")
        resp = litellm.completion(model=self.model, messages=[{"role": "user", "content": prompt}], max_tokens=120,
                                  **mock("We are preparing the payments release; release date agreed: 3 March."))
        return resp.choices[0].message.content


print("== 3. a token budget with a rolling summary (compaction done by the app)")
history = BudgetedHistory(FAST, budget=600)
for turn in HISTORY:
    history.add(turn)
ctx = history.context(QUESTION)
print("kept", len(history.turns), "turns verbatim,", token_counter(model=FAST, messages=ctx), "tokens; system prompt ends:")
print("  ", ctx[0]["content"].splitlines()[-2])

print("== 4. still too long? route to a bigger window")
router = Router(model_list=[
    {"model_name": "small", "litellm_params": {"model": FAST, "mock_response": "from small"},
     "model_info": {"id": "small-window", "max_input_tokens": 500}},
    {"model_name": "small", "litellm_params": {"model": BIG, "mock_response": "from big"},
     "model_info": {"id": "big-window", "max_input_tokens": 200_000}},
    {"model_name": "large", "litellm_params": {"model": BIG, "mock_response": "from the fallback group"}},
], enable_pre_call_checks=True, context_window_fallbacks=[{"small": ["large"]}], num_retries=0)
picked = {router.completion(model="small", messages=messages).choices[0].message.content for _ in range(5)}
print("pre-call checks, 5 calls  :", picked)
resp = router.completion(model="small", messages=[QUESTION], mock_testing_context_fallbacks=True)
print("context_window_fallbacks  :", resp.choices[0].message.content)

print("== 5. a provider's 'too long' error becomes one exception type")
try:
    litellm.completion(model=FAST, messages=[QUESTION],
                       mock_response=Exception("prompt is too long: 1048576 tokens > 1000000 maximum"))
except litellm.ContextWindowExceededError as e:
    print(type(e).__name__, e.status_code)
```

```text
== 1. how big is the window, and how full is it?
anthropic/claude-haiku-5-5: input 1,000,000 tokens, output 128,000
this request: 1639 tokens in 14 messages
== 2. trim_messages drops the oldest turns, keeps the system message
max_tokens=800       -> 8 messages, 794 tokens: ['You are', 'Turn 6:', 'Turn 7:', 'Turn 8:', 'Turn 9:', 'Turn 10', 'Turn 11', 'Which d']
model=FAST, ratio    -> 14 messages (prefixed name: not found, no trim)
bare name, ratio     -> 6 messages
== 3. a token budget with a rolling summary (compaction done by the app)
kept 4 turns verbatim, 590 tokens; system prompt ends:
   We are preparing the payments release; release date agreed: 3 March.
== 4. still too long? route to a bigger window
pre-call checks, 5 calls  : {'from big'}
context_window_fallbacks  : from the fallback group
== 5. a provider's 'too long' error becomes one exception type
ContextWindowExceededError 400
```

- **Measure against the window, minus what you need for the reply.** One million input tokens is the ceiling, not a target: cost and latency grow with every token you send, and models use the middle of a long context less well.
- **`trim_messages` is a sliding window.** It keeps the system message, any trailing `tool` messages (so a tool result is never cut off from its call), and as many of the newest turns as fit. Pass `max_tokens` yourself. With `model=` it looks the name up in `litellm.model_cost` exactly, so a provider-prefixed name such as `anthropic/...` or `bedrock/...` is not found and nothing is trimmed, with no warning.
- **Compaction is your code.** `BudgetedHistory` keeps the last turns verbatim and folds evicted ones into a summary written by the same cheap model, rewritten each time so it stays bounded. It goes into the system prompt inside `<conversation_summary>`, so the model can tell it apart from instructions.
- **The router is the safety net, not the plan.** With `enable_pre_call_checks=True` the router counts the prompt and skips deployments whose `model_info.max_input_tokens` is too small; in step 4 the 500-token deployment was never chosen. `context_window_fallbacks` moves a request that still overflows to another model group. It is separate from `fallbacks`, which handles other errors.

**Provider-native context features.** Anthropic models can clear old tool results and compact history on the server, and use a client-side memory tool. [`22b_native_context.py`](examples/22b_native_context.py) checks what LiteLLM sends, against local fakes of the Anthropic API and of Bedrock:

```python
"""Provider-native context features through LiteLLM: context editing, compaction, prompt caching, the memory tool."""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "bedrock"))
for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_BEARER_TOKEN_BEDROCK"):
    os.environ.pop(var, None)
# Fake static keys, only so the request can be signed for the fake endpoint; never do this with real keys.
os.environ.update(LITELLM_LOCAL_MODEL_COST_MAP="True", AWS_REGION="us-west-2",
                  AWS_ACCESS_KEY_ID="AKIAFAKEEXAMPLE0001", AWS_SECRET_ACCESS_KEY="fake-secret")

import httpx
import litellm

import _fake_upstream
import fake_bedrock


def start(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}"


ANTHROPIC, BEDROCK = start(_fake_upstream.Handler), start(fake_bedrock.Handler)
MSGS = [{"role": "system", "content": "Static rules: answer in one line."}, {"role": "user", "content": "Status?"}]
CLEAR_OLD_TOOL_RESULTS = {"edits": [{"type": "clear_tool_uses_20250919",
                                     "trigger": {"type": "input_tokens", "value": 30000},
                                     "keep": {"type": "tool_uses", "value": 3}, "exclude_tools": ["memory"]}]}
MEMORY_TOOL = [{"type": "memory_20250818", "name": "memory"}]


def anthropic(**kwargs):
    """Call the fake Anthropic API and return the body and anthropic-beta header it received."""
    litellm.completion(model="anthropic/claude-haiku-5-5", messages=MSGS, api_key="fake", api_base=ANTHROPIC, **kwargs)
    seen = httpx.get(f"{ANTHROPIC}/_seen").json()[-1]
    return json.loads(seen["body"]), seen["headers"].get("anthropic-beta")


def bedrock(model, **kwargs):
    """Call the fake Bedrock and return the route and the body fields beyond the messages."""
    litellm.completion(model=model, messages=MSGS, aws_bedrock_runtime_endpoint=BEDROCK, num_retries=0, **kwargs)
    seen = httpx.get(f"{BEDROCK}/_seen").json()[-1]
    extra = {k: v for k, v in seen["body"].items() if k not in ("messages", "inferenceConfig", "max_tokens", "anthropic_version")}
    return seen["path"].rsplit("/", 1)[-1], extra


print("== 1. context editing: let Anthropic clear old tool results")
body, beta = anthropic(context_management=CLEAR_OLD_TOOL_RESULTS)
print("beta   :", beta)
print("sent   :", body["context_management"]["edits"][0]["type"], "| keep", body["context_management"]["edits"][0]["keep"])

print("== 2. server-side compaction, OpenAI-style input")
body, beta = anthropic(context_management=[{"type": "compaction", "compact_threshold": 150000}])
print("beta   :", beta)
print("sent   :", body["context_management"])

print("== 3. prompt caching: mark the stable prefix")
body, _ = anthropic(cache_control_injection_points=[{"location": "message", "role": "system"}])
print("system :", body["system"])
_, extra = bedrock("bedrock/us.anthropic.claude-haiku-5-5",
                   cache_control_injection_points=[{"location": "message", "role": "system"}])
print("bedrock:", extra["system"])

print("== 4. Anthropic's memory tool is passed through")
body, beta = anthropic(tools=MEMORY_TOOL)
print("tools  :", body["tools"], "| beta:", beta)

print("== 5. on Bedrock it depends on the route")
for model in ("bedrock/us.anthropic.claude-haiku-5-5", "bedrock/invoke/us.anthropic.claude-haiku-5-5"):
    route, cm = bedrock(model, context_management=CLEAR_OLD_TOOL_RESULTS)
    _, tools = bedrock(model, tools=MEMORY_TOOL)
    print(f"{model:44} {route:8} context_management={'context_management' in cm}  memory tool={'tools' in tools}")
```

```text
== 1. context editing: let Anthropic clear old tool results
beta   : context-management-2025-06-27
sent   : clear_tool_uses_20250919 | keep {'type': 'tool_uses', 'value': 3}
== 2. server-side compaction, OpenAI-style input
beta   : compact-2026-01-12
sent   : {'edits': [{'type': 'compact_20260112', 'trigger': {'type': 'input_tokens', 'value': 150000}}]}
== 3. prompt caching: mark the stable prefix
system : [{'type': 'text', 'text': 'Static rules: answer in one line.', 'cache_control': {'type': 'ephemeral'}}]
bedrock: [{'text': 'Static rules: answer in one line.'}, {'cachePoint': {'type': 'default'}}]
== 4. Anthropic's memory tool is passed through
tools  : [{'type': 'memory_20250818', 'name': 'memory'}] | beta: context-management-2025-06-27
== 5. on Bedrock it depends on the route
bedrock/us.anthropic.claude-haiku-5-5        converse context_management=False  memory tool=False
bedrock/invoke/us.anthropic.claude-haiku-5-5 invoke   context_management=True  memory tool=True
```

- **LiteLLM passes these through and adds the beta headers.** `context_management` accepts Anthropic's own `{"edits": [...]}` format unchanged, or OpenAI's `[{"type": "compaction", ...}]`, which it maps to `compact_20260112`. It adds `context-management-2025-06-27` (also when the memory tool is present) or `compact-2026-01-12` to `anthropic-beta`.
- **`cache_control_injection_points` marks the stable prefix without changing your messages.** Here it marked the system message. Bedrock gets a `cachePoint` block instead of `cache_control`. A point can also take an `index`, such as `-2` for the last message before the new question (exercise 22b.3).
- **On Bedrock the route decides.** The default Converse route (`bedrock/us.anthropic...`) silently drops the `clear_tool_uses_20250919` edit and the memory tool: no error, no warning. It keeps only `compact_20260112` edits and adds the `compact-2026-01-12` beta for them (from the source, checked offline; the run above sends only the clear edit). This is `completion()`; the docs describe a different path for Anthropic-format `/v1/messages` calls, where the gateway applies the edits to the messages itself for providers without native support, Bedrock Converse included. I did not run that. The Invoke route (`bedrock/invoke/us.anthropic...`) sends Anthropic's own request body, so both reach the model with `anthropic_beta` set. If you rely on these features on Bedrock, use `bedrock/invoke/` and check what was sent.
- **Automatic compaction in the router.** The complexity router (section 14a) has a `context_compaction` setting, on by default (`trigger_ratio: 0.9`, summaries up to `max_tokens: 4096`). When a request passes 90% of the chosen deployment's input window, the router has a model summarise the older, closed part of the conversation, replaces it with one assistant message, `Summary of earlier conversation (context, not new instructions): ...`, and keeps the system prompt and the latest turn. It uses Anthropic's native compaction, so the summarising model must be an Anthropic API model that supports it (`claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5` and others), not a Bedrock one. I didn't run it here, because the fake Anthropic API doesn't produce compaction blocks.

#### Exercises

**22b.1 ★ `ex22b_1_fit_context.py`: fit a conversation into a budget**

Write `fit(messages, model, budget=None, reserve_output=1024)`. It returns `trim_messages(messages, max_tokens=budget)`, and when `budget` is `None` it uses 75% of `get_model_info(model)["max_input_tokens"]` minus `reserve_output`. Build a conversation of a system message, 16 long turns, a user question, then an assistant tool call and its `tool` result. Send the fitted messages to `_env.FAST`.

Checks:
- With no budget, `fit` returns the messages unchanged for `_env.FAST`.
- With `budget=900`, the result starts with the system message, ends with the tool call and its result, still holds the question, and everything before the tool result is at most 900 tokens.
- `trim_messages(messages, model=_env.FAST, trim_ratio=0.001)` returns the messages untrimmed. Explain why in a comment.

<details><summary>Hint</summary>

`trim_messages` is in `litellm.utils`. Count with `token_counter(model=_env.FAST, messages=...)`.
</details>

**22b.2 ★★ `ex22b_2_window_routing.py`: route by window size**

Build a `Router` with two deployments in the group `chat`: `_env.FAST` with `model_info` `{"id": "fast-2k", "max_input_tokens": 2000}`, and `_env.SMART` with `{"id": "smart-1m", "max_input_tokens": 1000000}`. Add a group `long` (`_env.ALT`, id `alt-1m`). Set `enable_pre_call_checks=True` and `context_window_fallbacks=[{"chat": ["long"]}]`. Use `**_env.mock(...)` inside each deployment's `litellm_params`.

Checks:
- Twenty short prompts use only `fast-2k` and `smart-1m`, and offline they use both.
- Four prompts of about 5,000 tokens all go to `smart-1m`.
- A short prompt with `mock_testing_context_fallbacks=True` is answered by `alt-1m`.

<details><summary>Hint</summary>

The deployment that answered is in `response._hidden_params["model_id"]`.
</details>

**22b.3 ★★ `ex22b_3_cache_layout.py`: lay out the context for caching**

Write `assemble(rules, memories, history, question)`. It returns a system message with two text blocks (the rules, marked `"cache_control": {"type": "ephemeral"}`, then the memories inside `<memories>`), followed by the history and the new question. Send it with `cache_control_injection_points=[{"location": "message", "index": -2}]`, once to a local `_fake_upstream` Anthropic and once to a local `fake_bedrock` (from `examples/`, as in `22b_native_context.py`).

Checks:
- Anthropic: in the system blocks only the rules carry `cache_control`. Of the messages, only the last history message carries it, not the question.
- Bedrock: the system is `text`, `cachePoint`, `text`, and only the last history message contains a `cachePoint`.

<details><summary>Hint</summary>

Put `examples/` and `examples/bedrock/` on `sys.path` and start each fake in a thread with `ThreadingHTTPServer(("127.0.0.1", 0), Handler)`. Both record requests at `/_seen`.
</details>

### 22c. Memory management with LiteLLM

LiteLLM keeps no memory of its own in the SDK. Every `completion()` call sends exactly the messages you give it. The proxy has two pieces of state that help:

| Need | What LiteLLM offers | Where | What you still build |
| --- | --- | --- | --- |
| Session (short-term) memory | Nothing in the SDK. On the proxy, the **Responses API** with `previous_response_id` rebuilds earlier turns for providers that don't store responses themselves | Proxy | Without the proxy: the history list and its compaction (22b) |
| Long-term memory | **`/v1/memory`**: a key-value store in the proxy's Postgres, scoped to users and teams. It only stores entries; nothing reads them into prompts | Proxy | Extraction, retrieval and injection: the read and write paths |
| Semantic search over memories | `litellm.embedding()` for the vectors | SDK, proxy | The vector store, scoring and threshold |
| Agent-managed memory | Tool calling for any model; Anthropic's `memory_20250818` tool passed through | SDK, proxy | The tool's backend: files or a database |
| Procedural memory | Prompt templates (section 17) and skills (section 16a) | SDK, proxy | Versioning and review |
| An episodic log | Spend logs, and `litellm_session_id` to group calls | Proxy | Turning logs into memories |

**Long-term memory in your app.** [`22c_long_term_memory.py`](examples/22c_long_term_memory.py) builds the write path (a model extracts facts as JSON, which are deduplicated and stored) and the read path (score, filter, fit to a budget, inject). To run offline it uses a toy word-hash embedder; in production, swap `embed()` for `litellm.embedding(...)` and the list for a vector database:

```python
"""Long-term memory built on LiteLLM: an LLM extracts facts (write path), retrieval scores and budgets them (read path)."""
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field

import litellm
from litellm import token_counter

from _mock import mock

MODEL = "anthropic/claude-haiku-5-5"
DAY = 86_400
STOP = {"the", "a", "an", "is", "of", "on", "we", "do", "our", "user", "s", "what", "when", "to", "in", "and"}


def embed(texts):
    """Toy hashed bag-of-words vectors so this runs offline; in production use litellm.embedding(model=..., input=texts)."""
    vectors = []
    for text in texts:
        vec = [0.0] * 256
        for word in re.findall(r"[a-z]+", text.lower()):
            if word in STOP:
                continue
            word = word[:-1] if len(word) > 4 and word.endswith("s") else word
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % 256] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vectors.append([v / norm for v in vec])
    return vectors


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


@dataclass
class Memory:
    text: str
    kind: str          # episodic, semantic or procedural
    importance: float  # 0..1, set when written
    vector: list = field(repr=False)
    written_at: float = field(default_factory=time.time)


class LongTermMemory:
    def __init__(self, min_similarity=0.2, half_life_days=30):
        self.items, self.min_similarity, self.half_life = [], min_similarity, half_life_days * DAY

    def write(self, text, kind, importance, now=None):
        """Store a memory, or refresh the timestamp of a near-duplicate."""
        vector = embed([text])[0]
        for item in self.items:
            if cosine(item.vector, vector) > 0.95:
                item.written_at = now or time.time()
                return "refreshed"
        self.items.append(Memory(text, kind, importance, vector, now or time.time()))
        return "stored"

    def search(self, query, budget_tokens, now=None):
        """Score by similarity, recency and importance; drop weak matches; fit the rest into the budget."""
        now, query_vector = now or time.time(), embed([query])[0]
        scored = []
        for item in self.items:
            similarity = cosine(item.vector, query_vector)
            if similarity < self.min_similarity:
                continue
            recency = 0.5 ** ((now - item.written_at) / self.half_life)
            scored.append((0.6 * similarity + 0.2 * recency + 0.2 * item.importance, item))
        picked, used = [], 0
        for score, item in sorted(scored, key=lambda pair: pair[0], reverse=True):
            cost = token_counter(model=MODEL, text=item.text)
            if used + cost <= budget_tokens:
                picked.append((round(score, 2), item))
                used += cost
        return picked


def extract_facts(turn):
    """Write path step 1: ask a cheap model which facts in a turn are worth keeping."""
    prompt = ("Extract durable facts about the user or project from this turn as JSON "
              '{"facts": [{"text": ..., "kind": "semantic|episodic|procedural", "importance": 0..1}]}. '
              f"Return an empty list if nothing is worth keeping.\n\nTurn: {turn}")
    fake = json.dumps({"facts": [
        {"text": "The user's team deploys the payments service on Fridays.", "kind": "semantic", "importance": 0.8},
        {"text": "On 2026-11-12 the Friday deploy failed on a missing database index.", "kind": "episodic", "importance": 0.6},
    ]})
    resp = litellm.completion(model=MODEL, messages=[{"role": "user", "content": prompt}],
                              response_format={"type": "json_object"}, **mock(fake))
    return json.loads(resp.choices[0].message.content)["facts"]


def build_system_prompt(memories):
    """Read path last step: inject what was found, with type and date, and say how to use it."""
    if not memories:
        return "You are a deployment assistant."
    lines = [f"- [{m.kind}, {time.strftime('%Y-%m-%d', time.gmtime(m.written_at))}] {m.text}" for _, m in memories]
    return ("You are a deployment assistant.\n<memories>\nThese notes may be outdated; use them only if relevant.\n"
            + "\n".join(lines) + "\n</memories>")


now = time.time()
store = LongTermMemory()
print("== 1. write path: extract, dedupe, store")
for fact in extract_facts("We always ship payments on Friday. Last week's deploy broke because an index was missing."):
    print(store.write(fact["text"], fact["kind"], fact["importance"], now - 6 * DAY), "|", fact["kind"], "|", fact["text"])
print(store.write("Our favourite lunch place is the noodle bar.", "semantic", 0.1, now - 90 * DAY), "| semantic | lunch")
print(store.write("The user's team deploys the payments service on Fridays!", "semantic", 0.8, now),
      "| near-duplicate of the first fact")

print("== 2. read path: score, filter, budget")
for query in ("When do we deploy payments?", "What is the capital of France?"):
    hits = store.search(query, budget_tokens=60, now=now)
    print(f"{query!r}: {[(score, m.text[:40]) for score, m in hits]}")

print("== 3. inject into the context of the next call")
system = build_system_prompt(store.search("When do we deploy payments?", budget_tokens=60, now=now))
print(system)
resp = litellm.completion(model=MODEL, messages=[{"role": "system", "content": system},
                                                 {"role": "user", "content": "When do we deploy payments?"}],
                          **mock("On Fridays; check the database indexes first."))
print("reply:", resp.choices[0].message.content)
```

```text
== 1. write path: extract, dedupe, store
stored | semantic | The user's team deploys the payments service on Fridays.
stored | episodic | On 2026-11-12 the Friday deploy failed on a missing database index.
stored | semantic | lunch
refreshed | near-duplicate of the first fact
== 2. read path: score, filter, budget
'When do we deploy payments?': [(0.74, "The user's team deploys the payments ser"), (0.47, 'On 2026-11-12 the Friday deploy failed o')]
'What is the capital of France?': []
== 3. inject into the context of the next call
You are a deployment assistant.
<memories>
These notes may be outdated; use them only if relevant.
- [semantic, 2026-11-19] The user's team deploys the payments service on Fridays.
- [episodic, 2026-11-13] On 2026-11-12 the Friday deploy failed on a missing database index.
</memories>
reply: On Fridays; check the database indexes first.
```

- **The threshold matters more than the ranking.** "What is the capital of France?" returned nothing, so nothing was injected. Without a minimum similarity, top-k always injects k memories, and irrelevant memories distract the model.
- **Score with more than similarity.** Recency (a 30-day half-life here) and an importance set at write time let a fresh, important fact beat an old one that happens to share words. The 90-day-old lunch preference never came close.
- **Deduplicate on write.** A near-duplicate refreshes the timestamp of the existing entry instead of adding a second copy.
- **Inject with provenance.** Each memory carries its type and date, inside `<memories>` with the line "may be outdated; use them only if relevant", so the model can weigh stale facts instead of obeying them.

**Agent-managed memory.** Instead of a pipeline deciding, the model decides what to remember, through a tool. Anthropic's built-in memory tool works only with the Anthropic API and `bedrock/invoke/` (22b). The same idea written as an ordinary OpenAI-format tool works with any model LiteLLM can call. [`22d_memory_tool.py`](examples/22d_memory_tool.py):

```python
"""Agent-managed memory: a file-backed memory tool in OpenAI format, so it works with any model LiteLLM can call."""
import json
import tempfile
from pathlib import Path

import litellm

from _mock import LIVE

MODEL = "anthropic/claude-haiku-5-5"
MEMORY_TOOL = [{"type": "function", "function": {
    "name": "memory",
    "description": "Your persistent memory directory /memories. View it before starting; record progress as you go.",
    "parameters": {"type": "object", "required": ["command", "path"], "properties": {
        "command": {"type": "string", "enum": ["view", "create", "str_replace"]},
        "path": {"type": "string", "description": "Path under /memories"},
        "file_text": {"type": "string"}, "old_str": {"type": "string"}, "new_str": {"type": "string"}}}}}]


class FileMemory:
    """The tool's backend: plain files under one root, so memories are readable, diffable and auditable."""

    def __init__(self, root):
        self.root = Path(root).resolve() / "memories"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, path):
        target = (self.root / Path(path).relative_to("/memories")).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"{path} is outside /memories")
        return target

    def run(self, command, path, file_text="", old_str="", new_str=""):
        target = self._path(path)
        if command == "view":
            if target.is_dir():
                return "\n".join(sorted(p.name for p in target.iterdir())) or "(empty)"
            return target.read_text() if target.exists() else f"{path} does not exist"
        if command == "create":
            target.write_text(file_text)
            return f"created {path}"
        if command == "str_replace":
            text = target.read_text()
            if text.count(old_str) != 1:
                return f"old_str must appear exactly once in {path}"
            target.write_text(text.replace(old_str, new_str))
            return f"edited {path}"
        return f"unknown command {command}"


def call(i, **args):
    return {"id": f"call_{i}", "type": "function", "function": {"name": "memory", "arguments": json.dumps(args)}}


SESSIONS = {
    "Start the payments migration checklist.": [
        {"mock_tool_calls": [call(1, command="view", path="/memories")]},
        {"mock_tool_calls": [call(2, command="create", path="/memories/migration.md",
                                  file_text="# Payments migration\n- [x] snapshot taken\n- [ ] apply schema\n")]},
        {"mock_response": "Snapshot taken; next step is applying the schema."},
    ],
    "Continue the migration.": [
        {"mock_tool_calls": [call(3, command="view", path="/memories/migration.md")]},
        {"mock_tool_calls": [call(4, command="str_replace", path="/memories/migration.md",
                                  old_str="- [ ] apply schema", new_str="- [x] apply schema")]},
        {"mock_response": "Schema applied; the checklist is complete."},
    ],
}

memory = FileMemory(tempfile.mkdtemp())
for task, fake_turns in SESSIONS.items():
    print(f"== new session (fresh context): {task!r}")
    messages = [{"role": "system", "content": "Always view /memories first. Keep a checklist there."},
                {"role": "user", "content": task}]
    for turn in range(6):
        fake = {} if LIVE else fake_turns[turn]
        msg = litellm.completion(model=MODEL, messages=messages, tools=MEMORY_TOOL, **fake).choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            print("answer:", msg.content)
            break
        for tool_call in msg.tool_calls:
            args = json.loads(tool_call.function.arguments)
            result = memory.run(**args)
            print(f"memory.{args['command']}({args['path']}) -> {result.splitlines()[0] if result else ''}")
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})

print("== what is on disk")
print((memory.root / "migration.md").read_text().rstrip())
try:
    memory.run("view", "/memories/../../etc/passwd")
except ValueError as e:
    print("blocked:", e)
```

```text
== new session (fresh context): 'Start the payments migration checklist.'
memory.view(/memories) -> (empty)
memory.create(/memories/migration.md) -> created /memories/migration.md
answer: Snapshot taken; next step is applying the schema.
== new session (fresh context): 'Continue the migration.'
memory.view(/memories/migration.md) -> # Payments migration
memory.str_replace(/memories/migration.md) -> edited /memories/migration.md
answer: Schema applied; the checklist is complete.
== what is on disk
# Payments migration
- [x] snapshot taken
- [x] apply schema
blocked: /memories/../../etc/passwd is outside /memories
```

- **Each session starts with an empty context.** The second session knew the checklist only because the model read `/memories/migration.md`. That is memory: something written outside the call and loaded back in.
- **The system prompt is the write policy.** "Always view /memories first. Keep a checklist there." decides what gets remembered, so treat it as procedural memory and version it.
- **The backend owns safety.** Every path is resolved and checked against the root, so `../` can't escape it. Plain files are easy to read, diff and audit, which is why tools such as Claude Code keep `CLAUDE.md` files.
- **The trade-off is round trips.** The model spent two extra calls per session on memory. A pipeline injects without extra calls but may inject what isn't needed. Many systems inject a small profile and let the agent fetch the rest.

**Memory on the proxy.** These need the database from section 13. [`memory/memory_config.yaml`](examples/memory/memory_config.yaml) points `chat` at the fake Anthropic API and stores prompts in the spend logs, which the Responses API needs:

```yaml
# Section 22: memory on the proxy. Needs DATABASE_URL (section 13) and _fake_upstream.py on port 4011.
model_list:
  - model_name: chat
    litellm_params:
      model: anthropic/claude-haiku-5-5
      api_key: fake
      api_base: http://127.0.0.1:4011

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  store_prompts_in_spend_logs: true     # the Responses API rebuilds a session from these rows
```

```bash
cd examples
uv run python _fake_upstream.py 4011 &
export DATABASE_URL=postgresql://postgres:demo@localhost:55432/litellm LITELLM_MASTER_KEY=sk-master-demo LITELLM_LOCAL_MODEL_COST_MAP=True
uv run litellm --config memory/memory_config.yaml --port 4000
uv run python memory/22e_proxy_memory.py        # in another shell, same exports
```

[`memory/22e_proxy_memory.py`](examples/memory/22e_proxy_memory.py)

```python
"""Memory on the proxy: Responses API sessions, and /v1/memory as the store behind your own read and write paths."""
import json
import os
import uuid

import httpx

PROXY, UPSTREAM = "http://localhost:4000", "http://127.0.0.1:4011"
ADMIN = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
MEMORY_ROUTES = ["/v1/memory", "/v1/memory/{key}"]


def last_upstream_body():
    seen = [r for r in httpx.get(f"{UPSTREAM}/_seen").json() if r["path"].startswith("/v1/messages")]
    return json.loads(seen[-1]["body"])


def key_for(http, user_id):
    """A key for an internal user that may also use the memory routes."""
    http.post("/user/new", json={"user_id": user_id, "user_role": "internal_user"})
    key = http.post("/key/generate", json={"user_id": user_id, "allowed_routes": MEMORY_ROUTES + ["/v1/chat/completions"]})
    return {"Authorization": f"Bearer {key.json()['key']}"}


with httpx.Client(base_url=PROXY, headers=ADMIN, timeout=60) as http:
    print("== 1. Responses API: the proxy keeps the conversation")
    first = http.post("/v1/responses", json={"model": "chat", "instructions": "Answer in one line.",
                                             "input": "My name is Ana and I deploy on Fridays."}).json()
    http.post("/v1/responses", json={"model": "chat", "input": "When do I deploy?", "previous_response_id": first["id"]})
    sent = last_upstream_body()
    print("id length   :", len(first["id"]))
    print("model got   :", [(m["role"], m["content"][0]["text"][:30]) for m in sent["messages"]])
    print("instructions:", sent["system"][0]["text"])

    print("== 2. /v1/memory as a key-value store, written by your app")
    suffix = uuid.uuid4().hex[:6]
    ana, bob = key_for(http, f"ana-{suffix}"), key_for(http, f"bob-{suffix}")
    for name, value in (("profile", "Deploys the payments service on Fridays."),
                        ("style", "Prefers one-line answers with the command to run.")):
        r = httpx.post(f"{PROXY}/v1/memory", headers=ana,
                       json={"key": f"user:ana-{suffix}:{name}", "value": value, "metadata": {"kind": "semantic"}})
        print("write:", r.status_code, r.json()["key"], "| owner", r.json()["user_id"])

    print("== 3. read path: fetch by prefix, inject, call the model")
    rows = httpx.get(f"{PROXY}/v1/memory", headers=ana, params={"key_prefix": f"user:ana-{suffix}:"}).json()["memories"]
    notes = "\n".join(f"- {row['value']}" for row in rows)
    httpx.post(f"{PROXY}/v1/chat/completions", headers=ana, json={"model": "chat", "messages": [
        {"role": "system", "content": f"You help with deployments.\n<memories>\n{notes}\n</memories>"},
        {"role": "user", "content": "Plan my next deploy."}]})
    print(last_upstream_body()["system"][0]["text"])

    print("== 4. scoping")
    print("bob lists   :", httpx.get(f"{PROXY}/v1/memory", headers=bob).json()["memories"])
    print("bob gets    :", httpx.get(f"{PROXY}/v1/memory/user:ana-{suffix}:profile", headers=bob).status_code)
    r = httpx.post(f"{PROXY}/v1/memory", headers=bob, json={"key": f"user:ana-{suffix}:profile", "value": "x"})
    print("bob reuses Ana's key name:", r.status_code, r.json()["detail"])
    no_routes = http.post("/key/generate", json={"user_id": f"bob-{suffix}"}).json()["key"]
    r = httpx.get(f"{PROXY}/v1/memory", headers={"Authorization": f"Bearer {no_routes}"})
    print("key without allowed_routes:", r.status_code)

    for row in rows:
        httpx.delete(f"{PROXY}/v1/memory/{row['key']}", headers=ana).raise_for_status()
    print("cleaned up", len(rows), "entries")
```

```text
== 1. Responses API: the proxy keeps the conversation
id length   : 469
model got   : [('user', 'My name is Ana and I deploy on'), ('assistant', 'fake Anthropic reply'), ('user', 'When do I deploy?')]
instructions: Answer in one line.
== 2. /v1/memory as a key-value store, written by your app
write: 200 user:ana-8b2379:profile | owner ana-8b2379
write: 200 user:ana-8b2379:style | owner ana-8b2379
== 3. read path: fetch by prefix, inject, call the model
You help with deployments.
<memories>
- Prefers one-line answers with the command to run.
- Deploys the payments service on Fridays.
</memories>
== 4. scoping
bob lists   : []
bob gets    : 404
bob reuses Ana's key name: 409 Memory with key 'user:ana-8b2379:profile' already exists.
key without allowed_routes: 401
cleaned up 2 entries
```

- **`previous_response_id` gives you session memory without storing history in your app.** For providers that don't store responses themselves, such as Anthropic and Bedrock, the proxy rebuilds the earlier turns from its spend logs and sends them with the new input, and it reuses the earlier `instructions`. The ID is an opaque 469-character string; store it as it is.
- **It needs `store_prompts_in_spend_logs: true`.** Without it, the second call still returns 200, but the model gets only the new input: the history is silently lost. With it, every prompt and reply is stored in Postgres, so treat that database as holding user content (retention, access, section 20).
- **`/v1/memory` stores entries, and your app does the rest.** The proxy has no hook that reads memories into prompts. In step 3 the app fetched entries by `key_prefix` and injected them itself. Listing also accepts an exact `key` or a `search` prefix, with `page` and `page_size`.
- **Only proxy admins can use it by default.** In 1.110.2 `/v1/memory` is not on the routes an internal user's key may call, so a normal key gets 401. Give a key `allowed_routes` that include `/v1/memory` and `/v1/memory/{key}`, plus every other route it needs, because `allowed_routes` replaces the defaults.
- **Keys are unique across the whole proxy.** Bob saw nothing of Ana's and got 404 on her entry, but creating an entry under her key name gave 409 `already exists`, which also tells him the name is taken. Namespace every key, for example `user:<id>:<name>` or `team:<id>:<name>`.
- **A team key shares what it writes.** An entry created with a key that belongs to a team gets both the user and the team ID, and every member of that team can read it. Only its owner (or a team admin, for team-only entries) can change it (exercise 22c.2). Write personal memories with a personal key.

**Making it work well, and cheaply.**

1. **Budget each part, not one total.** Fix a token budget for the rules, memories, history and question, and reserve the output. Measure with `token_counter` for the model you are calling.
2. **Keep the prefix stable and cache it.** Tools and rules first, then the per-turn memories and the new message. Mark the end of the stable part with `cache_control` or `cache_control_injection_points`, and keep timestamps and IDs out of it.
3. **Compact with a cheap model, and bound the result.** Summarise evicted turns with your fast model and rewrite the summary each time. Use the provider's server-side compaction or tool-result clearing where it is available (the Anthropic API, `bedrock/invoke/`).
4. **Retrieve for recall, inject for precision.** Fetch many candidates, then keep the few above a threshold that fit the budget, with their type and date.
5. **Write in the background, and scope every entry.** Extract facts after the reply, deduplicate, and key each entry to its user or team. On the proxy, use personal keys for personal memories.
6. **Keep a safety net.** `enable_pre_call_checks` and `context_window_fallbacks` catch what your budget missed, and `ContextWindowExceededError` is the one error type to handle.
7. **Measure it.** Track tokens per call (section 8), cache hits, and whether answers improve with memory on. Callbacks (sections 10 and 18) can log the injected memories next to the reply.

#### Exercises

**22c.1 ★ `ex22c_1_recall.py`: recall with a threshold, recency and a budget**

Build a small long-term memory. Offline, embed with a word-hash vector (as in `22c_long_term_memory.py`); live, use `litellm.embedding(model="bedrock/amazon.titan-embed-text-v2:0", input=...)`. Write four facts at different ages: the billing service runs on Postgres 16 (200 days), billing deploys need a migration review (5 days), Priya does the billing migration review (1 day), and the coffee machine is on floor 3 (2 days). Score with `0.8 × similarity + 0.2 × recency` (30-day half-life), drop anything below a minimum similarity, and fit the result into a token budget.

Checks:
- Writing a near-duplicate of the Postgres fact returns "not stored" and refreshes that entry's timestamp.
- "What is the capital of Peru?" recalls nothing.
- "Who does the billing migration review?" doesn't recall the coffee machine, and offline the Priya fact comes first, because recency breaks the similarity tie.
- With a 12-token budget, fewer facts come back and they fit in 12 tokens.

<details><summary>Hint</summary>

Ignore very short words in the toy embedder, or "the" and "is" will match everything. Live, Titan's similarities are on a different scale; choose the threshold by printing a few scores first.
</details>

**22c.2 ★★ `ex22c_2_proxy_memory.py`: shared memory and sessions on the proxy**

With the proxy from this subsection running, create a team with two members, Ana and Ben, and an outsider, Carl, each with a key whose `allowed_routes` are `/v1/memory`, `/v1/memory/{key}` and `/v1/responses` (Ana's and Ben's keys belong to the team). Ana writes `team:<tag>:runbook`. Then hold a three-turn conversation as Ana with `/v1/responses` and `previous_response_id`, and read what the fake upstream received for the last turn.

Checks:
- Ana's entry has her `user_id` and the team's `team_id`. Ben can read it but gets 403 when he tries to change it.
- Carl gets 404 reading it, and 409 when he creates an entry with the same key.
- On the third turn the upstream received five messages, alternating user and assistant, starting with Ana's first input.

<details><summary>Hint</summary>

Add members with `POST /team/member_add`. The fake upstream records requests at `http://127.0.0.1:4011/_seen`; the last `/v1/messages` entry is the third turn.
</details>

**Clean up.** Stop the proxy with Ctrl-C and the fake upstream with `kill %1`. If you are finished with the proxy sections, `docker rm -f litellm-tutorial-db` removes section 13's Postgres and everything stored in it.

## 23. Other providers and endpoints (reference; not run here)

These follow the same pattern as section 1, which covers AWS Bedrock, Bedrock Mantle, Ollama and vLLM in detail from the SDK, and the other major providers in brief. Section 12 covers the cloud platforms (AWS Bedrock, Microsoft Azure, Google Vertex AI), providers called directly, and local models with Ollama and vLLM, and runs them against a real Ollama and local fakes. The lines below are a quick reference; I didn't run them as written, because each needs that provider's credentials.

```python
# Local models
completion(model="ollama_chat/llama3.1", messages=m, api_base="http://localhost:11434")   # chat API; keeps roles and tools
completion(model="hosted_vllm/meta-llama/Llama-3.1-8B-Instruct", messages=m,
           api_base="http://localhost:8000/v1")

# Cloud platforms: credentials come from each platform's normal mechanism
completion(model="bedrock/anthropic.claude-sonnet-5-5", messages=m)      # AWS credential chain / IAM role
completion(model="azure/<your-deployment-name>", messages=m,
           api_base="https://<resource>.openai.azure.com", api_version="<version>")
completion(model="vertex_ai/gemini-2.5-flash", messages=m,
           vertex_project="<project>", vertex_location="us-central1")    # Google ADC

# Any OpenAI-compatible server
completion(model="openai/<model>", messages=m, api_base="https://<host>/v1", api_key=...)

# Embeddings: same idea, OpenAI-shaped response
litellm.embedding(model="openai/text-embedding-3-small", input=["hello", "world"])
```

Other endpoints follow the same pattern: `image_generation`, `transcription`, `rerank`, `responses` and batch APIs.

### Exercises

**23.1 ★ `ex23_1_semantic_search.py`: embeddings and nearest neighbours**

Embed 8 short help-centre articles and a query with `litellm.embedding(model="bedrock/amazon.titan-embed-text-v2:0", input=[...])`, then rank the articles by cosine similarity to the query. Print the top 3 and the embedding cost.

Checks:
- `len(resp.data)` equals the number of inputs (live), and every vector has the same length.
- Live: for the query "how do I get my money back", the top hit is your refund article.

<details><summary>Hint</summary>

Offline, the embedding mock returns one vector whatever the input. Behind `if not _env.LIVE`, build fake vectors yourself, for example from word counts over a small vocabulary, so the ranking code still runs. The Titan embedding model must be enabled in your account, like the chat models.
</details>

**23.2 ★★ `ex23_2_capstone.py`: an `ask` command that uses everything**

Build a CLI, `python ex23_2_capstone.py "question" [--json] [--fail-primary]`, that:

- routes through a `Router` with groups `smart`, `fast` and `alt`, and fallbacks `smart → fast → alt`;
- streams the answer to the terminal;
- caches answers in a local cache that lasts while the process runs (accept several questions in one run);
- logs every call with your 10.1 logger;
- enforces a budget with your 8.2 guard;
- with `--json`, returns a validated Pydantic `Answer(answer: str, confidence: float, sources: list[str])`, with confidence between 0 and 1;
- with `--fail-primary`, passes `mock_testing_fallbacks=True`.

Checks:
- Asking the same question twice in one run gives a cache hit with a logged cost of `0.0`.
- `--fail-primary` still answers, and the log shows the fallback group.
- With a budget set below one call's cost, the second question is refused with your `BudgetExceeded`.
- `--json` output validates against `Answer`.

<details><summary>Hint</summary>

Build this from the pieces of earlier exercises; it should need little new code. Streaming and `response_format` don't mix well, so stream only in the non-JSON mode.
</details>

---

## Gotchas found while writing this

| Symptom | Cause | Fix |
| --- | --- | --- |
| `UnsupportedParamsError: ... does not support temperature=0` | The model rejects that parameter, and LiteLLM refuses rather than guessing | Drop the parameter for that model, or pass `drop_params=True` knowingly |
| `litellm.max_budget` never triggers | In 1.110.2 its counter ignores chat completions | Your own guard (section 8) or proxy key budgets (section 13) |
| Budget exceeded by one call | Budgets are checked before a call; cost is known after | Set the limit with one call of headroom |
| `/key/info` spend is 0 right after calls | Spend is batch-written every 10s | Wait, or trust the 422 the proxy returns |
| `Router` crashes in `deepcopy` | The model list holds a non-copyable object | Keep `model_list` plain data |
| Traceback printed although the fallback succeeded | The fallback runner logs each failed attempt | Expected; lower the `LiteLLM` logger level if it's noise |
| "Give Feedback / Get Help" banner on stdout | LiteLLM prints it on errors | `litellm.suppress_debug_info = True` |
| Proxy with DB won't start | Missing `prisma` or an ungenerated client | `litellm[extra_proxy]` + `prisma generate`, or use the Docker image |
| Proxy container exits with `P1001: Can't reach database server at localhost:55432` | Inside a container, `localhost` is the container itself | Use the Compose service name: `postgresql://...@db:5432/...` |
| An edited `config.yaml` has no effect after `docker compose up -d` | Compose recreates a container when its settings change, not when a mounted file does | `docker compose restart proxy` |
| Slow first import, network access at import | Price table fetched from GitHub | `LITELLM_LOCAL_MODEL_COST_MAP=True` |
| A `CustomLogger` hook never runs, with no error | LiteLLM calls hooks with keyword arguments; a hook whose parameters aren't named `kwargs, response_obj, start_time, end_time` fails silently | Use exactly those parameter names |
| `completion_cost(resp)` charges for a cache hit | It re-prices the response from its token counts | Use `resp._hidden_params["response_cost"]` or the logged `response_cost`, which are `0.0` on a hit |
| `BadRequestError: ... Every deployment for it is a strategy router marker (auto_router/...)` | Smart routers only run on the async path in 1.110.2 | `await router.acompletion(...)`; the proxy is unaffected |
| A complexity-routed call ignores your `max_tokens` | `max_tokens_from_tier_model` defaults to true and sets the chosen model's maximum output | Set it to `"clamp"` or `false` |
| `uv sync` fails after adding `semantic-router` | Every release LiteLLM accepts requires `openai<3`; this project pins `openai==3.50.0` | Run with `uv run --with semantic-router==0.1.16 --with openai==2.54.0` |
| A quality router ignores a model that declares a tier | The model isn't in `available_models` | List every candidate there |
| The adaptive router never learns | No `litellm_session_id` and fewer than four messages, or only provider errors, which it ignores | Pass a session ID; it learns from conversation text only |
| A Bedrock call ran on Standard although `service_tier` was set | 1.110.2 forwards only `priority`, `flex`, `default` and `auto`, in lower case, and drops anything else without an error | Send one of those values in lower case; `reserved` can't be requested in 1.110.2 |
| A Bedrock call ran on Standard but was billed at the priority rate | `service_tier="Priority"` is dropped on the wire, but the cost lookup lower-cases it | Lower-case the tier before the call |
| An Azure OpenAI deployment's `response_cost` is `None` | `azure/<name>` is your deployment name, which LiteLLM can't price | `base_model: azure/<model>` (SDK) or `model_info.base_model` (proxy) |
| Azure answers `404 DeploymentNotFound` | The request used the model name, or the deployment is in another resource | Use the deployment name, with that resource's `api_base` |
| Requests refused by Azure's content filter are answered by another model | Plain `fallbacks` also catch `ContentPolicyViolationError` when `content_policy_fallbacks` isn't set | `content_policy_fallbacks: [{"<alias>": []}]` to keep the refusal |
| `except litellm.PermissionDeniedError` misses Vertex AI's 403 | In 1.110.2, Vertex's `PERMISSION_DENIED` becomes `BadRequestError` with `status_code` 403 | Check `status_code`, not only the class |
| vLLM, Ollama or OpenAI-compatible traffic missing from spend and budgets | Self-hosted models have no price (`None`) or a price of `0.0` | `input_cost_per_token` and `output_cost_per_token` on the deployment |
| A proxy in Docker can't reach Ollama at `localhost:11434` | `localhost` is the proxy's own container | A shared Docker network and the container name, or `host.docker.internal` |
| An MCP server's tools are missing from the gateway | stdio servers are disabled by default | Set `LITELLM_ENABLE_MCP_STDIO=true` in the proxy's environment |
| `mock_response` sent to the proxy is ignored | The proxy strips client mocks unless the key allows them | Put the mock in the deployment's `litellm_params` |
| `/v1/skills` returns 500 about `ANTHROPIC_API_KEY` | Without `custom_llm_provider=litellm_proxy` it calls Anthropic | Add `?custom_llm_provider=litellm_proxy` for hosted skills |
| A key gets 403 from an agent it lists in `object_permission.agents` | The check compares agent IDs; config agents have a 64-character hashed ID | List the `agent_id` from `GET /v1/agents`, not the name |
| An agent keeps answering after `PATCH ... {"enabled": false}` | In 1.110.2 `enabled` is enforced only for agents with a managed identity | Delete the agent, or remove it from keys' `object_permission.agents` |
| `PATCH /v1/agents/<id>` returns 404 for an agent you can list | Agents from the config file aren't in the database | Change the config and restart, or register the agent with `POST /v1/agents` |
| `trim_messages(messages, model="bedrock/...")` returns the messages untrimmed | It looks the name up in `litellm.model_cost` exactly, and prefixed names aren't there | Pass `max_tokens=` yourself, from `get_model_info(model)["max_input_tokens"]` |
| `AttributeError` or `ImportError` for `litellm.trim_messages` | In 1.110.2 it isn't exported at the top level | `from litellm.utils import trim_messages` |
| `clear_tool_uses` edits or Anthropic's memory tool have no effect on Bedrock | The Converse route drops them silently and keeps only `compact_20260112` | Use `bedrock/invoke/<model>`, which sends Anthropic's own request body |
| `previous_response_id` returns 200 but the model forgot the earlier turns | The proxy rebuilds history from spend logs, which hold no prompts by default | Set `general_settings.store_prompts_in_spend_logs: true`, and treat the database as holding user content |
| `/v1/memory` returns 401 for a user's key | Its routes are admin-only by default | Give the key `allowed_routes` with `/v1/memory` and `/v1/memory/{key}` and every other route it needs |
| `/v1/memory` POST returns 409 for a key you have never used | Memory keys are unique across all users | Namespace them, e.g. `user:<id>:<name>` |
| An agent doesn't get the client's header | Only `static_headers`, headers named in `extra_headers` and `x-a2a-<agent>-<name>` are forwarded | Name the header in `extra_headers`, or send it with the `x-a2a-<agent>-` prefix |
| A `.prompt` file's `temperature` has no effect | The SDK drops template parameters in 1.110.2 | Pass parameters on the call, or use the proxy, which applies them |
| A prompt template is applied twice | A manager overriding both the sync and async hooks, used with `acompletion` | Override only `get_chat_completion_prompt`, or use the `dotprompt/` prefix |
| Proxy won't start: `Could not build the 'otel' callback` | `opentelemetry-sdk` is not installed | Install it (this project does) |
| `/metrics` returns 401, or nothing | It requires a key by default, and redirects to `/metrics/` | Send a key and use `curl -L`, or set `require_auth_for_metrics_endpoint: false` |
| All fallbacks failed, but the exception isn't the one the primary raised | The fallback runner raises its own error once every fallback is exhausted | Catch `openai.APIError`, the base class of every LiteLLM provider exception (`litellm.APIError` is not) |
| Bedrock call: `UnsupportedParamsError ... does not support temperature` | Some models on Bedrock reject a parameter the OpenAI format allows | Drop it for that model, or `drop_params=True` |
| Bedrock 403 `AccessDeniedException` | Model access isn't enabled in that account and region, or the role lacks `bedrock:InvokeModel` on the model or inference-profile ARN | Enable the model in every region the profile routes to; check the IAM policy |
| Bedrock 400 `The provided model identifier is invalid` | A wrong model ID, or an inference profile used outside its geography (an `eu.` profile signed for a US region) | Check the ID and `aws_region_name` |
| Bedrock 400 `... with on-demand throughput isn't supported` | A base model ID for a model offered only through inference profiles | Use `us.`, `eu.`, `apac.` or `global.` in front of the ID |
| Bedrock spend is missing for an application-inference-profile ARN | LiteLLM can't price an ARN; `response_cost` is `None` | Set `base_model` on the call or deployment |
| A throttled Bedrock region keeps being tried | `allowed_fails` is set, so the older cooldown rule waits for more than that many failures | Remove `allowed_fails`; a 429 then cools the deployment down at once |
| Proxy won't start: `the master key is a publicly known default` (exit code 3) | `LITELLM_MASTER_KEY=sk-1234`; empty and unset keys are refused too | `sk-$(openssl rand -hex 32)`; only for local tests, `LITELLM_DANGEROUSLY_PERMIT_WEAK_OR_UNSET_MASTER_KEY=true` |
| A key was created fine, but every call with it returns 500 `... is an Enterprise feature` | The Enterprise-only key field `enforced_params` (`tags`, `guardrails` and `model_max_budget` are refused when the key is created) | Remove the field, or add a licence; test each new key with one call |
| A `custom_auth` caller can use models outside the `models` you returned | The key-level model check only runs for database keys | Check the requested model inside the auth function (section 20b) |
| The master key stops working after adding `custom_auth` | `custom_auth` replaces all of the proxy's key checks | Accept the master key in your function with `hmac.compare_digest` |
| A `custom_auth` user spends past every cap | No user row for that `user_id`; a missing row is treated as "no user limits" | Create the row on first sign-in, or refuse the call (section 20b) |
| Every `custom_auth` call gets 404 `Team doesn't exist in db` | The function returns an IdP group as `team_id`, and with a database the proxy looks the team up | Create the team, or don't return `team_id` |
| A person over their cap keeps spending with a team key | Personal caps skip team keys by default | `general_settings.apply_user_budget_to_team_keys: true` |
| An exhausted budget stays blocked for minutes after `budget_reset_at` | The reset job runs about every 10 minutes | Expected; `proxy_budget_rescheduler_min_time`/`max_time` to shorten it |
| A token signed with a just-rotated IdP key gets 401 for up to 30 s | PyJWT's `PyJWKClient` doesn't refetch the JWKS within `cooldown_duration` of its last fetch | Lower `cooldown_duration`; IdPs usually publish keys before using them |
| A model added through `/model/new` vanished after a restart (400 `Invalid model name`) | `LITELLM_SALT_KEY` changed; stored credentials can't be decrypted. Only a `WARNING` is logged | Never change the salt key; set it before the first credential is stored |
| The proxy uses an old provider key after Vault was updated | Secrets are read once, at startup | Rolling restart after every rotation |
| The proxy runs with a stale key while the secret store is down | An unreachable secret manager falls back to the environment variable of the same name, logging `Defaulting to os.environ value` | Don't keep same-named variables in the environment; alert on that log line |
| `PermissionError: ... '/app/config.yaml'` with the `litellm-non_root` image | The mounted file is `600` and the container runs as uid 65534 | `chmod 644` the mounted config (secrets stay in the environment) |
| httpx: `CA cert does not include key usage extension` | Python 3.13 checks X.509 strictly; a home-made CA lacks `keyUsage` | Add `basicConstraints=critical,CA:TRUE` and `keyUsage=critical,keyCertSign,cRLSign` to the CA |
| `rpm_limit` lets through N × the limit with N replicas | No coordination Redis, so each replica counts alone | `general_settings.coordination_redis` |
| Limits keep counting per replica for a minute after Redis came back | The Redis circuit breaker stays open for `REDIS_CIRCUIT_BREAKER_RECOVERY_TIMEOUT` (60 s) | Expected; alert on `circuit breaker is open` |
| `/openapi.json` and the `/ui` files are still served with `NO_DOCS` and `DISABLE_ADMIN_UI` | Those variables hide Swagger and turn off sign-in only | Set `NO_OPENAPI=True` for the schema, and block both paths at the edge proxy |
| `allowed_ips: ["10.0.0.0/8"]` blocks everyone (licensed proxy) | `allowed_ips` matches exact addresses only, no CIDR | List addresses, or filter at the network edge |
| `max_request_size_mb` has no effect | Enterprise-only; without a licence it is logged and ignored | `client_max_body_size` (nginx) or your load balancer's limit |
| The prebuilt `iban` pattern misses `GB82 WEST 1234 ...` | It matches the unspaced form only | Add a `regex` pattern for each format you see |
| Lens shows LiteLLM's model calls as `chain` steps and counts no LLM calls | LiteLLM writes `gen_ai.operation.name=acompletion` on async calls, a name Lens doesn't know | `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` before the `OpenTelemetry` logger is created |
| Lens marks calls through the proxy `ambiguous` and shows no cost | The SDK and the proxy each made their own LiteLLM call ID | Pass one ID as `litellm_call_id=` and as the `x-litellm-call-id` header |
| Lens marks calls `no_spend_log` although the proxy logged them | The tracing key belongs to a different user or team than the agent's virtual key | Create the tracing key with the agent's own key (its user needs `proxy_admin`), in the same team |
| A new Lens investigation screens 0 runs | Lens skips traces from the last two minutes | Wait two minutes after the runs |
| Runs are missing from Lens; the exporter logged `Failed to export spans batch code: 400` | Lens rejected the upload once, and the OTLP exporter doesn't retry a 400 | Confirm delivery with `POST /v1/traces/receipt` |
| Lens can't reach the proxy for analysis models | `localhost` inside the Lens container is the container | `host.docker.internal` (Docker Desktop), or a shared Docker network |
| Lens's SQL endpoint returns 503 for a typo | It answers 503 for SQL it can't parse or won't run | Read `GET /v1/traces/query/help` for the rules |

## Cheat sheet

```python
import litellm
from litellm import completion, acompletion, Router, completion_cost

completion(model="provider/model", messages=[...])                  # sync
await acompletion(model=..., messages=...)                          # async
completion(..., stream=True)                                        # stream; rebuild with stream_chunk_builder
completion(..., response_format=PydanticModel)                      # structured output
completion(..., tools=[...])                                        # tool calling, OpenAI format
completion(..., num_retries=3, fallbacks=["other/model"])           # resilience
completion_cost(resp); litellm.token_counter(model, messages=...)  # money and tokens
litellm.cache = litellm.Cache(type="redis", host=..., port=...)     # response cache
litellm.callbacks = [MyLogger(), "langfuse"]                        # observability
Router(model_list=[...], fallbacks=[...], routing_strategy=...)     # many deployments
{"model_name": "auto", "litellm_params": {"model": "auto_router/complexity_router",
  "complexity_router_config": {"tiers": {"SIMPLE": "fast", ...}}}}      # smart routing; await router.acompletion only
completion(model="dotprompt/openai/gpt-4o-mini", prompt_id="support", prompt_variables={...})  # prompt files
litellm.callbacks = ["otel", "langsmith"]                         # traces and logging platforms
litellm.callbacks = [OpenTelemetry(tracer_provider=provider)]     # agent spans to Lens: OTLP to <lens>/v1/traces, Bearer tracing key
from litellm.utils import trim_messages; trim_messages(messages, max_tokens=8000)   # sliding window, keeps system + tool results
Router(..., enable_pre_call_checks=True, context_window_fallbacks=[{"chat": ["long"]}])  # bigger window when needed
completion(..., context_management={"edits": [{"type": "clear_tool_uses_20250919"}]},
           cache_control_injection_points=[{"location": "message", "role": "system"}])  # provider context features
completion(model="a2a/triage", api_base="http://host/a2a/triage", api_key=key, messages=m)   # an A2A agent as a model
completion(..., mock_response="text" | SomeError(...))              # tests without a provider
completion(model="bedrock/us.anthropic.claude-haiku-5-5", messages=m,
           aws_region_name="us-west-2", aws_role_name="arn:aws:iam::...:role/bedrock")   # Bedrock via an assumed role
completion(model="azure/<deployment>", api_base="https://<resource>.openai.azure.com", api_version="2024-10-21",
           base_model="azure/gpt-4o", messages=m)                    # Azure OpenAI; base_model prices it
completion(model="azure_ai/claude-haiku-5-5", api_base="https://<resource>.services.ai.azure.com", messages=m)
completion(model="vertex_ai/gemini-2.5-flash", vertex_project="<p>", vertex_location="global", messages=m)  # Google ADC
completion(model="ollama_chat/qwen2.5:0.5b", api_base="http://localhost:11434", messages=m)   # local model
completion(model="hosted_vllm/<model>", api_base="http://<host>:8000/v1", messages=m)          # vLLM
```

```yaml
guardrails:                                                         # proxy config: mask, block, check replies
  - guardrail_name: pii
    litellm_params: {guardrail: litellm_content_filter, mode: pre_call, default_on: true,
                     patterns: [{pattern_type: prebuilt, pattern_name: email, action: MASK}]}
general_settings:
  custom_auth: oidc_auth.user_api_key_auth                          # IdP tokens without a licence
  coordination_redis: {host: os.environ/REDIS_HOST, port: 6379}     # limits shared across replicas
  key_management_system: custom                                     # secrets from your own store
```

```bash
uv run litellm --config config.yaml --port 4000                     # proxy
AWS_PROFILE=<p> uv run litellm --config examples/proxy/quickstart.yaml   # quick start: proxy in front of Bedrock
docker run -p 127.0.0.1:4000:4000 -v "$HOME/.aws:/root/.aws:ro" -e AWS_PROFILE -e AWS_REGION ...   # same, in Docker
docker run -d -p 127.0.0.1:11434:11434 ollama/ollama:0.12.6; docker exec <name> ollama pull qwen2.5:0.5b   # local model
docker run -p 127.0.0.1:4000:4000 -v "$PWD/config.yaml:/app/config.yaml:ro" -e LITELLM_MASTER_KEY \
  ghcr.io/berriai/litellm:v1.110.2 --config /app/config.yaml --port 4000   # proxy from the official image
docker compose up -d --wait; docker compose down -v                 # proxy + Postgres (examples/proxy/docker-compose.yml)
curl localhost:4000/key/generate -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{"models":["chat"],"max_budget":10,"rpm_limit":60}'           # virtual key
curl localhost:4000/user/new -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{"user_id":"alice","max_budget":20,"budget_duration":"1mo"}'   # a person's cap, reset on the 1st
LITELLM_ENABLE_MCP_STDIO=true uv run litellm --config mcp_config.yaml   # MCP gateway at /mcp
curl localhost:4000/a2a/triage -H "Authorization: Bearer $KEY" \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{...}}}'   # A2A agent gateway
curl -L localhost:4000/metrics -H "Authorization: Bearer $LITELLM_MASTER_KEY"   # Prometheus
LENS_PORT=4319 LENS_PUBLIC_URL=http://localhost:4319 ./start         # Lens + ClickHouse from the release bundle
LITELLM_LENS_URL=http://localhost:4319 LITELLM_LENS_SERVICE_TOKEN=... LENS_GATEWAY_SECRET=... \
  uv run litellm --config config.yaml                               # proxy connected to Lens
curl localhost:4000/v1/traces -H "Authorization: Bearer $KEY"       # agent runs through the proxy; POST /lens starts an investigation
curl localhost:4000/key/generate -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{"team_id":"...","key_type":"llm_api","duration":"30d"}'       # least-privilege app key
NO_DOCS=True NO_REDOC=True NO_OPENAPI=True DISABLE_ADMIN_UI=True LITELLM_MODE=PRODUCTION \
  LITELLM_CORS_ORIGINS=https://app.example.com uv run litellm --config config.yaml --host 127.0.0.1   # hardened settings
PROBE_KEY=sk-... uv run python examples/security/hardening_check.py https://llm.example.com           # external audit
```

---

© 2026 Chuan Zhang. The tutorial text and figures are all rights reserved; the code is MIT-licensed (see [LICENSE](LICENSE)).
