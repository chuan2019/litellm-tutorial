# LiteLLM by Worked Example

A hands-on tutorial for [LiteLLM](https://github.com/BerriAI/litellm), the Python SDK and the proxy: 23 sections, each a practical use case with a runnable script, its real output and exercises.

**Version 0.2.0, written for LiteLLM 1.110.2.** Every output in the tutorial was produced with that release, which `pyproject.toml` pins. On another LiteLLM version, expect differences.

## Editions

Each LiteLLM version the tutorial covers is an edition with its own branch, improved independently. `main` holds the newest edition. Releases are tags named `v<tutorial version>-litellm<LiteLLM version>`; pick the edition that matches the LiteLLM you run.

| LiteLLM | Branch | Releases |
| --- | --- | --- |
| 1.110.2 | [`litellm-1.110.2`](../../tree/litellm-1.110.2) (also `main`) | [`v*-litellm1.110.2`](../../tags) |
| 1.109.1 | [`litellm-1.109.1`](../../tree/litellm-1.109.1) | [`v*-litellm1.109.1`](../../tags) |

## Read it

- [`TUTORIAL.md`](TUTORIAL.md): the tutorial.
- `TUTORIAL.html`: the same content as a standalone page with navigation and search. Open it in a browser, or read it online at https://chuan2019.github.io/tutorials/litellm/.
- `exercises/exam.html`: a self-test.

## Run it

Needs [uv](https://docs.astral.sh/uv/) and Python 3.12 or newer. Most examples run offline with mocked replies.

```bash
uv sync
cd examples
export LITELLM_LOCAL_MODEL_COST_MAP=True
uv run python 01_first_call.py
```

The tutorial's Setup section covers the rest, including Docker, AWS Bedrock and the notebooks (`uv sync --group notebooks`).

## Layout

| Path | What it holds |
| --- | --- |
| `examples/` | One script per section, plus the proxy configs and local fakes they use |
| `exercises/` | Exercise setup and the self-test; your own exercise files are git-ignored |
| `solutions/` | Verified solutions for some exercises |
| `notebooks/` | Sections 1–11 as Jupyter notebooks that call AWS Bedrock |
| `build/` | The script that generates `TUTORIAL.html` from `TUTORIAL.md` |

## Licence

The code (examples, solutions, exercise helpers, notebook code cells and build scripts) is MIT-licensed; see [`LICENSE`](LICENSE). The tutorial text and figures are © 2026 Chuan Zhang, all rights reserved: read and link to them freely, but ask before copying or republishing them.
