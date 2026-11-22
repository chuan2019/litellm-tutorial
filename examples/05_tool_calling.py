"""A complete tool-calling loop in the OpenAI format, for any provider."""
import json

import litellm

from _mock import LIVE

MODEL = "anthropic/claude-sonnet-5-5"
TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}]


def get_weather(city):
    return {"city": city, "temp_c": {"Paris": 14, "Tokyo": 21}.get(city, 18), "sky": "cloudy"}


FAKE_TURNS = [
    {"mock_tool_calls": [
        {"id": "call_1", "type": "function",
         "function": {"name": "get_weather", "arguments": json.dumps({"city": "Paris"})}},
        {"id": "call_2", "type": "function",
         "function": {"name": "get_weather", "arguments": json.dumps({"city": "Tokyo"})}},
    ]},
    {"mock_response": "Tokyo is warmer: 21°C versus 14°C in Paris, both cloudy."},
]

messages = [{"role": "user", "content": "Is it warmer in Paris or Tokyo right now?"}]
for turn in range(5):
    fake = {} if LIVE else FAKE_TURNS[turn]
    msg = litellm.completion(model=MODEL, messages=messages, tools=TOOLS, **fake).choices[0].message
    messages.append(msg)
    if not msg.tool_calls:
        print("final answer:", msg.content)
        break
    for call in msg.tool_calls:
        args = json.loads(call.function.arguments)
        result = get_weather(**args)
        print(f"turn {turn}: model called {call.function.name}({args}) -> {result}")
        messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})
