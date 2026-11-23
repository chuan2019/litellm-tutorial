# Comparing two editions

Scripts used to move the tutorial to a new LiteLLM release. They run the same examples under the previous edition and the new one and report only the output that changed, after normalising IDs, timestamps, durations and hashes. Random splits, token counters in the fakes and tracebacks with paths still show up; read each diff.

Set up a checkout of the previous edition with its own environment, next to this repository:

```bash
git worktree add ../litellm-tutorial-1.109.1 litellm-1.109.1
(cd ../litellm-tutorial-1.109.1 && uv sync --group notebooks)
export COMPARE_OLD=$PWD/../litellm-tutorial-1.109.1
```

- `diffrun.py` runs scripts that need nothing else running (sections 1–11, 14, 17, 18a, 22a–d, `agents/16b_a2a_sdk.py`, and the Lens 19a scripts with Lens up). Section 1's `01c`–`01f` run offline too; `01e_ollama.py` needs Ollama with `qwen2.5:0.5b` and `qwen3:0.6b`. Run `01c` and `01d` again with `LIVE=1` by hand: their live output is what the tutorial shows.
- `proxyrun.py` takes the JSON files in `specs/`: each starts its fakes, then for each edition runs any `pre_sh` commands, starts the proxy and runs the clients. Proxy specs that use Postgres expect the container `litellm-tutorial-db` on port 55432, recreate the `litellm` database before each edition, and need `prisma generate` run once in both environments.

Results go to `runs/` (git-ignored): `<name>.old.txt`, `<name>.new.txt` and `<name>.diff`.

Not in `specs/`: section 19 (its spec needs the Lens tokens from `~/lens/lens-0.1.0/deploy/lens/.env`, so write it locally and keep it out of git), section 21's production stack and Redis drill, Setup's quick start and the notebooks (real Bedrock calls), and section 12's Bedrock Mantle proxy example and exercise 12.10 (real Mantle calls). Run those by hand as the tutorial describes.
