"""Build the paged LiteLLM TUTORIAL.html from TUTORIAL.md, reusing a template page's CSS, nav and script.

Usage: build_html_paged.py TUTORIAL.md TUTORIAL.html TEMPLATE.html
Figures: figures.json (extracted from the committed page) plus extra_figures.py.
"""
import hashlib
import json
import html
import re
import sys
from pathlib import Path

from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

sys.path.insert(0, str(Path(__file__).parent))
from extra_figures import EXTRA

FIGS = json.loads((Path(__file__).parent / "figures.json").read_text())

src, dst, style_src = map(Path, sys.argv[1:4])
ref = style_src.read_text()
STYLE = ref[ref.index("<style>"):ref.index("</style>") + len("</style>")]
SCRIPT = ref[ref.rindex("<script>"):ref.rindex("</script>") + len("</script>")]
NAV_TOOLS = ref[ref.index('<button class="menu-btn"'):ref.index('<div id="tocList">')]


def slug(text, seen):
    s = re.sub(r"<[^>]+>", "", text).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", html.unescape(s)).strip("-")
    base, n = s, seen.get(s, 0)
    seen[base] = n + 1
    return base if n == 0 else f"{base}-{n + 1}"


def render_fence(self, tokens, idx, options, env):
    tok = tokens[idx]
    lang = tok.info.strip().split()[0] if tok.info.strip() else "text"
    code = tok.content
    if lang == "mermaid":
        m = re.search(r"%% fig: ([\w-]+)", code)
        key = m.group(1) if m else "sha:" + hashlib.sha1(code.encode()).hexdigest()[:12]
        if key in EXTRA:
            svg, label = EXTRA[key]
            return (f'\n<figure class="diagram" role="img" aria-label="{html.escape(label)}">\n'
                    f'<div class="diagram-scroll">\n{svg}\n</div>\n</figure>\n')
        if key not in FIGS:
            raise SystemExit(f"mermaid block without a known figure ({key}):\n{code[:200]}")
        return "\n" + FIGS[key]
    if lang == "text":
        return (f'<div class="code"><button type="button" class="copy" aria-label="Copy code">Copy</button>'
                f'<pre class="hl"><code>{html.escape(code)}</code></pre></div>\n')
    try:
        body = highlight(code, get_lexer_by_name(lang), HtmlFormatter(nowrap=True))
    except ClassNotFound:
        body = html.escape(code)
    return (f'<div class="code"><span class="lang">{html.escape(lang)}</span><button type="button" class="copy" '
            f'aria-label="Copy code">Copy</button><pre class="hl"><code>{body}</code></pre></div>\n')


md = MarkdownIt("commonmark", {"html": True}).enable("table")
md.add_render_rule("fence", render_fence)
text = src.read_text()
tokens = md.parse(text)

seen = {}
for i, tok in enumerate(tokens):
    if tok.type == "heading_open":
        tok.attrSet("id", slug(tokens[i + 1].content, seen))
body = md.renderer.render(tokens, md.options, {})
body = re.sub(r'<a href="(https?://[^"]+)">', r'<a href="\1" target="_blank" rel="noopener">', body)
body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")

h1 = re.search(r"<h1[^>]*>(.*?)</h1>\n", body)
title = re.sub(r"^Tutorial: ", "", h1.group(1))
byline = re.search(r"<p>(.*?)</p>\n", body[h1.end():]).group(1)
rest = body[h1.end():].split("\n", 1)[1]
rest = rest.replace("<hr />\n", "")

parts = re.split(r'(?=<h2 id=")', rest)
pages = [p for p in parts if p.startswith("<h2")]
info = []
for p in pages:
    m = re.match(r'<h2 id="([^"]+)">(.*?)</h2>', p)
    subs = re.findall(r'<h3 id="([^"]+)">(.*?)</h3>', p)
    info.append((m.group(1), re.sub(r"\s*\(.*\)$", "", re.sub(r"<[^>]+>", "", m.group(2))), subs))

toc = ["<ul>"]
for pid, name, subs in info:
    inner = "".join(f'<li><a href="#{sid}">{html.escape(html.unescape(re.sub(r"<[^>]+>", "", sname)))}</a></li>' for sid, sname in subs)
    toc.append(f'<li data-page="{pid}"><a href="#{pid}">{html.escape(name, quote=False)}</a>'
               + (f"<ul>{inner}</ul>" if inner else "") + "</li>")
toc.append("</ul>")

sections = []
for n, (p, (pid, name, _)) in enumerate(zip(pages, info)):
    head = ""
    if n == 0:
        head = f'<h1>{h1.group(1)}</h1>\n<p class="byline">{byline}</p>\n'
    prev_link = (f'<a class="prev" href="#{info[n - 1][0]}"><span>Previous</span>{html.escape(info[n - 1][1], quote=False)}</a>'
                 if n else "<span></span>")
    next_link = (f'<a class="next" href="#{info[n + 1][0]}"><span>Next</span>{html.escape(info[n + 1][1], quote=False)}</a>'
                 if n + 1 < len(info) else "<span></span>")
    sections.append(
        f'<section class="page" data-page="{pid}" data-title="{html.escape(name)}">\n{head}'
        f'<p class="crumb">Page {n + 1} of {len(info)}</p>{p.rstrip()}\n'
        f'<nav class="pager" aria-label="Section navigation">{prev_link}{next_link}</nav>\n</section>')

page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
{STYLE}
</head>
<body>
{NAV_TOOLS}<div id="tocList">{"".join(toc)}</div>
</nav>
<main>
<article>
{chr(10).join(sections)}
</article>
</main>
<button class="to-top" type="button" id="toTop" aria-label="Back to top">↑ Top</button>
{SCRIPT}
</body>
</html>
"""
dst.write_text(page)
print(f"wrote {dst}: {len(info)} pages, {len(page)} bytes")
