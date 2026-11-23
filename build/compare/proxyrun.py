"""Start fakes once, then per edition start a proxy, run its clients, stop it, and diff the client output.

Usage: COMPARE_OLD=../litellm-tutorial-<old> proxyrun.py specs/s13-keys.json ...
"""
import difflib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from diffrun import NEW, OLD, OUT, ENV, norm


def wait(url, secs=90):
    end = time.time() + secs
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def start(cmd, cwd, env, log):
    return subprocess.Popen(cmd, cwd=cwd, env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT, start_new_session=True)


def stop(p):
    if p and p.poll() is None:
        os.killpg(p.pid, signal.SIGTERM)
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)


def main(spec_file):
    spec = json.loads(Path(spec_file).read_text())
    name, port = spec["name"], spec.get("port", 4000)
    env = {**ENV, **spec.get("env", {})}
    fakes, res = [], {}
    try:
        for i, f in enumerate(spec.get("fakes", [])):
            fakes.append(start(["uv", "run", "--no-sync", "python", *f["cmd"]], NEW / f["cwd"], env, OUT / f"{name}.fake{i}.log"))
            if f.get("wait"):
                wait(f["wait"], 30)
        for tag, root in (("old", OLD), ("new", NEW)):
            for pre in spec.get("pre", []):
                subprocess.run(["uv", "run", "--no-sync", "python", *pre["cmd"]], cwd=root / pre["cwd"], env=env, capture_output=True)
            e = {k: v.replace("$ROOT", str(root)).replace("$TAG", tag) for k, v in env.items()}
            for sh in spec.get("pre_sh", []):
                subprocess.run(["bash", "-c", sh], env=e, capture_output=True)
            proxy = None
            if spec.get("config"):
                proxy = start(["uv", "run", "--no-sync", "litellm", "--config", spec["config"], "--port", str(port)],
                              root / spec["cwd"], e, OUT / f"{name}.proxy.{tag}.log")
            try:
                up = wait(f"http://127.0.0.1:{port}/health/liveliness", spec.get("boot", 180)) if proxy else "n/a"
                outs = []
                for c in spec["clients"]:
                    p = subprocess.run(["uv", "run", "--no-sync", *c["cmd"]], cwd=root / c["cwd"], env=e,
                                       capture_output=True, text=True, timeout=300)
                    outs.append(f"$ {' '.join(c['cmd'])}  exit={p.returncode}\n{p.stdout}" + (f"--stderr--\n{p.stderr}" if p.stderr.strip() else ""))
                out = f"proxy up={up}\n" + "\n".join(outs)
            finally:
                stop(proxy)
                time.sleep(1)
            (OUT / f"{name}.{tag}.txt").write_text(out)
            res[tag] = norm(out)
    finally:
        for f in fakes:
            stop(f)
    same = res.get("old") == res.get("new")
    print(f"{'SAME' if same else 'DIFF'}  {name}", flush=True)
    if not same:
        d = difflib.unified_diff(res["old"].splitlines(), res["new"].splitlines(), "old", "new", n=1, lineterm="")
        (OUT / f"{name}.diff").write_text("\n".join(d))


if __name__ == "__main__":
    if OLD is None:
        sys.exit("set COMPARE_OLD to a checkout of the previous edition (with its own .venv)")
    OUT.mkdir(parents=True, exist_ok=True)
    for s in sys.argv[1:]:
        main(s)
