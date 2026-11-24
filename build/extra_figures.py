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

GATEWAY_REFERENCE = """<svg viewBox="0 0 1100 1060" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="arr9" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker></defs>
  <g class="edges">
    <path d="M270,150 L308,146" marker-end="url(#arr9)"/>
    <path d="M270,250 C288,250 286,530 298,530" marker-end="url(#arr9)"/>
    <path d="M270,320 C286,320 288,671 308,671" marker-end="url(#arr9)"/>
    <path d="M270,380 C282,380 288,818 308,818" marker-end="url(#arr9)"/>
    <path d="M810,406 L848,406" marker-end="url(#arr9)"/>
    <path d="M145,56 L145,90" stroke-dasharray="6 4"/>
    <path d="M560,56 L560,90" stroke-dasharray="6 4"/>
    <path d="M965,56 L965,90" stroke-dasharray="6 4"/>
    <path d="M145,620 L145,1000" stroke-dasharray="6 4"/>
    <path d="M560,974 L560,1000" stroke-dasharray="6 4"/>
    <path d="M965,854 L965,1000" stroke-dasharray="6 4"/>
    <path d="M810,198 L835,198 L835,690 L850,690" stroke-dasharray="6 4"/>
    <path d="M810,725 L850,725" stroke-dasharray="6 4"/>
  </g>
  <g class="node accent"><rect x="20" y="12" width="1060" height="44" rx="8"/><text x="550" y="31">Identity &amp; access</text><text x="550" y="48" class="sub">users · roles · permissions</text></g>
  <g class="node accent"><rect x="20" y="1000" width="1060" height="44" rx="8"/><text x="550" y="1019">Observability</text><text x="550" y="1036" class="sub">OpenTelemetry · metrics · traces · cost · audit</text></g>
  <g class="group"><rect x="20" y="90" width="250" height="320" rx="10"/></g>
  <text x="145" y="112">Consumers</text>
  <g class="node"><rect x="35" y="126" width="220" height="58" rx="8"/><text x="145" y="152">Chats &amp; assistants</text><text x="145" y="169" class="sub">LibreChat · custom chat UIs</text></g>
  <g class="node"><rect x="35" y="196" width="220" height="58" rx="8"/><text x="145" y="222">Messaging bots</text><text x="145" y="239" class="sub">Teams / Slack bots</text></g>
  <g class="node"><rect x="35" y="266" width="220" height="58" rx="8"/><text x="145" y="292">Services</text><text x="145" y="309" class="sub">your back-end services</text></g>
  <g class="node"><rect x="35" y="336" width="220" height="58" rx="8"/><text x="145" y="362">Vendor AI apps</text><text x="145" y="379" class="sub">Claude, ChatGPT, …</text></g>
  <g class="group"><rect x="20" y="440" width="250" height="180" rx="10" style="stroke-dasharray:none"/></g>
  <text x="145" y="462">Platform console</text>
  <g class="node"><rect x="35" y="476" width="220" height="58" rx="8"/><text x="145" y="502">Admin &amp; self-service</text><text x="145" y="519" class="sub">keys · teams · budgets · usage</text></g>
  <g class="node"><rect x="35" y="546" width="220" height="58" rx="8"/><text x="145" y="564.5">Playground &amp; evaluation</text><text x="145" y="581.5" class="sub">try prompts · compare models</text><text x="145" y="596.5" class="sub">eval sets</text></g>
  <g class="group"><rect x="300" y="90" width="520" height="356" rx="10" style="stroke-dasharray:none"/></g>
  <text x="560" y="112">LLM gateway</text>
  <g class="node"><rect x="310" y="124" width="500" height="44" rx="8"/><text x="560" y="143">API</text><text x="560" y="160" class="sub">chat completions · responses · batch · models</text></g>
  <g class="node"><rect x="310" y="176" width="500" height="44" rx="8"/><text x="560" y="195">Enforcement</text><text x="560" y="212" class="sub">permissions · quotas · guardrail checks</text></g>
  <g class="node"><rect x="310" y="228" width="245.0" height="44" rx="8"/><text x="432.5" y="247">Routing</text><text x="432.5" y="264" class="sub">model choice · fallbacks · retries</text></g>
  <g class="node"><rect x="565.0" y="228" width="245.0" height="44" rx="8"/><text x="687.5" y="247">Smart router</text><text x="687.5" y="264" class="sub">best-fit model per request</text></g>
  <g class="node"><rect x="310" y="280" width="500" height="44" rx="8"/><text x="560" y="299">Response cache</text><text x="560" y="316" class="sub">exact · semantic</text></g>
  <g class="node"><rect x="310" y="332" width="500" height="44" rx="8"/><text x="560" y="351">Model registry &amp; pricing</text><text x="560" y="368" class="sub">model info · rates · cost per call</text></g>
  <g class="node"><rect x="310" y="384" width="500" height="44" rx="8"/><text x="560" y="403">Provider adapters</text><text x="560" y="420" class="sub">request/response translation per provider</text></g>
  <g class="group"><rect x="300" y="470" width="520" height="120" rx="10" style="stroke-dasharray:none"/></g>
  <text x="560" y="492">Context management</text>
  <g class="node"><rect x="310.0" y="504" width="119.0" height="74" rx="8"/><text x="369.5" y="529.5">Sessions &amp;</text><text x="369.5" y="546.5">history</text><text x="369.5" y="563.5" class="sub">state · compaction</text></g>
  <g class="node"><rect x="437.0" y="504" width="119.0" height="74" rx="8"/><text x="496.5" y="537">Conversation</text><text x="496.5" y="554">search</text></g>
  <g class="node"><rect x="564.0" y="504" width="119.0" height="74" rx="8"/><text x="623.5" y="545.5">Memory</text></g>
  <g class="node"><rect x="691.0" y="504" width="119.0" height="74" rx="8"/><text x="750.5" y="530.5">Knowledge</text><text x="750.5" y="547.5" class="sub">RAG · documents</text><text x="750.5" y="562.5" class="sub">vector search</text></g>
  <g class="group"><rect x="300" y="614" width="520" height="360" rx="10" style="stroke-dasharray:none"/></g>
  <text x="560" y="636">Capabilities hub</text>
  <g class="node"><rect x="310" y="648" width="245.0" height="46" rx="8"/><text x="432.5" y="668">Manifest</text><text x="432.5" y="685" class="sub">what a client gets: capabilities &amp; config</text></g>
  <g class="node"><rect x="565.0" y="648" width="245.0" height="46" rx="8"/><text x="687.5" y="675.5">Capability registry</text></g>
  <g class="node"><rect x="310" y="702" width="245.0" height="46" rx="8"/><text x="432.5" y="722">Credential vault</text><text x="432.5" y="739" class="sub">outbound OAuth · per-user tokens</text></g>
  <g class="node"><rect x="565.0" y="702" width="245.0" height="46" rx="8"/><text x="687.5" y="722">Enforcement</text><text x="687.5" y="739" class="sub">permissions · quotas · guardrail checks</text></g>
  <g class="group"><rect x="310" y="758" width="500" height="98" rx="10" style="stroke-dasharray:none"/></g>
  <text x="560" y="780">Capabilities · runtime &amp; proxy</text>
  <g class="node"><rect x="320.0" y="792" width="91.2" height="52" rx="8"/><text x="365.6" y="822.5">MCP</text></g>
  <g class="node"><rect x="417.2" y="792" width="91.2" height="52" rx="8"/><text x="462.8" y="822.5">Skills</text></g>
  <g class="node"><rect x="514.4" y="792" width="91.2" height="52" rx="8"/><text x="560" y="822.5">Prompts</text></g>
  <g class="node"><rect x="611.6" y="792" width="91.2" height="52" rx="8"/><text x="657.2" y="822.5" style="font-size:13px">Instructions</text></g>
  <g class="node"><rect x="708.8" y="792" width="91.2" height="52" rx="8"/><text x="754.4" y="815">Agents</text><text x="754.4" y="832" class="sub">as capabilities</text></g>
  <g class="group"><rect x="310" y="866" width="500" height="98" rx="10" style="stroke-dasharray:none"/></g>
  <text x="560" y="888">Agents &amp; flows</text>
  <g class="node"><rect x="320.0" y="900" width="154.66666666666666" height="52" rx="8"/><text x="397.333" y="930.5">Runtime</text></g>
  <g class="node"><rect x="482.66666666666663" y="900" width="154.66666666666666" height="52" rx="8"/><text x="560" y="930.5">Builder</text></g>
  <g class="node"><rect x="645.3333333333333" y="900" width="154.66666666666666" height="52" rx="8"/><text x="722.667" y="923">Agent endpoint</text><text x="722.667" y="940" class="sub">OpenAI-compatible</text></g>
  <g class="group"><rect x="850" y="90" width="230" height="356" rx="10" style="stroke-dasharray:none"/></g>
  <text x="965" y="112">Model providers</text>
  <g class="node"><rect x="865" y="126" width="200" height="66" rx="8"/><text x="965" y="163.5">Bedrock Runtime</text></g>
  <g class="node"><rect x="865" y="206" width="200" height="66" rx="8"/><text x="965" y="243.5">Bedrock Mantle</text></g>
  <g class="node"><rect x="865" y="286" width="200" height="66" rx="8"/><text x="965" y="316">Custom deployments</text><text x="965" y="333" class="sub">e.g. SageMaker</text></g>
  <g class="group"><rect x="865" y="366" width="200" height="66" rx="8"/><text x="965" y="396">Local LLMs</text><text x="965" y="413" class="sub">on-prem</text></g>
  <g class="group"><rect x="850" y="614" width="230" height="240" rx="10" style="stroke-dasharray:none"/></g>
  <text x="965" y="636">Policy &amp; guardrails</text>
  <g class="node"><rect x="865" y="650" width="200" height="80" rx="8"/><text x="965" y="687">Quotas &amp; budgets</text><text x="965" y="704" class="sub">tokens · cost · tool calls</text></g>
  <g class="node"><rect x="865" y="744" width="200" height="94" rx="8"/><text x="965" y="773">Guardrails</text><text x="965" y="790" class="sub">PII · prompt injection</text><text x="965" y="805" class="sub">toxicity</text><text x="965" y="820" class="sub">(Bedrock Guardrails)</text></g>
</svg>"""

