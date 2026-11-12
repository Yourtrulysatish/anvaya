"""ANVAYA REST + SSE API."""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from . import decisions, ingest, reports, scenarios as scen, security
from .agents import generator
from .config import TASKS, settings
from .db import get_store, new_id
from .engines import mirofish
from .intel import analytics, extract
from .llm.provider import ProviderError, provider
from .security import User, own_project, own_simulation
from .sim.engine import Agent, Shock, SimConfig
from .sim.runner import Budget, SimulationRun

RUNS: dict[str, SimulationRun] = {}
TASKS_BG: set = set()
LLM_QUOTA: dict = {}
MAX_LLM_JOBS_PER_DAY = int(__import__("os").environ.get("ANVAYA_MAX_LLM_JOBS_PER_DAY", "25"))
DEFAULT_MAX_CALLS = int(__import__("os").environ.get("ANVAYA_DEFAULT_RUN_MAX_CALLS", "150"))

router = APIRouter(prefix="/api")


def _llm():
    return provider if settings.llm_configured else None


def _quota(user: dict, cost: int = 1):
    k = (user["id"], date.today().isoformat())
    if LLM_QUOTA.get(k, 0) + cost > MAX_LLM_JOBS_PER_DAY:
        raise HTTPException(429, f"Daily LLM job quota ({MAX_LLM_JOBS_PER_DAY}) reached for this account")
    LLM_QUOTA[k] = LLM_QUOTA.get(k, 0) + cost


def _perr(e: ProviderError) -> HTTPException:
    code = {"auth": 502, "payment": 402, "rate_limit": 429, "model_unavailable": 424, "not_configured": 503}.get(e.kind, 502)
    return HTTPException(code, e.to_dict())


def _strip(d: dict, drop=("_owner", "_project", "_created", "_updated")) -> dict:
    return {k: v for k, v in d.items() if k not in drop}


def spawn(coro):
    t = asyncio.create_task(coro)
    TASKS_BG.add(t); t.add_done_callback(TASKS_BG.discard)
    return t


# ---------------------------------------------------------------------------------- jobs
def start_job(kind: str, project_id: str, owner: str, fn, **meta) -> dict:
    jid = new_id("job")
    store = get_store()
    job = {"kind": kind, "status": "running", "progress": 0.0, "message": "Starting…", "result": None, "error": None, **meta}
    store.put("job", jid, job, owner, project_id)

    def update(progress: float = None, message: str = None):
        j = store.get("job", jid)
        if progress is not None: j["progress"] = progress
        if message: j["message"] = message
        store.put("job", jid, _strip(j), owner, project_id)

    async def runner():
        try:
            res = await fn(update)
            j = _strip(store.get("job", jid)); j.update(status="done", progress=1.0, message="Done", result=res)
            store.put("job", jid, j, owner, project_id)
        except ProviderError as e:
            j = _strip(store.get("job", jid)); j.update(status="failed", error=e.to_dict(), message=str(e))
            store.put("job", jid, j, owner, project_id)
        except Exception as e:  # noqa
            j = _strip(store.get("job", jid)); j.update(status="failed", error={"kind": "internal", "message": f"{e.__class__.__name__}: {e}"}, message=str(e))
            store.put("job", jid, j, owner, project_id)
    spawn(runner())
    return {"id": jid, **job}


@router.get("/jobs/{jid}")
def get_job(jid: str, user=User):
    j = get_store().get("job", jid)
    if not j or j["_owner"] != user["id"]:
        raise HTTPException(404, "Job not found")
    return {"id": jid, **_strip(j)}


# ---------------------------------------------------------------------------------- health / auth
@router.get("/health")
async def health():
    out = {"status": "ok", "llm_configured": settings.llm_configured, "registration_open": settings.allow_registration, "version": "0.1.0",
           "engine": "anvaya-native", "mirofish_url_configured": bool(settings.mirofish_url)}
    return out


class Creds(BaseModel):
    email: str
    password: str


@router.post("/auth/register")
def auth_register(c: Creds):
    if not settings.allow_registration:
        raise HTTPException(403, "Registration is closed on this deployment")
    security.register(c.email, c.password)
    return security.login(c.email, c.password)


@router.post("/auth/login")
def auth_login(c: Creds):
    return security.login(c.email, c.password)


@router.post("/auth/logout")
def auth_logout(user=User):
    security.logout(user["token"]); return {"ok": True}


@router.get("/auth/me")
def auth_me(user=User):
    return {"id": user["id"], "email": user["email"], "is_admin": _is_admin(user)}


def _is_admin(user: dict) -> bool:
    import os
    adm = os.environ.get("ANVAYA_ADMIN_EMAIL", "").lower()
    if adm:
        return user["email"].lower() == adm
    rows = get_store().execute("SELECT id FROM users ORDER BY created LIMIT 1")
    return bool(rows) and rows[0]["id"] == user["id"]


