"""Render an extra figure to PNG with the page's diagram CSS, for checking the layout."""
import sys
import cairosvg
from extra_figures import EXTRA

CSS = """.node rect{fill:#f3f4f6;stroke:#6b7280;stroke-width:1.2}.node.accent rect{fill:#e0ecff;stroke:#2563eb}
.node.partial rect{fill:#fff4c2;stroke:#c9a227}.node.gap rect{fill:#dcebfb;stroke:#3b7fc4}text.sub.lic,text .lic{fill:#c62828;font-weight:700}
text{fill:#111827;font:600 14px sans-serif;text-anchor:middle}text.sub{font-weight:400;font-size:12px;fill:#6b7280}
.edges path{fill:none;stroke:#6b7280;stroke-width:1.5}.arrowhead{fill:#6b7280}
text.lbl{font-weight:400;font-size:12px;stroke:none}"""
svg = EXTRA[sys.argv[1]][0].replace("<defs>", f"<style>{CSS}</style><rect width='100%' height='100%' fill='white'/><defs>", 1)
cairosvg.svg2png(bytestring=svg.encode(), write_to=sys.argv[2], output_width=1350)
