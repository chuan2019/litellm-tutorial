"""Call A2A agents from the LiteLLM SDK: read the card, send, stream, and use completion() on an agent."""
import asyncio
import os
import threading
import uuid
from http.server import ThreadingHTTPServer

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import httpx
import litellm
from a2a.compat.v0_3.types import MessageSendParams, SendMessageRequest, SendStreamingMessageRequest
from litellm.a2a_protocol import aget_agent_card, asend_message, asend_message_streaming

from fake_agents import Handler

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
TRIAGE = f"http://127.0.0.1:{server.server_port}/triage"


def params(text):
    """Wrap text as the A2A message a client sends."""
    return MessageSendParams(message={"role": "user", "parts": [{"kind": "text", "text": text}],
                                      "messageId": uuid.uuid4().hex})


async def main():
    print("== 1. the agent card (GET /.well-known/agent-card.json)")
    card = await aget_agent_card(base_url=TRIAGE)
    print(card.name, "|", card.description, "| skills:", [s.id for s in card.skills])

    print("== 2. message/send")
    reply = await asend_message(request=SendMessageRequest(id="1", params=params("I was charged twice")),
                                api_base=TRIAGE)
    result = reply.model_dump(mode="json", exclude_none=True)["result"]
    print(result["kind"], result["role"], result["parts"])

    print("== 3. message/stream")
    request = SendStreamingMessageRequest(id="2", params=params("The app crashes on login"))
    async for chunk in asend_message_streaming(request=request, api_base=TRIAGE):
        event = chunk.model_dump(mode="json", exclude_none=True)["result"]
        text = "".join(p["text"] for p in event.get("artifact", {}).get("parts", []))
        print(f"{event['kind']:15} {event.get('status', {}).get('state', '')!s:9} {text!r}")

    print("== 4. completion() with model a2a/<agent>")
    resp = await litellm.acompletion(model="a2a/triage", api_base=TRIAGE,
                                     messages=[{"role": "user", "content": "Where is my invoice?"}])
    print(resp.choices[0].message.content, "| usage:", resp.usage.prompt_tokens, resp.usage.completion_tokens)
    sent = httpx.get(f"http://127.0.0.1:{server.server_port}/_seen").json()[-1]
    print("the agent got:", sent["method"], sent["body"]["params"]["message"]["parts"])


asyncio.run(main())
server.shutdown()
