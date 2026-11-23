# Building TUTORIAL.html

`TUTORIAL.html` is generated from `TUTORIAL.md`. The current page supplies the CSS, navigation and script, so pass it as the template. Run from the repository root:

```bash
uv run --with markdown-it-py --with pygments python build/build_html_paged.py TUTORIAL.md TUTORIAL.html TUTORIAL.html
```

Run it from the repository root, not from elsewhere: uv can resolve a different Pygments there, which rewrites every code block.

Mermaid blocks are not rendered in the browser. Each is replaced by a hand-drawn SVG:

- `figures.json` holds the figures already on the page, keyed by a block's `%% fig: <name>` marker, or by a hash of its code. `extract_figures.py TUTORIAL.md TUTORIAL.html figures.json` regenerates it from the page.
- `extra_figures.py` holds figures added since. A new Mermaid block needs a `%% fig: <name>` marker and an SVG here, or the build fails to find it.
- `uv run --with cairosvg python build/render.py <name> out.png` renders one extra figure to PNG to check its layout.

## Versions and editions

`pyproject.toml` is the source of truth: `version` is the tutorial's version and the `litellm` pin is the LiteLLM version. The build runs `check_versions.py` first and stops if the byline, the "Which version this covers" paragraph, the README, `uv.lock`, a Docker image tag or a link to LiteLLM's source names another version. Run it on its own with `python3 build/check_versions.py`.

Each LiteLLM version is an edition on its own branch (`litellm-<version>`); `main` is the newest. To work on two at once, give each its own worktree and `.venv`: `git worktree add ../litellm-tutorial-1.109.1 litellm-1.109.1`.

- **A change for one edition only** is committed on that edition's branch.
- **A change for every edition** is committed once and copied with `git cherry-pick`. Never merge one edition branch into another: the merge brings the pin and every version-specific output with it.
- **Generated files** (`TUTORIAL.html`, `uv.lock`) are not merged by hand. On a conflict take either side, then rebuild the page and run `uv lock`.
- **A runnable change** is run again on every edition it lands on.

To release an edition, bump `version` in `pyproject.toml` and the places the check names, run `uv lock` and the build, commit, then tag and push:

```bash
git tag -a "$(python3 build/check_versions.py --tag)" -m "LiteLLM tutorial release"
git push origin --tags
```

[`compare/`](compare/) runs the examples under the old and the new edition side by side, so only output that really changed gets rewritten. To start an edition for a new LiteLLM version: branch the current `main` as `litellm-<old version>`, push it, then on `main` change the pin and image tags, run `uv lock`, re-run every example and update the outputs and each "in <old version>" claim, add a row to the README's editions table, and release.

## Publishing to the blog

`publish_blog.py` copies a released edition to the blog repository (chuan2019.github.io), at `tutorials/litellm/<LiteLLM version>/`: the page as `index.html` and the self-test as `exercises/exam.html`. It refuses to run unless the working tree is clean and HEAD carries this edition's release tag, because every link to a file in this repository is rewritten to point at GitHub at that tag:

```bash
python3 build/publish_blog.py ../chuan2019.github.io
```

Then add the edition to the blog's `tutorials/litellm/index.md` if it is new, and deploy the blog with its `scripts/deploy.sh`.