# ---------------------------------------------------------------------------------- settings / models
@router.get("/settings")
async def get_settings(user=User):
    out: dict[str, Any] = {"llm_configured": settings.llm_configured, "provider": "FreeModel.in", "base_url": settings.freemodel_base_url,
                           "is_admin": _is_admin(user), "tasks": list(TASKS), "limits": {"max_agents": settings.max_agents, "max_rounds": settings.max_rounds,
                           "max_upload_mb": settings.max_upload_mb, "requests_per_minute": settings.requests_per_minute, "daily_llm_jobs": MAX_LLM_JOBS_PER_DAY},
                           "session_usage": provider.session_usage, "usage": get_store().usage_summary()}
    if settings.llm_configured:
        try:
            cat = await provider.list_models()
            out["models"] = [{"id": m["id"], "name": m.get("name"), "context_window": m.get("context_window"), "capabilities": m.get("capabilities"), "pricing": m.get("pricing"), "description": m.get("description")} for m in cat]
            out["assignments"] = {}
            for t in TASKS:
                try: out["assignments"][t] = {"model": await provider.resolve_model(t), "explicit": bool(provider.runtime_models.get(t) or settings.model_overrides.get(t))}
                except ProviderError as e: out["assignments"][t] = {"error": e.to_dict()}
            out["rate_limit_headers"] = provider.last_rate_headers
        except ProviderError as e:
            out["error"] = e.to_dict()
    return out


class ModelAssign(BaseModel):
    task: str
    model: str = ""


@router.put("/settings/models")
async def set_model(a: ModelAssign, user=User):
    if not _is_admin(user):
        raise HTTPException(403, "Only the deployment admin can change model assignments")
    if a.task not in TASKS:
        raise HTTPException(400, f"Unknown task. Choose from {list(TASKS)}")
    if a.model:
        chk = await _safe(provider.check_model(a.model))
        if not chk["available"]:
            raise HTTPException(424, chk)
        provider.runtime_models[a.task] = a.model
    else:
        provider.runtime_models.pop(a.task, None)
    return {"task": a.task, "model": await provider.resolve_model(a.task)}


@router.post("/settings/test")
async def test_connection(user=User):
    return await provider.test_connection(live_call=True)


@router.get("/settings/check-model")
async def check_model(id: str, user=User):
    return await _safe(provider.check_model(id))


async def _safe(coro):
    try:
        return await coro
    except ProviderError as e:
        raise _perr(e)


# ---------------------------------------------------------------------------------- projects
class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    situation: str = Field(default="", max_length=8000)
    objectives: str = Field(default="", max_length=4000)


@router.get("/projects")
def list_projects(user=User):
    st = get_store()
    out = []
    for p in st.list("project", owner=user["id"]):
        out.append({**_strip(p), "documents": len(st.list("document", project_id=p["id"])), "simulations": len(st.list("simulation", project_id=p["id"])),
                    "updated": p["_updated"], "created": p["_created"]})
    return out


@router.post("/projects")
def create_project(p: ProjectIn, user=User):
    pid = new_id("prj")
    get_store().put("project", pid, p.model_dump(), user["id"], pid)
    return {"id": pid, **p.model_dump()}


@router.get("/projects/{pid}")
def get_project(pid: str, user=User):
    p = own_project(pid, user)
    st = get_store()
    return {**_strip(p), "documents": [{k: v for k, v in _strip(d).items() if k not in ("text", "table")} | {"chars": len(d.get("text", ""))} for d in st.list("document", project_id=pid)],
            "populations": [{"id": x["id"], "n": x["n"], "basis": x["basis"], "title": x["spec"]["title"], "updated": x["_updated"]} for x in st.list("population", project_id=pid)],
            "simulations": [{k: v for k, v in _strip(s).items() if k not in ("analysis", "agents")} | {"updated": s["_updated"]} for s in st.list("simulation", project_id=pid)],
            "scenarios": [_strip(s) for s in st.list("scenario", project_id=pid)],
            "has_knowledge": st.get("knowledge", pid) is not None,
            "reports": [{"id": r["id"], "title": r["report"]["title"], "updated": r["_updated"]} for r in st.list("report", project_id=pid)]}


@router.put("/projects/{pid}")
def update_project(pid: str, p: ProjectIn, user=User):
    own_project(pid, user)
    get_store().put("project", pid, p.model_dump(), user["id"], pid)
    return {"id": pid, **p.model_dump()}


@router.delete("/projects/{pid}")
def delete_project(pid: str, user=User):
    own_project(pid, user)
    for sid, run in list(RUNS.items()):
        s = get_store().get("simulation", sid)
        if s and s["_project"] == pid:
            run.stop()
    get_store().delete_project(pid)
    return {"ok": True}


# ---------------------------------------------------------------------------------- documents
def _store_doc(pid: str, user: dict, name: str, ex: dict, url: str = None) -> dict:
    did = new_id("doc")
    body = {"name": name, "kind": ex["kind"], "text": ex["text"], "meta": ex.get("meta", {}), "table": ex.get("table"), "url": url}
    get_store().put("document", did, body, user["id"], pid)
    return {"id": did, "name": name, "kind": ex["kind"], "chars": len(ex["text"]), "tabular": bool(ex.get("table")), "url": url}


@router.post("/projects/{pid}/documents")
async def upload_document(pid: str, request: Request, file: UploadFile = File(...), user=User):
    own_project(pid, user)
    cl = request.headers.get("content-length")
    if cl and int(cl) > (settings.max_upload_mb + 1) * 1024 * 1024:
        raise HTTPException(413, f"Upload exceeds {settings.max_upload_mb} MB")
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    name = ingest.safe_filename(file.filename or "upload")
    try:
        ext = ingest.validate_upload(name, data)
        ex = await asyncio.to_thread(ingest.extract_text, ext, data)
    except ingest.IngestError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # corrupt files
        raise HTTPException(400, f"Could not read {name}: {e.__class__.__name__}")
    if not ex["text"].strip():
        raise HTTPException(400, "No extractable text found in this file")
    return _store_doc(pid, user, name, ex)


