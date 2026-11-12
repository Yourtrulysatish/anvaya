# Development log

**2026-11-12**
- M1 Recon: read MiroFish (AGPL-3.0) source files + route tables; wrote `MIROFISH_ASSESSMENT.md`. Verified FreeModel.in live (OpenAI-compatible, Bearer, 29 models, 60 req/min); found fenced JSON in `json_object` mode.
- M4 Provider adapter: retries/limits/usage/cost + 6 mock-transport tests. Live smoke test OK.
- M5 Engine + population generator; live 24-agent/3-round LLM run (7 calls ≈ $0.019).
- M3 Observatory: Canvas2D + d3-force, particles per event type, communities, inspector, feed, timeline with checkpoints. DEMO run generated from the same engine (seed 42, 140 agents, 24 rounds).
- Repo created, GitHub Pages deployed.
- M6–M9: MiroFish adapter, ingestion, extraction/graph, analytics, scenarios, decisions, 15-section reports (MD/PDF/CSV), REST+SSE API, auth, rate limiting.
- Live end-to-end run with the real key (population → sim with LLM text + LLM-decided agents → scenario interpreted by the model → recommendations → report). Found and fixed: LLM spec parsing too strict (TypeError → silent fallback), `groups` metric overwritten at `sim_end`, int-vs-string key mismatch in `influence`, over-broad `model_unavailable` classification, Opus as default reasoning model (≈$0.8 for 5 calls) → economical default.
- M10: CI (pytest + demo reproducibility + frontend build + secret scan), Pages workflow, Dockerfile + Render blueprint, docs.

**Test status:** `pytest` 38 passed (provider, engine determinism/invariants, pause/stop, adapters, security, SSRF, upload validation, full offline API pipeline incl. SSE resume, exports). Frontend: `tsc -b` + `vite build` clean. Manual: UI flow (new analysis → LLM population → simulation) verified in a browser against a local backend.
