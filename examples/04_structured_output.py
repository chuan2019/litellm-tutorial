"""Get JSON that matches a Pydantic schema, and validate it."""
import json

import litellm
from pydantic import BaseModel, ValidationError

from _mock import mock


class Invoice(BaseModel):
    vendor: str
    total: float
    currency: str
    line_items: list[str]


TEXT = """ACME Tools Ltd. Invoice #8812. 2x hammer (24.00), 1x saw (31.50).
Total due: 55.50 EUR."""
MODEL = "openai/gpt-4o-mini"

print("supports json schema:", litellm.supports_response_schema(model=MODEL))

resp = litellm.completion(
    model=MODEL,
    messages=[{"role": "user", "content": f"Extract the invoice.\n\n{TEXT}"}],
    response_format=Invoice,
    **mock(json.dumps({"vendor": "ACME Tools Ltd.", "total": 55.5, "currency": "EUR",
                       "line_items": ["2x hammer", "1x saw"]})),
)
invoice = Invoice.model_validate_json(resp.choices[0].message.content)
print(invoice)

try:
    Invoice.model_validate_json('{"vendor": "ACME", "total": "fifty"}')
except ValidationError as e:
    print(f"\nbad output is caught: {e.error_count()} errors, e.g. {e.errors()[0]['loc']}")