class UrlIn(BaseModel):
    url: str = Field(max_length=2000)


@router.post("/projects/{pid}/documents/url")
async def add_url(pid: str, u: UrlIn, user=User):
    own_project(pid, user)
    try:
        ex = await ingest.fetch_url(u.url)
    except ingest.IngestError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Could not fetch URL: {e.__class__.__name__}")
    return _store_doc(pid, user, ex.get("title") or u.url, ex, url=u.url)


class TextIn(BaseModel):
    name: str = Field(default="Pasted text", max_length=120)
    text: str = Field(min_length=1, max_length=200_000)


@router.post("/projects/{pid}/documents/text")
def add_text(pid: str, t: TextIn, user=User):
    own_project(pid, user)
    return _store_doc(pid, user, t.name, {"text": t.text, "kind": "txt", "meta": {}})


@router.delete("/projects/{pid}/documents/{did}")
def delete_document(pid: str, did: str, user=User):
    own_project(pid, user)
    d = get_store().get("document", did)
    if not d or d["_project"] != pid:
        raise HTTPException(404, "Document not found")
    get_store().delete("document", did)
    return {"ok": True}


# ---------------------------------------------------------------------------------- research / knowledge graph
class MethodIn(BaseModel):
    question: str = Field(max_length=4000)


@router.post("/projects/{pid}/methodology")
def methodology(pid: str, m: MethodIn, user=User):
    own_project(pid, user)
    docs = get_store().list("document", project_id=pid)
    return analytics.select_methods(m.question, any(d.get("table") for d in docs), bool(docs))


class AnalyseIn(BaseModel):
    use_llm: bool = True


@router.post("/projects/{pid}/analyse")
async def analyse_project(pid: str, a: AnalyseIn, user=User):
    p = own_project(pid, user)
    docs = [{"id": d["id"], **_strip(d)} for d in get_store().list("document", project_id=pid)]
    if not docs:
        raise HTTPException(400, "Add at least one document, URL or pasted text first")
    use_llm = a.use_llm and settings.llm_configured
    if use_llm: _quota(user)

    async def job(update):
        update(0.1, "Extracting entities, relations and facts…")
        kb = await extract.build_knowledge(_llm(), docs, pid, use_llm)
        tables = {}
        for d in docs:
            if d.get("table"):
                tables[d["name"]] = await asyncio.to_thread(analytics.describe_table, d["table"])
        kb["dataset_analysis"] = tables
        get_store().put("knowledge", pid, kb, user["id"], pid)
        return {"entities": len(kb["nodes"]), "relations": len(kb["edges"]), "facts": len(kb["facts"]), "method": kb["method"]}
    return start_job("analyse", pid, user["id"], job)


@router.get("/projects/{pid}/graph")
def get_graph(pid: str, user=User):
    own_project(pid, user)
    kb = get_store().get("knowledge", pid)
    if not kb:
        raise HTTPException(404, "No knowledge graph yet. Run the analysis first.")
    return _strip(kb)


# ---------------------------------------------------------------------------------- population
class PopIn(BaseModel):
    description: str = Field(min_length=3, max_length=4000)
    n: int = Field(default=120, ge=5, le=2000)
    use_llm: bool = True
    enrich: bool = True
    seed: int = 1


def _pop_summary(pop: dict) -> dict:
    return {"id": pop["id"], "n": pop["n"], "basis": pop["basis"], "title": pop["spec"]["title"]}


@router.post("/projects/{pid}/populations/generate")
async def generate_population(pid: str, p: PopIn, user=User):
    own_project(pid, user)
    n = min(p.n, settings.max_agents)
    use_llm = p.use_llm and settings.llm_configured
    if use_llm: _quota(user)
    kb = get_store().get("knowledge", pid)
    ctx = ""
    if kb:
        ctx = "\n".join(f"- {f['text']} [{f['temporal']}; {f['source_ref']['doc']}]" for f in kb["facts"][:25])

    async def job(update):
        warnings: list[str] = []
        spec = None
        if use_llm:
            update(0.1, "Interpreting the population…")
            try:
                spec = await generator.interpret(p.description, provider, n, ctx, pid)
            except Exception as e:  # noqa
                warnings.append(f"LLM interpretation failed ({getattr(e, 'kind', e.__class__.__name__)}: {str(e)[:120]}); generic heuristic population used.")
        if spec is None:
            spec = generator.interpret_offline(p.description)
            if not use_llm: warnings.append("No LLM configured: generic heuristic population (labelled 'heuristic').")
        update(0.4, "Sampling diverse agents…")
        agents = generator.sample(spec, n, p.seed)
        enriched = 0
        if use_llm and p.enrich and spec.basis == "llm":
            update(0.5, "Writing individual personas…")
            enriched = await generator.enrich_personas(agents, spec, provider, pid)
            if enriched < len(agents): warnings.append(f"{len(agents) - enriched} agents kept template personas (LLM batch missed them).")
        pop_id = new_id("pop")
        counts: dict = {}
        for a in agents: counts[a.segment] = counts.get(a.segment, 0) + 1
        pop = {"spec": spec.to_dict(), "agents": [asdict(a) for a in agents], "n": len(agents), "basis": spec.basis, "enriched": enriched,
               "segments": [{"name": s.name, "share": s.share, "count": counts.get(s.name, 0), "description": s.description} for s in spec.segments],
               "assumptions": spec.assumptions + (["Attributes were also informed by supplied documents."] if ctx else []), "warnings": warnings, "description": p.description}
        get_store().put("population", pop_id, pop, user["id"], pid)
        return {"population_id": pop_id, "n": len(agents), "basis": spec.basis, "warnings": warnings}
    return start_job("population", pid, user["id"], job)


