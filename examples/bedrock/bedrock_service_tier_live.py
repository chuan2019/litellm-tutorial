"""Bedrock service tiers against real Bedrock: what was sent, what Bedrock reported back, and the cost."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _wire import LIVE, outcome, send  # noqa: E402  first: it sets the env vars LiteLLM reads when imported
import litellm  # noqa: E402

if not LIVE:
    sys.exit("this script calls real Bedrock: set LIVE=1 and AWS credentials (see section 12)")

MSGS = [{"role": "user", "content": "Capital of France? One word."}]
for model in ("bedrock/us.amazon.nova-2-lite-v1:0", "bedrock/us.anthropic.claude-haiku-5-5"):
    for tier in (None, "default", "priority", "flex", "reserved", "Priority"):
        start = time.perf_counter()
        resp, req = send(litellm.completion, model=model, messages=MSGS, max_tokens=20,
                         **({} if tier is None else {"service_tier": tier}))
        sent = (req or {}).get("body", {}).get("serviceTier")
        reported = getattr(resp, "service_tier", None)  # absent when Bedrock reports no tier
        print(f"{model.split('.')[1]:9} {str(tier):9} sent={str(sent):22} reported={str(reported):9} "
              f"{time.perf_counter() - start:4.1f}s {outcome(resp)[:80]}")
