# Architecture

```
frontend/ (React 19 + TS + Tailwind 4, Canvas2D + d3-force)        backend/anvaya/ (FastAPI, Python 3.12)
 ├ observatory/  renderer.ts  Observatory.tsx  Inspector.tsx        ├ api.py        REST + SSE, jobs, access control
 ├ lib/simState.ts  Playback (checkpoints, seek, replay)            ├ security.py   scrypt auth, sessions, rate limit
 ├ lib/api.ts       fetch client + SSE reconnect/dedupe             ├ ingest.py     PDF/DOCX/XLSX/CSV/JSON/TXT/MD/URL (SSRF-safe)
 └ pages/ tabs/     projects, research, population, scenarios…      ├ llm/provider.py   FreeModel adapter (retry, limits, usage, cost)
                                                                    ├ agents/generator.py  description → segments → diverse agents
 static DEMO assets: public/demo/{run,graph,scenarios,report}.json  ├ sim/engine.py  opinion-dynamics engine (seeded, inspectable)
                                                                    ├ sim/writers.py LLM / template language layer + LLM deliberation
                                                                    ├ sim/runner.py  rounds, event sink, pause/stop, budgets
                                                                    ├ intel/extract.py  entities/relations/facts + provenance + contradictions
                                                                    ├ intel/analytics.py method selection, stats, Monte Carlo, Bayesian
                                                                    ├ scenarios.py   what-if → assumptions, paired replicates, sensitivity
                                                                    ├ decisions.py   ranked recommendations     reports.py  15-section report, MD/PDF/CSV
                                                                    └ engines/mirofish.py  OASIS actions.jsonl → normalised events
```

## The simulation, honestly
* **Structure is modelled, language is generated.** Who talks to whom, agree/disagree/share, tie changes, opinion shifts, communities and cascades come from a seeded
  *bounded-confidence opinion-dynamics model with backlash*, driven by each agent's traits, goals, memory, ties and the environment. Every event stores a human-readable `reason`.
* **Language** is written by the agent model in batched calls (the provider allows 60 req/min, so one call per agent is impossible) or by deterministic templates (DEMO / fallback).
  `content_source` is `llm` or `template` on every event.
* **LLM-decided agents:** each round up to *k* of the most influential active agents are decided directly by the LLM (action, stance, opinion shift ≤ ±0.25, message, reason). Those events carry `decided_by: "llm"`.
* **Emergent effects are computed, never drawn:** communities = label propagation over ties × opinion similarity; cascades = share chains; influence = PageRank over "who moved whose opinion";
  polarisation/consensus/modularity from opinions and ties. The canvas only animates recorded events; scrubbing reconstructs state purely from `state_changes`.
* **Budgets/cost:** per-run call/token budget (LLM falls back to labelled templates when exhausted), per-user daily LLM-job quota, client-side rate limiter, usage + estimated cost per task/model.

## Market layer (`sim/market.py`)
Optional layer on top of the opinion model (enabled by a `market` spec on a population; scenarios can override parts of it).
* **Funnel:** unaware → aware → considering → trial → repeat → advocate (or rejecter). Word of mouth spreads only from agents who are considering/using the brand.
* **Awareness:** Bass-style (external marketing + word of mouth). Default annual coefficients p=0.03, q=0.38 (commonly cited meta-analysis values, from a secondary source — verify) converted to per-round rates (`rounds_per_year`, default 52).
* **Purchase:** multinomial-logit brand choice among brands *available at the agent's store*: price × price-sensitivity, Guadagni–Little-style loyalty to the usual brand, quality × taste-fit, plus opinion/consideration for the focal brand. Unaware agents and rejecters cannot choose it.
* **Retailers** list when stance and shopper demand clear thresholds (or by an explicit negotiated `list_at` round) and delist after repeated low share; **competitors** run budget-limited promotions when the focal share crosses a trigger.
* Emits `funnel_change`, `listing_decision`, `competitor_action` events (each with a computed `reason`) and a `market` block in every `round_end` (funnel, awareness, shares, revenue index, listings). Monte Carlo/scenario results include these metrics with paired differences.
* All spec numbers are assumptions unless the caller supplies data; no market statistics are bundled.

## Normalised event (`sim/runner.py`)
`id, seq, simulation_id, round, type, source_agent, target_agent, agents[], topic, content, content_source, reason, result{}, state_changes{opinion, relationships, sentiment, group}, timestamp, provenance{engine, mode, seed}, cause_event?`
Types: `sim_start round_start external_event post reply agree disagree share cascade opinion_change relationship_change join_group leave_group round_end sim_pause sim_resume sim_end error`.

## Transport
Events are appended to SQLite per round, then pushed to subscribers. `GET /api/simulations/{id}/stream` (SSE) first replays persisted events after `Last-Event-ID`/`?after`,
then follows live. The client (fetch-based, so it can send `Authorization`) reconnects with the last `seq`, and `Playback.append` drops duplicates by id and enforces `seq` order.
Pause/resume/stop act on the server run; "Playback paused · simulation still computing" is shown when only the viewer is paused.

## Data
SQLite (WAL): `users, sessions, docs(kind,id,owner,project_id,json), events(simulation_id,seq,…), usage`. Chosen over Postgres/graph-DB/vector-DB to avoid unneeded infrastructure:
the knowledge graph is a few hundred nodes (stored as JSON), and no embeddings are used. Narrow `Store` interface = swappable later.

## Analytics engine
`select_methods()` picks methods from the question (and refuses a multi-agent simulation when data analysis suffices). Implemented: descriptive stats/correlation, linear trend with CI,
diagnostic segment/shock analysis, scenario analysis with **paired Monte Carlo** (same population+seed, only assumptions differ), one-at-a-time sensitivity, Beta-Binomial posterior over
replicate outcomes (reported only as model-conditional). *Financial* and *causal* methods are selected/explained but not separately implemented beyond the above.

## MiroFish
See `MIROFISH_ASSESSMENT.md`. `engines/mirofish.py` normalises `actions.jsonl` (tested on fixtures of the documented format, import endpoint included); it has **not** been run against a live MiroFish install.