def _get_pop(pid: str, pop_id: str) -> dict:
    pop = get_store().get("population", pop_id)
    if not pop or pop["_project"] != pid:
        raise HTTPException(404, "Population not found")
    return pop


@router.get("/projects/{pid}/populations/{pop_id}")
def get_population(pid: str, pop_id: str, user=User):
    own_project(pid, user)
    return _strip(_get_pop(pid, pop_id))


class AgentEdit(BaseModel):
    id: int
    name: str = Field(max_length=80)
    persona: str = Field(default="", max_length=700)
    goals: list[str] = Field(default_factory=list, max_length=6)
    beliefs: list[str] = Field(default_factory=list, max_length=6)
    activity: float = Field(ge=0.02, le=0.95)
    influence: float = Field(ge=0, le=1)
    opinions: dict[str, float] = Field(default_factory=dict)
    traits: dict[str, float] = Field(default_factory=dict)


class PopUpdate(BaseModel):
    agents: list[AgentEdit]
    remove: list[int] = Field(default_factory=list)


@router.put("/projects/{pid}/populations/{pop_id}")
def edit_population(pid: str, pop_id: str, u: PopUpdate, user=User):
    own_project(pid, user)
    pop = _get_pop(pid, pop_id)
    by = {a["id"]: a for a in pop["agents"]}
    for e in u.agents:
        a = by.get(e.id)
        if not a: continue
        a.update(name=e.name.strip() or a["name"], persona=e.persona, goals=[g[:140] for g in e.goals], beliefs=[b[:160] for b in e.beliefs],
                 activity=e.activity, influence=e.influence, attributes_basis="user")
        a["opinions"] = {k: max(-1, min(1, v)) for k, v in e.opinions.items() if k in a["opinions"]} or a["opinions"]
        a["initial_opinions"] = dict(a["opinions"])
        a["traits"] = {k: max(0, min(1, v)) for k, v in e.traits.items() if k in a["traits"]} or a["traits"]
    keep = [a for a in pop["agents"] if a["id"] not in set(u.remove)]
    if len(keep) < 5:
        raise HTTPException(400, "A population needs at least 5 agents")
    for i, a in enumerate(keep): a["id"] = i
    pop["agents"], pop["n"] = keep, len(keep)
    counts: dict = {}
    for a in keep: counts[a["segment"]] = counts.get(a["segment"], 0) + 1
    for s in pop["segments"]: s["count"] = counts.get(s["name"], 0)
    pop["edited_by_user"] = True
    get_store().put("population", pop_id, _strip(pop), user["id"], pid)
    return _pop_summary({**pop, "id": pop_id})


# ---------------------------------------------------------------------------------- simulations
class SimIn(BaseModel):
    population_id: str
    name: str = Field(default="Simulation", max_length=120)
    rounds: int = Field(default=20, ge=2, le=200)
    seed: int = 7
    use_llm: bool = False
    llm_agents_per_round: int = Field(default=0, ge=0, le=12)
    budget_calls: int = Field(default=0, ge=0, le=2000)
    budget_tokens: int = Field(default=0, ge=0, le=5_000_000)
    scenario_id: Optional[str] = None
    round_delay: float = Field(default=0.0, ge=0, le=5)