EXTRA = {
    "lens": (LENS, "How Lens fits in. Your agent sends model calls to the LiteLLM proxy with a virtual key, and the proxy "
             "calls the model providers. The agent also sends its OpenTelemetry spans straight to Lens with a tracing "
             "key. The proxy sends Lens a request record with the cost of every call. Lens stores spans and records in "
             "ClickHouse, and you read them through the Lens UI, API or SQL. For investigations, Lens sends selected "
             "trace content to an analysis model, called directly or through the proxy."),
    "gateway-reference": (GATEWAY_REFERENCE, "A gateway reference design. Identity and access run across the top and observability across the bottom. "
                          "On the left, consumers (chats and assistants, messaging bots, services, vendor AI apps) and a platform "
                          "console (admin and self-service, playground and evaluation). In the middle, the LLM gateway (API, "
                          "enforcement, routing, smart router, response cache, model registry and pricing, provider adapters), "
                          "context management (sessions and history, conversation search, memory, knowledge) and a capabilities hub"
                          " (manifest, capability registry, credential vault, enforcement, the MCP, skills, prompts, instructions "
                          "and agent capabilities, and agents and flows with a runtime, a builder and an OpenAI-compatible agent "
                          "endpoint). On the right, model providers (Bedrock Runtime, Bedrock Mantle, custom deployments such as "
                          "SageMaker, on-prem local LLMs) and policy and guardrails (quotas and budgets, guardrails). Consumers "
                          "call the API, context management and the capabilities hub; the provider adapters call the model "
                          "providers; both enforcement points check against the policy and guardrails."),
}
