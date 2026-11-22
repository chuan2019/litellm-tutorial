"""Call the proxy with a W3C traceparent and tags, then scrape its Prometheus /metrics."""
import os
import re

import httpx
from openai import OpenAI

BASE = os.environ.get("PROXY_URL", "http://localhost:4000")
KEY = os.environ["LITELLM_KEY"]
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
WANT = ("litellm_requests_metric_total", "litellm_spend_metric_total", "litellm_total_tokens_metric_total")

client = OpenAI(base_url=BASE, api_key=KEY)
for alias, tags in (("chat", ["support"]), ("chat", ["billing"]), ("chat-cheap", ["support"])):
    client.chat.completions.create(
        model=alias, messages=[{"role": "user", "content": "hello"}],
        extra_body={"metadata": {"tags": tags}},
        extra_headers={"traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01"})

print("without a key:", httpx.get(f"{BASE}/metrics/").status_code)
text = httpx.get(f"{BASE}/metrics/", headers={"Authorization": f"Bearer {KEY}"}).text
for line in text.splitlines():
    name = line.split("{")[0]
    if name in WANT:
        labels = dict(re.findall(r'(\w+)="([^"]*)"', line))
        print(f"{name:34} requested_model={labels['requested_model']:10} "
              f"tag_support={labels.get('tag_support', '-'):5} {line.rsplit(' ', 1)[1]}")
