# FreeModel.in integration — what was verified

Checked on 2026-11-12 against the public pages (`freemodel.in`, `/docs/chat-completions`, `/models`) **and live calls with a real key**.

| Item | Finding | Source |
|---|---|---|
| Base URL | `https://freemodel.in/v1` | docs + live |
| Auth | `Authorization: Bearer <key>` (keys start `fm_`) | live (200 OK; CORS also lists `x-api-key`, `anthropic-version`) |
| Endpoints used | `GET /models`, `POST /chat/completions` | docs + live |
| Format | OpenAI-style request/response, `usage{prompt,completion,total}` + `completion_tokens_details.reasoning_tokens` | live |
| Models | 29 in the live catalogue, each with `context_window`, `capabilities[]`, `pricing{input_per_1k,output_per_1k}` | live `/models` |
| Context windows | 256k – 1M tokens, per model | live `/models` |
| JSON output | `response_format:{"type":"json_object"}` accepted, but replies may still be wrapped in ```json fences → ANVAYA parses tolerantly | live |
| Tools / streaming | listed per model (`tools`, `streaming`); **ANVAYA does not currently use either** | `/models` |
| `max_tokens` | server raises values < 2048 to 2048; reasoning models spend tokens before visible output (empty content + `finish_reason: length` possible → ANVAYA retries with a larger budget) | docs |
| Rate limit | `x-ratelimit-limit: 60` (requests/min), `x-ratelimit-limit-tokens: 1000000` + remaining headers | live headers |
| Empty balance | HTTP 402 | docs |
| Web search | some models advertise `web_search`; **not assumed or used** — research uses user-supplied URLs (a dedicated provider can be configured) | `/models` |
| Embeddings | key scope mentioned, no endpoint documented → **not used** (no vector DB needed) | docs |

## Task → model assignment
`GET /api/settings` shows the live assignment; defaults are chosen from the live catalogue by capability/price hints, never hard-wired:
`reasoning`, `report` → a strong, economical model (currently `claude-sonnet-5-5`); `agent`, `extraction` → fast cheap JSON-capable model (currently `gemini-3.7-flash`);
`summarisation` → cheapest (currently `glm-5.3-flash`). Override in **Settings** (deployment admin) or with `ANVAYA_MODEL_<TASK>`.
If a configured model is missing from the catalogue the API returns `model_unavailable` instead of silently substituting.

## Error handling in `llm/provider.py`
401/403 → `auth`, 402 → `payment`, 429 → `rate_limit` (honours `Retry-After`/`x-ratelimit-reset`, exponential backoff, ≤4 retries), 5xx/timeouts → retried, unknown model → `model_unavailable`.
A client-side sliding window (default 50 req/min, below the provider's 60) paces all calls; token usage and estimated cost are stored per task/model/project.