async def _launch(pid: str, user: dict, s: SimIn, shocks: list[dict] = None, scenario_id: str = None) -> dict:
    pop = _get_pop(pid, s.population_id)
    rounds = min(s.rounds, settings.max_rounds)
    running = [r for r in RUNS.values() if r.status in ("running", "paused") and (get_store().get("simulation", r.cfg.simulation_id) or {}).get("_owner") == user["id"]]
    if len(running) >= 2:
        raise HTTPException(429, "Two simulations are already running for this account; stop one first")
    use_llm = s.use_llm and settings.llm_configured
    if use_llm: _quota(user, 2)
    sid = new_id("sim")
    agents = scen.agents_from_pop(pop)
    cfg = SimConfig(sid, seed=s.seed, rounds=rounds, topics=scen.topics_from_pop(pop), shocks=[scen.shock_from_dict(x) for x in (shocks or [])],
                    llm_agents_per_round=s.llm_agents_per_round if use_llm else 0, mode="native", title=s.name, description=pop.get("description", ""))
    budget = Budget(s.budget_calls or (DEFAULT_MAX_CALLS if use_llm else 0), s.budget_tokens, provider if use_llm else None)
    run = SimulationRun(agents, cfg, store=get_store(), provider=provider if use_llm else None, use_llm=use_llm, project_id=pid, budget=budget, round_delay=s.round_delay)
    doc = {"name": s.name, "population_id": s.population_id, "status": "created", "config": {"rounds": rounds, "seed": s.seed, "use_llm": use_llm, "llm_agents_per_round": cfg.llm_agents_per_round,
           "budget_calls": budget.max_calls, "budget_tokens": budget.max_tokens, "shocks": shocks or []}, "agents": [a.public() for a in agents],
           "topic": pop["spec"]["topics"][0]["id"], "scenario_id": scenario_id, "mode": "native", "synthetic": False, "label": "LIVE" if use_llm else "SIMULATED (no LLM text)"}
    st = get_store(); st.put("simulation", sid, doc, user["id"], pid)
    RUNS[sid] = run

    async def go():
        await run.run()
        d = _strip(st.get("simulation", sid)); d["status"] = run.status; d["error"] = run.error
        d["analysis"] = analytics.analyse_events(run.events, d["agents"], d["topic"]) if run.status in ("completed", "stopped") else None
        st.put("simulation", sid, d, user["id"], pid)
    spawn(go())
    doc["status"] = "running"; st.put("simulation", sid, doc, user["id"], pid)
    return {"id": sid, "status": "running", "agents": len(agents), "rounds": rounds, "use_llm": use_llm}


@router.post("/projects/{pid}/simulations")
async def start_simulation(pid: str, s: SimIn, user=User):
    own_project(pid, user)
    shocks = None
    if s.scenario_id:
        sc = get_store().get("scenario", s.scenario_id)
        if not sc or sc["_project"] != pid: raise HTTPException(404, "Scenario not found")
        shocks = sc.get("shocks", [])
    return await _launch(pid, user, s, shocks, s.scenario_id)


def _sim_view(s: dict, with_agents: bool = True) -> dict:
    run = RUNS.get(s["id"])
    out = {k: v for k, v in _strip(s).items() if k not in ("analysis",) and (with_agents or k != "agents")}
    if run:
        out["status"], out["round"] = run.status, run.current_round
    out["events"] = get_store().count_events(s["id"])
    out["project_id"] = s["_project"]
    return out


@router.get("/simulations/{sid}")
def get_simulation(sid: str, user=User):
    return _sim_view(own_simulation(sid, user))


@router.get("/simulations/{sid}/events")
def get_events(sid: str, after: int = -1, limit: int = Query(5000, le=20000), user=User):
    own_simulation(sid, user)
    return {"events": get_store().read_events(sid, after, limit)}


@router.get("/simulations/{sid}/analysis")
def sim_analysis(sid: str, user=User):
    s = own_simulation(sid, user)
    if s.get("analysis"):
        return s["analysis"]
    evs = get_store().read_events(sid)
    if not evs: raise HTTPException(404, "No events recorded")
    return analytics.analyse_events(evs, s["agents"], s["topic"])


def _sse(name: str, data: Any, id_: Optional[int] = None) -> str:
    return (f"id: {id_}\n" if id_ is not None else "") + f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


@router.get("/simulations/{sid}/stream")
async def stream(sid: str, request: Request, after: int = -1, user=User):
    own_simulation(sid, user)
    try:
        last = max(after, int(request.headers.get("last-event-id", after)))
    except ValueError:
        last = after
    run = RUNS.get(sid)
    st = get_store()

    async def gen():
        nonlocal last
        q = run.subscribe() if run and run.status in ("created", "running", "paused") else None
        try:
            yield _sse("status", {"status": run.status if run else (st.get("simulation", sid) or {}).get("status")})
            while True:
                evs = st.read_events(sid, last, 400)
                if not evs: break
                last = evs[-1]["seq"]
                yield _sse("events", evs, last)
            if q is None:
                yield _sse("end", {"status": (st.get("simulation", sid) or {}).get("status")}); return
            while True:
                if await request.is_disconnected(): return
                try:
                    batch = await asyncio.wait_for(q.get(), 12)
                except asyncio.TimeoutError:
                    yield _sse("status", {"status": run.status, "round": run.current_round}); continue
                if batch is None:
                    yield _sse("end", {"status": run.status}); return
                fresh = [e for e in batch if e["seq"] > last]
                if fresh:
                    last = fresh[-1]["seq"]; yield _sse("events", fresh, last)
        finally:
            if q is not None and run: run.unsubscribe(q)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _run_for(sid: str, user: dict) -> SimulationRun:
    own_simulation(sid, user)
    run = RUNS.get(sid)
    if not run or run.status not in ("running", "paused"):
        raise HTTPException(409, "Simulation is not running")
    return run


@router.post("/simulations/{sid}/pause")
def pause(sid: str, user=User):
    r = _run_for(sid, user); r.pause(); return {"status": r.status}


@router.post("/simulations/{sid}/resume")
def resume(sid: str, user=User):
    r = _run_for(sid, user); r.resume(); return {"status": r.status}


@router.post("/simulations/{sid}/stop")
def stop(sid: str, user=User):
    r = _run_for(sid, user); r.stop(); return {"status": "stopping"}


class InterviewIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@router.post("/simulations/{sid}/agents/{aid}/interview")
async def interview(sid: str, aid: int, q: InterviewIn, user=User):
    s = own_simulation(sid, user)
    if not settings.llm_configured:
        raise HTTPException(503, "Interviews need the language model (FREEMODEL_API_KEY not configured)")
    if aid < 0 or aid >= len(s["agents"]):
        raise HTTPException(404, "Agent not found")
    _quota(user, 1)
    a = s["agents"][aid]
    evs = [e for e in get_store().read_events(sid) if aid in (e.get("agents") or []) or e.get("source_agent") == aid or e.get("target_agent") == aid]
    heard = [f"{s['agents'][e['source_agent']]['name']}: {e['content']}" for e in evs if e.get("source_agent") not in (None, aid) and e.get("content") and e["type"] in ("post", "reply", "agree", "disagree", "share")][-8:]
    said = [e["content"] for e in evs if e.get("source_agent") == aid and e.get("content") and e["type"] in ("post", "reply", "agree", "disagree", "share")][-6:]
    last_op = None
    for e in evs:
        c = (e.get("state_changes") or {}).get("opinion", {}).get(str(aid))
        if c: last_op = c["to"]
    sys = (f"You are role-playing {a['name']}, a FICTIONAL simulated agent in a social simulation (not a real person). Persona: {a['persona']} Goals: {a['goals']}. Beliefs: {a['beliefs']}. "
           f"Current opinion on the topic ({-1}=against, +1=in favour): {last_op if last_op is not None else a['opinions']}. Things this agent said: {said}. Things this agent heard: {heard}. "
           "Answer the interviewer in character in 2-5 sentences, grounded ONLY in the above. If asked about something outside this, say you haven't thought about it. Never claim to be a real person.")
    try:
        res = await provider.chat("agent", [{"role": "system", "content": sys}, {"role": "user", "content": q.question}], temperature=0.7, max_tokens=1500, project_id=s["_project"])
    except ProviderError as e:
        raise _perr(e)
    return {"answer": res.content.strip(), "model": res.model, "simulated": True}


# ---------------------------------------------------------------------------------- scenarios
class ScenarioIn(BaseModel):
    population_id: str
    name: str = Field(max_length=80)
    kind: str = "alternative"
    prompt: str = Field(default="", max_length=600)
    rounds: int = Field(default=20, ge=2, le=100)


@router.post("/projects/{pid}/scenarios/propose")
async def propose(pid: str, body: dict, user=User):
    p = own_project(pid, user)
    pop = _get_pop(pid, body.get("population_id", ""))
    if settings.llm_configured: _quota(user)
    return {"scenarios": await scen.propose_scenarios(_llm(), p.get("situation", "") or pop.get("description", ""), pop, int(body.get("rounds", 20)), pid)}


@router.post("/projects/{pid}/scenarios")
async def create_scenario(pid: str, s: ScenarioIn, user=User):
    own_project(pid, user)
    pop = _get_pop(pid, s.population_id)
    shocks, assumptions, method, rationale = [], [], "none", ""
    if s.prompt.strip() and s.kind != "baseline":
        if settings.llm_configured: _quota(user)
        r = await scen.interpret_shock(_llm(), s.prompt, pop, s.rounds, pid)
        shocks, assumptions, method, rationale = r["shocks"], r["assumptions"], r["method"], r.get("rationale", "")
        if not shocks:
            raise HTTPException(422, "Could not turn this into a concrete assumption; try rephrasing")
    sid = new_id("scn")
    doc = {"name": s.name, "kind": s.kind, "prompt": s.prompt, "population_id": s.population_id, "rounds": s.rounds, "shocks": shocks, "assumptions": assumptions,
           "interpretation": method, "rationale": rationale, "results": None, "status": "draft"}
    get_store().put("scenario", sid, doc, user["id"], pid)
    return {"id": sid, **doc}


class ScenarioEdit(BaseModel):
    shocks: list[dict]


@router.put("/scenarios/{sid}")
def edit_scenario(sid: str, e: ScenarioEdit, user=User):
    sc = get_store().get("scenario", sid)
    if not sc: raise HTTPException(404, "Scenario not found")
    own_project(sc["_project"], user)
    pop = _get_pop(sc["_project"], sc["population_id"])
    sc["shocks"] = scen.validate_shocks(e.shocks, pop, sc["rounds"])
    sc["results"], sc["status"] = None, "draft"
    get_store().put("scenario", sid, _strip(sc), user["id"], sc["_project"])
    return {"id": sid, **_strip(sc)}


class RunScenario(BaseModel):
    replicates: int = Field(default=8, ge=2, le=30)
    sensitivity: bool = True
    visible_run: bool = True


