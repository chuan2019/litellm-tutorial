"""Run many calls concurrently, capped by a semaphore."""
import asyncio
import time

import litellm

from _mock import mock

REVIEWS = [
    "Arrived broken, support never answered.",
    "Exactly as described, fast shipping!",
    "It works, I guess. Nothing special.",
    "Best purchase this year.",
    "Stopped working after two days.",
    "Decent value for the price.",
]
FAKE = ["negative", "positive", "neutral", "positive", "negative", "neutral"]
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
    start = time.perf_counter()
    labels = await asyncio.gather(*(classify(sem, r, f) for r, f in zip(REVIEWS, FAKE, strict=True)))
    elapsed = time.perf_counter() - start
    for review, label in zip(REVIEWS, labels, strict=True):
        print(f"{label:9} {review}")
    print(f"\n{len(REVIEWS)} calls x 1.0s each, {MAX_CONCURRENCY} at a time: {elapsed:.1f}s")


asyncio.run(main())
