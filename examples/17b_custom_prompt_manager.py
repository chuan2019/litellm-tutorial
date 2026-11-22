"""A custom prompt manager: serve versioned, labelled templates from your own store."""
import litellm
from litellm.integrations.custom_prompt_management import CustomPromptManagement

from _mock import mock

PROMPTS = {
    ("summarise", 1): {"model": "openai/gpt-4o-mini", "system": "Summarise in {words} words."},
    ("summarise", 2): {"model": "anthropic/claude-haiku-5-5", "system": "Summarise in {words} words, as bullets."},
}
LABELS = {"production": 1, "staging": 2}


class DictPromptManager(CustomPromptManagement):
    """Look up a template by id and version (or label) and put it before the caller's messages."""

    def get_chat_completion_prompt(self, model, messages, non_default_params, prompt_id,
                                   prompt_variables, dynamic_callback_params, prompt_label=None,
                                   prompt_version=None, **kwargs):
        version = prompt_version or LABELS[prompt_label or "production"]
        template = PROMPTS[(prompt_id, version)]
        system = template["system"].format(**(prompt_variables or {}))
        print(f"  manager: {prompt_id} v{version} -> {template['model']}, system={system!r}")
        return template["model"], [{"role": "system", "content": system}, *messages], non_default_params


litellm.callbacks = [DictPromptManager()]
article = [{"role": "user", "content": "LiteLLM is a Python SDK and proxy that ..."}]

for how in ({}, {"prompt_label": "staging"}, {"prompt_version": 1}):
    print(how or "(no label: production)")
    resp = litellm.completion(model="openai/gpt-4o-mini", messages=article, prompt_id="summarise",
                              prompt_variables={"words": 20}, **how, **mock("A short summary."))
    print(f"  response model: {resp.model}")

print("no prompt_id: the manager is not called")
resp = litellm.completion(model="openai/gpt-4o-mini", messages=article, **mock("A short summary."))
print(f"  response model: {resp.model}")
