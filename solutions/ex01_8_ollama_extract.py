"""Exercise 1.8: extract fields from support emails with a small local model, with and without a schema."""
import json
import os
import statistics
import time

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm  # noqa: E402
from pydantic import BaseModel, ValidationError  # noqa: E402

OLLAMA = os.environ.get("OLLAMA_API_BASE", "http://127.0.0.1:11434")
MODEL = "ollama_chat/qwen2.5:0.5b"
EMAILS = [
    "Hi, Dana Reyes here. Order A-1043 arrived with a cracked screen.",
    "This is Omar Haddad. My order B-2210 never arrived.",
    "Order C-0087 was charged twice. - Mei Lin",
    "Hello, I'm Lars Berg; order D-5531 is the wrong colour.",
    "Priya Nair, order E-7720: the box was empty!",
]


class Ticket(BaseModel):
    customer: str
    order_id: str
    issue: str


SCHEMA = {"type": "json_schema", "json_schema": {"name": "ticket", "schema": Ticket.model_json_schema()}}


def extract(email, with_schema):
    start = time.perf_counter()
    resp = litellm.completion(
        model=MODEL, api_base=OLLAMA, max_tokens=100, temperature=0, num_ctx=2048, timeout=120,
        messages=[{"role": "system", "content": "Return JSON with customer, order_id and issue."},
                  {"role": "user", "content": email}],
        **({"response_format": SCHEMA} if with_schema else {}))
    text = resp.choices[0].message.content
    try:
        return Ticket.model_validate_json(text), time.perf_counter() - start
    except (ValidationError, json.JSONDecodeError):
        return None, time.perf_counter() - start


valid = {}
for with_schema in (False, True):
    results = [extract(email, with_schema) for email in EMAILS]
    valid[with_schema] = [t for t, _ in results if t]
    print(f"schema={with_schema!s:5} valid={len(valid[with_schema])}/{len(EMAILS)} "
          f"median latency={statistics.median(s for _, s in results):.2f}s")
    for ticket, _ in results:
        print(f"    {ticket.model_dump() if ticket else 'not valid JSON for the schema'}")

assert len(valid[True]) == len(EMAILS)
print("all checks passed")
