"""Run scripts under two edition checkouts and report normalised output differences.

Usage: COMPARE_OLD=../litellm-tutorial-<old> diffrun.py examples/01_first_call.py ["examples/x.py|--with pkg==1"] ...
"""
import difflib
import os
import re
import subprocess
import sys
from pathlib import Path

NEW = Path(os.environ.get("COMPARE_NEW", Path(__file__).resolve().parents[2]))
OLD = Path(os.environ["COMPARE_OLD"]) if "COMPARE_OLD" in os.environ else None
OUT = Path(os.environ.get("COMPARE_OUT", Path(__file__).parent / "runs"))
ENV = {**os.environ, "LITELLM_LOCAL_MODEL_COST_MAP": "True", "LIVE": "0", "PYTHONUNBUFFERED": "1"}
for k in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "VIRTUAL_ENV"):
    ENV.pop(k, None)

NORM = [
    (r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<uuid>"),
    (r"\b\d+(\.\d+)?\s?(ms|s|secs?)\b", "<dur>"),
    (r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z?", "<ts>"),
    (r"\b(0x)?[0-9a-f]{16,}\b", "<hex>"),
    (r"\b17\d{8}\b", "<epoch>"),
    (r"chatcmpl-[\w-]+", "chatcmpl-<id>"),
    (r"line \d+", "line <n>"),
    (r"\.py:\d+", ".py:<n>"),
]


def norm(text):
    for a, b in NORM:
        text = re.sub(a, b, text)
    return text


def run(root, rel, extra):
    script = root / rel
    cmd = ["uv", "run", "--no-sync", *extra, "python", script.name]
    try:
        p = subprocess.run(cmd, cwd=script.parent, env=ENV, capture_output=True, text=True, timeout=240)
        return p.returncode, p.stdout + ("\n--stderr--\n" + p.stderr if p.stderr.strip() else "")
    except subprocess.TimeoutExpired as e:
        return "timeout", (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")


def main(items):
    for item in items:
        rel, _, extra = item.partition("|")
        extra = extra.split() if extra else []
        res = {}
        for tag, root in (("old", OLD), ("new", NEW)):
            code, out = run(root, rel, extra)
            name = rel.replace("/", "__")
            (OUT / f"{name}.{tag}.txt").write_text(f"exit={code}\n{out}")
            res[tag] = (code, norm(out))
        same = res["old"] == res["new"]
        print(f"{'SAME' if same else 'DIFF'}  old={res['old'][0]} new={res['new'][0]}  {rel}", flush=True)
        if not same:
            d = difflib.unified_diff(res["old"][1].splitlines(), res["new"][1].splitlines(), "old", "new", n=1, lineterm="")
            (OUT / f"{rel.replace('/', '__')}.diff").write_text("\n".join(d))


if __name__ == "__main__":
    if OLD is None:
        sys.exit("set COMPARE_OLD to a checkout of the previous edition (with its own .venv)")
    OUT.mkdir(parents=True, exist_ok=True)
    main(sys.argv[1:])