@router.post("/scenarios/{sid}/run")
async def run_scenario(sid: str, r: RunScenario, user=User):
    sc = get_store().get("scenario", sid)
    if not sc: raise HTTPException(404, "Scenario not found")
    pid = sc["_project"]; own_project(pid, user)
    pop = _get_pop(pid, sc["population_id"])
    seeds = list(range(101, 101 + r.replicates))

    async def job(update):
        st = get_store()
        update(0.1, "Running baseline replicates…")
        base_runs = await scen.monte_carlo(pop, [], sc["rounds"], seeds)
        update(0.4, "Running scenario replicates…")
        runs = base_runs if not sc["shocks"] else await scen.monte_carlo(pop, sc["shocks"], sc["rounds"], seeds)
        res = {"summary": scen.summarise_runs(runs), "baseline_summary": scen.summarise_runs(base_runs), "replicates": r.replicates,
               "comparison": scen.compare(base_runs, runs) if sc["shocks"] else None, "monte_carlo_runs": [{k: v for k, v in x.items() if k != "segments"} for x in runs]}
        if r.sensitivity and sc["shocks"]:
            update(0.7, "Sensitivity analysis…")
            res["sensitivity"] = await scen.sensitivity(pop, sc["shocks"], sc["rounds"], seeds[:6])
        if r.visible_run:
            update(0.9, "Recording a replayable run…")
            out = await _launch(pid, user, SimIn(population_id=sc["population_id"], name=f"Scenario: {sc['name']}", rounds=sc["rounds"], seed=seeds[0], use_llm=False), sc["shocks"], sid)
            res["simulation_id"] = out["id"]
        d = _strip(st.get("scenario", sid)); d["results"], d["status"] = res, "complete"
        st.put("scenario", sid, d, user["id"], pid)
        return {"scenario_id": sid}
    return start_job("scenario", pid, user["id"], job)


@router.get("/projects/{pid}/scenarios")
def list_scenarios(pid: str, user=User):
    own_project(pid, user)
    return [{"id": s["id"], **_strip(s)} for s in get_store().list("scenario", project_id=pid)]


@router.delete("/scenarios/{sid}")
def delete_scenario(sid: str, user=User):
    sc = get_store().get("scenario", sid)
    if not sc: raise HTTPException(404, "Scenario not found")
    own_project(sc["_project"], user); get_store().delete("scenario", sid); return {"ok": True}


# ---------------------------------------------------------------------------------- recommendations & reports
class RecIn(BaseModel):
    simulation_id: str
    scenario_ids: list[str] = Field(default_factory=list)


def _scenario_context(pid: str, ids: list[str]) -> list[dict]:
    out = []
    for i in ids:
        sc = get_store().get("scenario", i)
        if sc and sc["_project"] == pid and sc.get("results"):
            out.append({"id": i, "name": sc["name"], "kind": sc["kind"], "prompt": sc["prompt"], "assumptions": sc.get("assumptions", []), 
                        "comparison": sc["results"].get("comparison"), "sensitivity": sc["results"].get("sensitivity")})
    return out


@router.post("/projects/{pid}/recommendations")
async def make_recommendations(pid: str, r: RecIn, user=User):
    p = own_project(pid, user)
    s = own_simulation(r.simulation_id, user)
    if s["_project"] != pid: raise HTTPException(404, "Simulation not found")
    evs = get_store().read_events(r.simulation_id)
    analysis = s.get("analysis") or analytics.analyse_events(evs, s["agents"], s["topic"])
    kb = get_store().get("knowledge", pid)
    if settings.llm_configured: _quota(user)
    ctx = {"situation": p.get("situation"), "objectives": p.get("objectives"), "analysis": analysis, "scenarios": _scenario_context(pid, r.scenario_ids),
           "knowledge_facts": (kb or {}).get("facts", [])}
    try:
        res = await decisions.recommend(_llm(), ctx, pid)
    except ProviderError as e:
        raise _perr(e)
    rid = new_id("rec")
    doc = {**res, "simulation_id": r.simulation_id, "scenario_ids": r.scenario_ids}
    get_store().put("recommendation", rid, doc, user["id"], pid)
    return {"id": rid, **doc}


@router.get("/projects/{pid}/recommendations")
def list_recs(pid: str, user=User):
    own_project(pid, user)
    return [{"id": x["id"], **_strip(x)} for x in get_store().list("recommendation", project_id=pid)]


class ReportIn(BaseModel):
    simulation_id: str
    scenario_ids: list[str] = Field(default_factory=list)
    recommendation_id: Optional[str] = None
    monte_carlo_replicates: int = Field(default=10, ge=0, le=30)


@router.post("/projects/{pid}/reports")
async def make_report(pid: str, r: ReportIn, user=User):
    p = own_project(pid, user)
    s = own_simulation(r.simulation_id, user)
    st = get_store()
    pop = st.get("population", s["population_id"]) if s.get("population_id") else None
    evs = st.read_events(r.simulation_id)
    analysis = s.get("analysis") or analytics.analyse_events(evs, s["agents"], s["topic"])
    kb = st.get("knowledge", pid)
    docs = [{"id": d["id"], **_strip(d)} for d in st.list("document", project_id=pid)]
    rec = st.get("recommendation", r.recommendation_id) if r.recommendation_id else (st.list("recommendation", project_id=pid) or [None])[0]
    mc = None
    if pop and r.monte_carlo_replicates >= 3 and s.get("mode") == "native":
        shocks = s["config"].get("shocks", [])
        runs = await scen.monte_carlo(pop, shocks, s["config"]["rounds"], list(range(201, 201 + r.monte_carlo_replicates)))
        mc = scen.summarise_runs(runs)
    methodology = analytics.select_methods((p.get("situation", "") + " " + p.get("objectives", "")).strip() or "how will people react", any(d.get("table") for d in docs), bool(docs))
    if settings.llm_configured: _quota(user)
    segs = [{"name": x["name"], "share": x["count"] / max(1, pop["n"]) if pop else 0} for x in (pop["segments"] if pop else [])]
    ctx = {"project": _strip(p), "documents": docs, "knowledge": kb, "analysis": analysis, "methodology": methodology, "monte_carlo": mc, "recommendations": (rec or {}).get("recommendations", []),
           "population": {"n": len(s["agents"]), "segments": segs, "assumptions": (pop or {}).get("assumptions", []), "basis": (pop or {}).get("basis", s.get("mode"))},
           "scenarios": [{"name": x["name"], "kind": x["kind"], "prompt": x["prompt"], "assumptions": x["assumptions"], "comparison": x["comparison"]}
                         for x in _scenario_context(pid, r.scenario_ids)],
           "usage": st.usage_summary(pid), "engine": "anvaya-native" if s.get("mode") == "native" else s.get("mode"), "mode": s.get("label"), "llm_text": s["config"].get("use_llm"),
           "assumptions": (pop or {}).get("assumptions", [])}
    analysis["final"]["rounds"] = s["config"]["rounds"]
    try:
        rep = await reports.build_report(_llm(), ctx, pid)
    except ProviderError as e:
        raise _perr(e)
    rid = new_id("rpt")
    st.put("report", rid, {"report": rep, "simulation_id": r.simulation_id}, user["id"], pid)
    return {"id": rid, "report": rep}


