# Reference solutions

Verified solutions for some exercises. Try each exercise before you read its solution. Run them from the repository root with `uv run python solutions/<file>.py`, after starting what the exercise's section starts:

| Solution | Needs running |
| --- | --- |
| `ex01_4_param_map.py`, `ex01_5_structured_bedrock.py`, `ex01_7_price_the_route.py` | Nothing offline (`LIVE=0`); AWS credentials with `LIVE=1` |
| `ex01_6_mantle_catalogue.py` | AWS credentials and `LIVE=1` |
| `ex01_8_ollama_extract.py` | Ollama with `qwen2.5:0.5b` on 11434 |
| `ex01_9_vllm_chargeback.py`, `ex01_10_provider_matrix.py` | Nothing: the fake vLLM runs inside the script, and nothing is sent |
| `ex01_11_reasoning_matrix.py` | Ollama with `qwen3:0.6b` on 11434 |
| `ex12_6_azure_wire.py` | `examples/azure/fake_azure.py 4018` |
| `ex12_7_vertex_wire.py` | `examples/vertex/make_fake_credentials.py`, then `examples/vertex/fake_vertex.py 4019` |
| `ex12_8_three_clouds.py` | The Bedrock, Azure and Vertex fakes (4015, 4018, 4019), and the proxy on `ex12_8_three_clouds.yaml` with fake AWS keys, `BEDROCK_ENDPOINT`, `AZURE_FOUNDRY_BASE` (`http://127.0.0.1:4018/myfoundry`), `AZURE_FOUNDRY_KEY`, `VERTEX_SA_FILE` and `VERTEX_API_BASE` set |
| `ex12_9_local_first.py` | Ollama with `qwen2.5:0.5b` on 11434, `examples/_fake_upstream.py 4011`, and the proxy on `ex12_9_local_first.yaml` with `OLLAMA_API_BASE`, `ANTHROPIC_API_KEY` and `FAKE_UPSTREAM` set |
| `ex12_10_mantle_mix.py` | AWS credentials, and the proxy on `ex12_10_mantle_mix.yaml` with `LITELLM_MASTER_KEY` set (no fake: Mantle is called for real) |
| `ex19a_*`, `ex19b_*`, `ex19c_1_*` | Lens and the proxy from section 19 (`examples/lens/`); 19c also needs Bedrock |
| `ex20_5_shared_cap.py` | `examples/proxy/config.yaml` with `DATABASE_URL` set, on port 4106 (`PROXY_URL` to change it) |
| `ex20_6_team_keys.py` | The same proxy; add `--capped` when `general_settings.apply_user_budget_to_team_keys: true` is set |

The proxy solutions need `LITELLM_MASTER_KEY` set to the proxy's master key; 12.6 and 12.7 call the fakes directly with the SDK.
