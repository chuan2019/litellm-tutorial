"""Context management with the SDK: measure the window, trim, compact into a summary, and fall back to a bigger window."""
import litellm
from litellm import Router, get_model_info, token_counter
from litellm.utils import trim_messages

from _mock import mock

FAST, BIG = "anthropic/claude-haiku-5-5", "anthropic/claude-opus-5-5"
SYSTEM = {"role": "system", "content": "You are a release assistant. Answer in one line."}
HISTORY = [{"role": "user" if i % 2 == 0 else "assistant",
            "content": f"Turn {i}: " + ("notes about the payments release " * 25)} for i in range(12)]
QUESTION = {"role": "user", "content": "Which date did we pick for the release?"}

print("== 1. how big is the window, and how full is it?")
info = get_model_info(FAST)
print(f"{FAST}: input {info['max_input_tokens']:,} tokens, output {info['max_output_tokens']:,}")
messages = [SYSTEM, *HISTORY, QUESTION]
print("this request:", token_counter(model=FAST, messages=messages), "tokens in", len(messages), "messages")

print("== 2. trim_messages drops the oldest turns, keeps the system message")
trimmed = trim_messages(messages, max_tokens=800)
print("max_tokens=800       ->", len(trimmed), "messages,", token_counter(model=FAST, messages=trimmed), "tokens:",
      [m["content"][:7] for m in trimmed])
print("model=FAST, ratio    ->", len(trim_messages(messages, model=FAST, trim_ratio=0.0005)), "messages (prefixed name: not found, no trim)")
print("bare name, ratio     ->", len(trim_messages(messages, model="claude-haiku-5-5", trim_ratio=0.0005)), "messages")


class BudgetedHistory:
    """Short-term memory: keep the last turns verbatim, fold older ones into a rolling summary."""

    def __init__(self, model, budget, keep_last=2):
        self.model, self.budget, self.keep_last = model, budget, keep_last
        self.summary, self.turns = "", []

    def add(self, message):
        self.turns.append(message)
        while self.tokens() > self.budget and len(self.turns) > self.keep_last:
            evicted, self.turns = self.turns[:2], self.turns[2:]
            self.summary = self._summarise(evicted)

    def context(self, question):
        system = SYSTEM["content"]
        if self.summary:
            system += f"\n<conversation_summary>\n{self.summary}\n</conversation_summary>"
        return [{"role": "system", "content": system}, *self.turns, question]

    def tokens(self):
        return token_counter(model=self.model, messages=self.context(QUESTION))

    def _summarise(self, evicted):
        prompt = (f"Current summary:\n{self.summary or '(none)'}\n\nNew turns:\n"
                  + "\n".join(f"{m['role']}: {m['content']}" for m in evicted)
                  + "\n\nRewrite the summary in at most 60 words. Keep decisions, dates and names.")
        resp = litellm.completion(model=self.model, messages=[{"role": "user", "content": prompt}], max_tokens=120,
                                  **mock("We are preparing the payments release; release date agreed: 3 March."))
        return resp.choices[0].message.content


print("== 3. a token budget with a rolling summary (compaction done by the app)")
history = BudgetedHistory(FAST, budget=600)
for turn in HISTORY:
    history.add(turn)
ctx = history.context(QUESTION)
print("kept", len(history.turns), "turns verbatim,", token_counter(model=FAST, messages=ctx), "tokens; system prompt ends:")
print("  ", ctx[0]["content"].splitlines()[-2])

print("== 4. still too long? route to a bigger window")
router = Router(model_list=[
    {"model_name": "small", "litellm_params": {"model": FAST, "mock_response": "from small"},
     "model_info": {"id": "small-window", "max_input_tokens": 500}},
    {"model_name": "small", "litellm_params": {"model": BIG, "mock_response": "from big"},
     "model_info": {"id": "big-window", "max_input_tokens": 200_000}},
    {"model_name": "large", "litellm_params": {"model": BIG, "mock_response": "from the fallback group"}},
], enable_pre_call_checks=True, context_window_fallbacks=[{"small": ["large"]}], num_retries=0)
picked = {router.completion(model="small", messages=messages).choices[0].message.content for _ in range(5)}
print("pre-call checks, 5 calls  :", picked)
resp = router.completion(model="small", messages=[QUESTION], mock_testing_context_fallbacks=True)
print("context_window_fallbacks  :", resp.choices[0].message.content)

print("== 5. a provider's 'too long' error becomes one exception type")
try:
    litellm.completion(model=FAST, messages=[QUESTION],
                       mock_response=Exception("prompt is too long: 1048576 tokens > 1000000 maximum"))
except litellm.ContextWindowExceededError as e:
    print(type(e).__name__, e.status_code)
