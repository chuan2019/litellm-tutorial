"""Exercise 1.5: one Pydantic schema, two Bedrock model families; compare what each costs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "exercises"))
import _env  # noqa: E402

import litellm  # noqa: E402
from pydantic import BaseModel  # noqa: E402


class Ticket(BaseModel):
    customer: str
    order_id: str
    issue: str


EMAIL = ("Hi, this is Dana Reyes. My order A-1043 arrived with a cracked screen. "
         "Can you send a replacement? Thanks, Dana")
messages = [{"role": "user", "content": f"Extract the ticket fields from this email:\n\n{EMAIL}"}]
results = {}
for model in (_env.FAST, _env.ALT):
    resp = litellm.completion(model=model, messages=messages, max_tokens=300, response_format=Ticket,
                              **_env.mock('{"customer": "Dana Reyes", "order_id": "A-1043", "issue": "cracked screen"}'))
    ticket = Ticket.model_validate_json(resp.choices[0].message.content)
    results[model] = resp.usage.prompt_tokens
    print(f"{model:40} {ticket.model_dump()} prompt_tokens={resp.usage.prompt_tokens} "
          f"cost=${litellm.completion_cost(resp):.6f}")
    assert ticket.order_id == "A-1043"

if _env.LIVE:
    assert results[_env.ALT] > results[_env.FAST], results
print("all checks passed")
