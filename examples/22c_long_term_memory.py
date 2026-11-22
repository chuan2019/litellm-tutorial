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
