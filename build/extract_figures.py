"""Extract each Mermaid block's rendered figure from the committed TUTORIAL.html into figures.json."""
import hashlib, json, re, sys
from pathlib import Path

md, page, out = map(Path, sys.argv[1:4])
blocks = re.findall(r"```mermaid\n(.*?)```", md.read_text(), re.S)
figs = re.findall(r'<figure class="diagram".*?</figure>\n', page.read_text(), re.S)
assert len(blocks) == len(figs), (len(blocks), len(figs))


def key(code):
    m = re.search(r"%% fig: ([\w-]+)", code)
    return m.group(1) if m else "sha:" + hashlib.sha1(code.encode()).hexdigest()[:12]


out.write_text(json.dumps({key(b): f for b, f in zip(blocks, figs)}, indent=1))
print(len(figs), "figures:", [key(b) for b in blocks])
