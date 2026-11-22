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
