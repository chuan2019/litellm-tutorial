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
