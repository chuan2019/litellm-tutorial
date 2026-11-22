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
