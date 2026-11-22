#!/usr/bin/env bash
# Issue a scoped virtual key, use it, and watch the proxy enforce its limits.
set -euo pipefail
PROXY=http://localhost:4000
ADMIN="Authorization: Bearer ${LITELLM_MASTER_KEY}"
JSON="Content-Type: application/json"

chat() {  # chat <key> <model>
  curl -s "$PROXY/v1/chat/completions" -H "Authorization: Bearer $1" -H "$JSON" \
    -d "{\"model\":\"$2\",\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}]}"
}

echo "== 1. create a key: only 'chat-cheap', \$0.00003 budget, 10 requests/min"
KEY=$(curl -s "$PROXY/key/generate" -H "$ADMIN" -H "$JSON" -d '{
  "key_alias": "demo-app-'$(date +%s)'", "models": ["chat-cheap"],
  "max_budget": 0.00003, "rpm_limit": 10, "metadata": {"team": "search"}
}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["key"])')
echo "key: ${KEY:0:8}..."

echo "== 2. allowed model"
chat "$KEY" chat-cheap | python3 -c 'import json,sys; print(json.load(sys.stdin)["choices"][0]["message"]["content"])'

echo "== 3. model not on the key's list"
chat "$KEY" chat | python3 -c 'import json,sys; e=json.load(sys.stdin)["error"]; print(e["code"], e["message"][:90])'

echo "== 4. spend until the budget runs out"
for i in 2 3 4 5; do
  out=$(chat "$KEY" chat-cheap)
  echo "call $i: $(echo "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("ok" if "choices" in d else d["error"]["code"]+" "+d["error"]["message"][:80])')"
done

echo "== 5. what the proxy recorded for the key"
curl -s "$PROXY/key/info?key=$KEY" -H "$ADMIN" | python3 -c '
import json,sys; i=json.load(sys.stdin)["info"]
print({k: i[k] for k in ("key_alias","spend","max_budget","models","rpm_limit")})'

echo "== 6. an unknown key"
chat sk-not-a-real-key chat-cheap | python3 -c 'import json,sys; e=json.load(sys.stdin)["error"]; print(e["code"], e["message"][:60])'

echo "== 7. rate limit: a key allowed 2 requests per minute"
SLOW=$(curl -s "$PROXY/key/generate" -H "$ADMIN" -H "$JSON" -d '{"key_alias": "rpm-demo-'$(date +%s)'", "rpm_limit": 2}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["key"])')
for i in 1 2 3; do
  echo "call $i: $(chat "$SLOW" chat-cheap | python3 -c 'import json,sys; d=json.load(sys.stdin); print("ok" if "choices" in d else d["error"]["code"]+" "+d["error"]["message"][:70])')"
done
