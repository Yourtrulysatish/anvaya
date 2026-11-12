# ANVAYA · अन्वय
**COLLECTIVE INTELLIGENCE. SIMULATED FUTURES.**  *Everything is connected. Understand how it evolves.*

Describe a situation → ANVAYA reads your sources, builds an artificial society, lets agents interact in a living visual universe, and turns the result into scenarios, ranked decisions and a traceable report.

**Live site (DEMO, no backend or key needed):** https://yourtrulysatish.github.io/anvaya/ · simulation universe: `/#/universe`

| | |
|---|---|
| Observatory | Canvas of hundreds of agents; animated particles per event type; Social / Influence / Network modes; inspector; interviews (live mode); feed; play/pause/resume/stop/restart/step ±/0.5–4×/timeline/replay |
| Intelligence | PDF · DOCX · XLSX · CSV · JSON · TXT · MD · URLs → entities, relations, facts (historical/current/assumption) with source quotes, contradictions, knowledge-graph explorer |
| Market layer | purchase funnel (unaware → … → advocate), Bass-style awareness, multinomial-logit brand choice by store, retailer listing decisions, budget-limited competitor promotions → awareness, trial, repeat, share, revenue index |
| Analytics | method selection, descriptive/trend stats, paired Monte Carlo scenarios, sensitivity, Bayesian summaries |
| Decisions & reports | ranked recommendations (impact/feasibility/urgency/risk) → 15-section report with FACT / ANALYSIS / ESTIMATE / SIMULATION / RECOMMENDATION labels; PDF, Markdown, CSV |
| Model provider | FreeModel.in (verified OpenAI-compatible), per-task models, connection test, retries, rate limits, token & cost tracking — key stays on the backend |

## Quick start
```bash
cp .env.example .env                       # set FREEMODEL_API_KEY (backend only, git-ignored)
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn anvaya.main:app --port 8000
cd ../frontend && npm ci && npm run dev    # http://localhost:5173
```
Tests: `cd backend && .venv/bin/python -m pytest` · Regenerate the DEMO data: `python scripts/make_demo.py`.
Docs: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/FREEMODEL.md`](docs/FREEMODEL.md) · [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) · [`docs/MIROFISH_ASSESSMENT.md`](docs/MIROFISH_ASSESSMENT.md) · [`docs/DEVLOG.md`](docs/DEVLOG.md)

## What is real, what is labelled
* **DEMO** = 140 synthetic agents, seeded model, template text, scripted round-9 price cut, replayed from recorded events. It is never mixed with LLM results.
* **Live** runs label every event `llm`/`template`, and `decided_by` `rule`/`llm`. Agents are fictional; traits not in your evidence are *simulation assumptions*. Outputs are model results, not predictions.

## Known limitations
* **Backend is not deployed by this repo's automation** (needs your hosting account; see DEPLOYMENT.md). Until then the public site is DEMO-only.
* MiroFish/OASIS adapter is unit-tested on the documented log format but **not run against a live MiroFish install**; imported runs have no opinion data.
* Single-topic-per-agent opinion model; interaction *structure* is rule-based (LLM writes text and decides a few key agents per round).
* Financial/causal methods are advisory only; no external web-search provider is bundled (add URLs yourself).
* Auth is email+password with bearer tokens in browser storage; SQLite + one worker (no horizontal scaling). PDF export uses a Latin-1 font (non-Latin names are transliterated to `?`).
* Canvas2D renders smoothly to a few hundred agents; thousands would need a WebGL renderer.

## Licence
AGPL-3.0 (see `LICENSE`, `NOTICE`). MiroFish (AGPL-3.0) and OASIS (CAMEL-AI, Apache-2.0) are credited; no MiroFish source is copied.
