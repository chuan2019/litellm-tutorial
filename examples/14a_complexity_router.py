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
