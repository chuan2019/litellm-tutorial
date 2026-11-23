"""Check that every statement of the tutorial and LiteLLM versions agrees with pyproject.toml.

Usage: check_versions.py          exit 1 and list mismatches, if any
       check_versions.py --tag    print the release tag for this edition
"""
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Generated from files that are checked themselves.
SKIP = {"TUTORIAL.html", "uv.lock"}


def versions():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    pins = [m.group(1) for d in project["dependencies"] if (m := re.fullmatch(r"litellm(?:\[[^\]]*\])?==(\S+)", d))]
    if len(pins) != 1:
        sys.exit(f"pyproject.toml: expected one exact litellm pin, found {pins}")
    return project["version"], pins[0]


def problems(tutorial, litellm):
    out = []

    def need(path, text, what):
        if text not in (ROOT / path).read_text():
            out.append(f"{path}: missing {what}: {text!r}")

    need("TUTORIAL.md", f"Tutorial version {tutorial} · written for LiteLLM {litellm}", "byline")
    need("TUTORIAL.md", f"This is version {tutorial} of the tutorial", "'Which version this covers'")
    need("TUTORIAL.md", f"it is written for LiteLLM {litellm}.", "'Which version this covers'")
    need("TUTORIAL.md", f"`litellm[proxy,extra_proxy]=={litellm}`", "pin in Setup")
    need("README.md", f"**Version {tutorial}, written for LiteLLM {litellm}.**", "version line")
    need("CHANGELOG.md", f"## [{tutorial}] for LiteLLM {litellm} (", "changelog entry")
    if not re.search(rf"^\| {re.escape(litellm)} \|", (ROOT / "README.md").read_text(), re.M):
        out.append(f"README.md: editions table has no row for LiteLLM {litellm}")

    lock = (ROOT / "uv.lock").read_text()
    for name, want in (("litellm", litellm), ("litellm-tutorial", tutorial)):
        got = re.search(rf'^name = "{name}"\nversion = "([^"]+)"', lock, re.M)
        if not got or got.group(1) != want:
            out.append(f"uv.lock: {name} is {got and got.group(1)}, expected {want} (run uv lock)")

    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    refs = (r"ghcr\.io/berriai/litellm[\w-]*:v([\w.-]+)", r"github\.com/BerriAI/litellm/blob/v([\w.-]+)/")
    for path in tracked:
        if path in SKIP or not (ROOT / path).is_file():
            continue
        try:
            text = (ROOT / path).read_text()
        except UnicodeDecodeError:
            continue
        for pattern in refs:
            for m in re.finditer(pattern, text):
                if m.group(1) != litellm:
                    line = text.count("\n", 0, m.start()) + 1
                    out.append(f"{path}:{line}: {m.group(0)} does not match LiteLLM {litellm}")
    return out


def check():
    tutorial, litellm = versions()
    if found := problems(tutorial, litellm):
        sys.exit("Version check failed:\n  " + "\n  ".join(found))
    return tutorial, litellm


if __name__ == "__main__":
    tutorial, litellm = check()
    print(f"v{tutorial}-litellm{litellm}" if "--tag" in sys.argv else f"OK: tutorial {tutorial}, LiteLLM {litellm}")
