# Changelog

Every release of the tutorial, newest first. A release is tagged `v<tutorial version>-litellm<LiteLLM version>` (see [Editions](README.md#editions)). Each LiteLLM version is an edition on its own branch, so an older edition can get a later tutorial version than a newer one; the heading of each entry names both versions.

## [0.2.5] for LiteLLM 1.110.2 (2026-11-23)

### Changed

- **Appendix, the reference design figure shows LiteLLM's support.** Each box is colored by its row in the table, with a legend:
  - light red for the four boxes LiteLLM 1.110.2 doesn't provide at all;
  - light yellow for the boxes it supports in part;
  - light blue for the boxes that need an Enterprise licence (identity and access, guardrails, observability).

## [0.2.4] for LiteLLM 1.110.2 (2026-11-23)

### Added

- **Appendix, the four gaps.** For each box LiteLLM 1.110.2 doesn't provide at all (messaging bots, conversation search, the manifest, the agent builder): what it is, whether it is important or optional, and how to fill it with your own code or another service.

## [0.2.3] for LiteLLM 1.110.2 (2026-11-23)

### Added

- **Appendix, LiteLLM 1.110.2 against a gateway reference design.** A figure of the design and a table that maps each of its boxes onto LiteLLM 1.110.2:
  - what LiteLLM provides, what is missing, and which section shows it;
  - nine boxes that need your own code, and the boxes that need an Enterprise licence;
  - rows that this tutorial doesn't run link the 1.110.2 source or LiteLLM's docs, and say so.

### Changed

- The outline and "How this was verified" mention the appendix.

## [0.2.2] for LiteLLM 1.110.2 (2026-11-23)

### Added

- **Setup, running the proxy on an EC2 instance.** The quick start's Bedrock proxy and section 13's Postgres on one instance with Docker Compose:
  - an instance role instead of AWS keys, and SSM Session Manager and a port-forward instead of SSH and inbound ports;
  - the problems hit on a real run: instance-role registration, the metadata hop limit, Compose interpolation, Postgres keeping its first password, the SSM region;
  - the files are in `examples/ec2/`.

## [0.2.1] for LiteLLM 1.110.2 (2026-11-22)

### Added

- **Section 1, provider adapters from the SDK.** AWS Bedrock, Amazon Bedrock Mantle, Ollama and vLLM in detail. Each part covers where OpenAI parameters land in the provider's request, what comes back, and the gotchas. The other major providers are covered in brief, in one table.
  - New examples `01c_bedrock.py`, `01d_bedrock_mantle.py`, `01e_ollama.py` and `01f_vllm.py`.
  - They share `_wire.py`, which records the request LiteLLM builds without sending it, and `_fake_vllm.py`.
  - The Bedrock and Mantle examples were run against real AWS.
- **Section 12, Bedrock Mantle behind the proxy.** `examples/bedrock/mantle_proxy.yaml` and its client, run against real Mantle.
- **Section 12, Bedrock service tiers** (priority, flex, default).
  - `bedrock_service_tier.py` runs against the fake Bedrock; `bedrock_service_tier_live.py` runs against real Bedrock.
  - The fake Bedrock can now report, override or refuse a tier.
- **Exercises and the self-test.**
  - Exercises 1.4–1.11 and 12.10, each with a reference solution in `solutions/`.
  - 27 more questions in `exercises/exam.html`, 284 in total.
  - Two rows in the gotchas table, on service tiers.

### Changed

- The outline, "How this was verified", the notebooks table and section 23 now mention the new material.
- `build/compare/README.md` describes how to compare the new examples on the next upgrade.

## [0.2.0] for LiteLLM 1.110.2 (2026-11-22)

### Changed

- **Moved to LiteLLM 1.110.2.** Every example was run again under 1.109.1 and 1.110.2 side by side, and only what changed was rewritten. The comparison scripts are in `build/compare/`. The tutorial's introduction lists the behaviour that differs:
  - the router core now runs in Rust;
  - no cost header is sent for a call LiteLLM can't price;
  - Bedrock Converse asks for the output-token breakdown;
  - the `azure_ai` token leak is fixed;
  - a rate-limited request no longer writes a warning to the log;
  - shared limits take longer to recover after a Redis outage.
- **Two scripts fixed** for 1.110.2's behaviour:
  - `providers_proxy_client.py` handles the missing cost header;
  - `prod_checks.py` copes with the quieter rate-limit log, and keeps one connection so nginx's per-worker round-robin doesn't skew the replica split.
- Docker image tags set to `v1.110.2`. The notebooks were re-executed against real Bedrock.

## [0.1.0] for LiteLLM 1.109.1 (2026-11-22)

### Added

- **First release:** 23 sections on the LiteLLM SDK and proxy, with runnable examples, notebooks, exercises, reference solutions and a self-test.
- **`build/check_versions.py`** checks that every statement of the tutorial and LiteLLM versions matches `pyproject.toml`; the HTML build runs it first.
- **`build/publish_blog.py`** publishes a tagged edition to the blog.
- **The licence:** the code is MIT-licensed; the tutorial text and figures are all rights reserved.

[0.2.2]: ../../releases/tag/v0.2.2-litellm1.110.2
[0.2.1]: ../../releases/tag/v0.2.1-litellm1.110.2
[0.2.0]: ../../releases/tag/v0.2.0-litellm1.110.2
[0.1.0]: ../../releases/tag/v0.1.0-litellm1.109.1
