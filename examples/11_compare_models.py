"""Run one small eval across several models and compare accuracy, cost and latency."""
import asyncio
import time

import litellm

from _mock import LIVE

litellm.drop_params = True

MODELS = ["anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5", "openai/gpt-4o-mini"]
CASES = [
    ("What is 17 * 23? Reply with the number only.", "391"),
    ("Capital of Canada? One word.", "Ottawa"),
    ("Is 91 prime? Reply yes or no.", "no"),
    ("Reverse the string 'litellm'. Reply with the result only.", "mlletil"),
]
FAKE = {
    "anthropic/claude-haiku-5-5": ["391", "Ottawa", "yes", "mlletil"],
    "anthropic/claude-sonnet-5-5": ["391", "Ottawa", "No", "mlletil"],
    "openai/gpt-4o-mini": ["391", "Toronto", "no", "mletlil"],
}


async def run_case(model, i, prompt):
    fake = {} if LIVE else {"mock_response": FAKE[model][i], "mock_delay": 0.05 * (i + 1)}
    start = time.perf_counter()
    resp = await litellm.acompletion(model=model, messages=[{"role": "user", "content": prompt}],
                                     max_tokens=20, temperature=0, **fake)
    return (resp.choices[0].message.content.strip(), litellm.completion_cost(resp),
            time.perf_counter() - start)


async def main():
    print(f"{'model':30} {'acc':>5} {'cost':>11} {'p50 s':>6}")
    for model in MODELS:
        results = await asyncio.gather(*(run_case(model, i, p) for i, (p, _) in enumerate(CASES)))
        outputs = [out.lower().strip(".") for out, _, _ in results]
        correct = sum(out == want.lower() for out, (_, want) in zip(outputs, CASES, strict=True))
        cost = sum(c for _, c, _ in results)
        p50 = sorted(t for _, _, t in results)[len(results) // 2]
        print(f"{model:30} {correct}/{len(CASES):<3} ${cost:.8f} {p50:6.2f}")


asyncio.run(main())
