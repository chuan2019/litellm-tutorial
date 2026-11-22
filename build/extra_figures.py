"""Hand-drawn SVGs for Mermaid blocks added after figures.json was extracted, keyed by their %% fig: marker."""

LENS = """<svg viewBox="0 0 900 380" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="arr8" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker></defs>
  <g class="edges">
    <path d="M192,68 L363,68" marker-end="url(#arr8)"/>
    <path d="M537,68 L708,68" marker-end="url(#arr8)"/>
    <path d="M105,96 C105,170 230,228 363,228" marker-end="url(#arr8)"/>
    <path d="M450,96 L450,198" marker-end="url(#arr8)"/>
    <path d="M192,300 C290,300 300,248 363,248" marker-end="url(#arr8)"/>
    <path d="M450,258 L450,306" marker-end="url(#arr8)" marker-start="url(#arr8)"/>
    <path d="M537,228 L708,228" marker-end="url(#arr8)"/>
    <path d="M795,200 C795,140 640,110 537,90" stroke-dasharray="6 4"/>
  </g>
  <text x="278" y="58" class="lbl">model calls (virtual key)</text>
  <text x="622" y="58" class="lbl">provider calls</text>
  <text x="190" y="196" class="lbl">OTLP spans (tracing key)</text>
  <text x="450" y="150" class="lbl">request records with cost</text>
  <text x="622" y="218" class="lbl">selected trace content</text>
  <text x="690" y="132" class="lbl">or through the proxy</text>
  <g class="node"><rect x="20" y="40" width="172" height="56" rx="8"/><text x="106" y="63">Your agent</text><text x="106" y="81" class="sub">OTel spans + tracing key</text></g>
  <g class="node"><rect x="365" y="40" width="172" height="56" rx="8"/><text x="451" y="63">LiteLLM proxy</text><text x="451" y="81" class="sub">virtual keys, spend</text></g>
  <g class="node"><rect x="710" y="40" width="172" height="56" rx="8"/><text x="796" y="63">Model providers</text><text x="796" y="81" class="sub">Bedrock, OpenAI, ...</text></g>
  <g class="node accent"><rect x="365" y="200" width="172" height="58" rx="8"/><text x="451" y="224">Lens</text><text x="451" y="242" class="sub">ingest, normalize, review</text></g>
  <g class="node accent"><rect x="710" y="200" width="172" height="58" rx="8"/><text x="796" y="224">Analysis model</text><text x="796" y="242" class="sub">investigations</text></g>
  <g class="node"><rect x="20" y="272" width="172" height="56" rx="8"/><text x="106" y="295">You</text><text x="106" y="313" class="sub">UI, API, SQL</text></g>
  <g class="node"><rect x="365" y="308" width="172" height="56" rx="8"/><text x="451" y="331">ClickHouse</text><text x="451" y="349" class="sub">spans, request records</text></g>
</svg>"""

EXTRA = {
    "lens": (LENS, "How Lens fits in. Your agent sends model calls to the LiteLLM proxy with a virtual key, and the proxy "
             "calls the model providers. The agent also sends its OpenTelemetry spans straight to Lens with a tracing "
             "key. The proxy sends Lens a request record with the cost of every call. Lens stores spans and records in "
             "ClickHouse, and you read them through the Lens UI, API or SQL. For investigations, Lens sends selected "
             "trace content to an analysis model, called directly or through the proxy."),
}
