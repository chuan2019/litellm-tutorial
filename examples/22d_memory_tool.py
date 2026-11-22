"""Agent-managed memory: a file-backed memory tool in OpenAI format, so it works with any model LiteLLM can call."""
import json
import tempfile
from pathlib import Path

import litellm

from _mock import LIVE

MODEL = "anthropic/claude-haiku-5-5"
MEMORY_TOOL = [{"type": "function", "function": {
    "name": "memory",
    "description": "Your persistent memory directory /memories. View it before starting; record progress as you go.",
    "parameters": {"type": "object", "required": ["command", "path"], "properties": {
        "command": {"type": "string", "enum": ["view", "create", "str_replace"]},
        "path": {"type": "string", "description": "Path under /memories"},
        "file_text": {"type": "string"}, "old_str": {"type": "string"}, "new_str": {"type": "string"}}}}}]


class FileMemory:
    """The tool's backend: plain files under one root, so memories are readable, diffable and auditable."""

    def __init__(self, root):
        self.root = Path(root).resolve() / "memories"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, path):
        target = (self.root / Path(path).relative_to("/memories")).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"{path} is outside /memories")
        return target

    def run(self, command, path, file_text="", old_str="", new_str=""):
        target = self._path(path)
        if command == "view":
            if target.is_dir():
                return "\n".join(sorted(p.name for p in target.iterdir())) or "(empty)"
            return target.read_text() if target.exists() else f"{path} does not exist"
        if command == "create":
            target.write_text(file_text)
            return f"created {path}"
        if command == "str_replace":
            text = target.read_text()
            if text.count(old_str) != 1:
                return f"old_str must appear exactly once in {path}"
            target.write_text(text.replace(old_str, new_str))
            return f"edited {path}"
        return f"unknown command {command}"


def call(i, **args):
    return {"id": f"call_{i}", "type": "function", "function": {"name": "memory", "arguments": json.dumps(args)}}


SESSIONS = {
    "Start the payments migration checklist.": [
        {"mock_tool_calls": [call(1, command="view", path="/memories")]},
        {"mock_tool_calls": [call(2, command="create", path="/memories/migration.md",
                                  file_text="# Payments migration\n- [x] snapshot taken\n- [ ] apply schema\n")]},
        {"mock_response": "Snapshot taken; next step is applying the schema."},
    ],
    "Continue the migration.": [
        {"mock_tool_calls": [call(3, command="view", path="/memories/migration.md")]},
        {"mock_tool_calls": [call(4, command="str_replace", path="/memories/migration.md",
                                  old_str="- [ ] apply schema", new_str="- [x] apply schema")]},
        {"mock_response": "Schema applied; the checklist is complete."},
    ],
}

memory = FileMemory(tempfile.mkdtemp())
for task, fake_turns in SESSIONS.items():
    print(f"== new session (fresh context): {task!r}")
    messages = [{"role": "system", "content": "Always view /memories first. Keep a checklist there."},
                {"role": "user", "content": task}]
    for turn in range(6):
        fake = {} if LIVE else fake_turns[turn]
        msg = litellm.completion(model=MODEL, messages=messages, tools=MEMORY_TOOL, **fake).choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            print("answer:", msg.content)
            break
        for tool_call in msg.tool_calls:
            args = json.loads(tool_call.function.arguments)
            result = memory.run(**args)
            print(f"memory.{args['command']}({args['path']}) -> {result.splitlines()[0] if result else ''}")
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})

print("== what is on disk")
print((memory.root / "migration.md").read_text().rstrip())
try:
    memory.run("view", "/memories/../../etc/passwd")
except ValueError as e:
    print("blocked:", e)
