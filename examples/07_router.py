"""Load-balance across deployments, retry, and fail over between model groups."""
import logging
from collections import Counter

import litellm
from litellm import Router

litellm.suppress_debug_info = True
logging.getLogger("LiteLLM Router").setLevel(logging.CRITICAL)

router = Router(
    model_list=[
        {"model_name": "fast", "litellm_params": {
            "model": "openai/gpt-4o-mini", "api_key": "sk-fake-a",
            "mock_response": "from deployment A"}, "model_info": {"id": "A"}},
        {"model_name": "fast", "litellm_params": {
            "model": "openai/gpt-4o-mini", "api_key": "sk-fake-b",
            "mock_response": "from deployment B"}, "model_info": {"id": "B"}},
        {"model_name": "smart", "litellm_params": {
            "model": "anthropic/claude-sonnet-5-5", "api_key": "sk-fake-c",
            "mock_response": "from smart"}},
        {"model_name": "flaky", "litellm_params": {
            "model": "openai/gpt-4o", "api_key": "sk-fake-d",
            "mock_response": "from flaky"}},
    ],
    routing_strategy="simple-shuffle",
    num_retries=1,
    fallbacks=[{"flaky": ["smart"]}],
)

msgs = [{"role": "user", "content": "hi"}]
counts = Counter(router.completion(model="fast", messages=msgs).choices[0].message.content
                 for _ in range(100))
print("100 calls to 'fast':", dict(counts))

resp = router.completion(model="flaky", messages=msgs, mock_testing_fallbacks=True)
print("'flaky' failed; the call was answered by", repr(resp.choices[0].message.content))