@router.get("/reports/{rid}")
def get_report(rid: str, user=User):
    r = get_store().get("report", rid)
    if not r: raise HTTPException(404, "Report not found")
    own_project(r["_project"], user)
    return {"id": rid, "report": r["report"], "simulation_id": r["simulation_id"]}


@router.get("/reports/{rid}/export")
def export_report(rid: str, format: str = "md", part: str = "events", user=User):
    r = get_store().get("report", rid)
    if not r: raise HTTPException(404, "Report not found")
    own_project(r["_project"], user)
    rep = r["report"]
    if format == "md":
        return Response(reports.to_markdown(rep), media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="anvaya-report-{rid}.md"'})
    if format == "pdf":
        return Response(reports.to_pdf(rep), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="anvaya-report-{rid}.pdf"'})
    if format == "csv":
        s = get_store().get("simulation", r["simulation_id"])
        evs = get_store().read_events(r["simulation_id"])
        if part == "events": body = reports.events_csv(evs, s["agents"])
        elif part == "metrics": body = reports.metrics_csv((s.get("analysis") or analytics.analyse_events(evs, s["agents"], s["topic"]))["trajectory"])
        elif part == "agents":
            end = next((e for e in reversed(evs) if e["type"] == "sim_end"), {"result": {}})
            body = reports.agents_csv(s["agents"], end["result"].get("final_opinions", {}), s["topic"])
        else: raise HTTPException(400, "part must be events, metrics or agents")
        return Response(body, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="anvaya-{part}-{rid}.csv"'})
    raise HTTPException(400, "format must be md, pdf or csv")


# ---------------------------------------------------------------------------------- MiroFish import
@router.post("/projects/{pid}/import/mirofish")
async def import_mirofish(pid: str, file: UploadFile = File(...), platform: str = Form("unknown"), user=User):
    own_project(pid, user)
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "File too large")
    parsed = mirofish.normalise(data.decode("utf-8", errors="replace").splitlines(), "tmp", platform[:20])
    if not parsed["events"]:
        raise HTTPException(400, "No usable MiroFish actions found in this file")
    sid = new_id("sim")
    parsed = mirofish.normalise(data.decode("utf-8", errors="replace").splitlines(), sid, platform[:20])
    agents, events = mirofish.to_dataset(parsed, sid, file.filename or "mirofish")
    st = get_store()
    doc = {"name": f"MiroFish import · {platform}", "status": "completed", "config": {"rounds": parsed["rounds"], "use_llm": True, "shocks": []}, "agents": agents, "topic": "t1",
           "mode": "mirofish", "synthetic": False, "label": "IMPORTED · MIROFISH", "skipped": parsed["skipped"], "population_id": None,
           "note": "Imported from a MiroFish actions.jsonl. Opinions are not present in MiroFish logs, so agents start neutral and opinion metrics are unavailable."}
    st.put("simulation", sid, doc, user["id"], pid)
    st.append_events(sid, events)
    return {"id": sid, "events": len(events), "agents": len(agents), "skipped": parsed["skipped"]}


# ---------------------------------------------------------------------------------- app factory
def create_app() -> FastAPI:
    settings.ensure_dirs()

    @asynccontextmanager
    async def lifespan(app):
        st = get_store()
        for s in st.list("simulation", limit=2000):
            if s.get("status") in ("running", "created", "paused"):
                d = _strip(s); d["status"], d["error"] = "failed", "Server restarted while the simulation was running"
                st.put("simulation", s["id"], d, s["_owner"], s["_project"])
        for j in st.list("job", limit=2000):
            if j.get("status") == "running":
                d = _strip(j); d["status"], d["error"] = "failed", {"kind": "restart", "message": "Server restarted"}
                st.put("job", j["id"], d, j["_owner"], j["_project"])
        yield
    app = FastAPI(title="ANVAYA API", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(security.RateLimitMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                       allow_headers=["Authorization", "Content-Type", "Last-Event-ID"], expose_headers=["Content-Disposition"])
    app.include_router(router)
    return app
