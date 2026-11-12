"""Scenario engine: interpret what-if assumptions, run paired Monte Carlo replicates, compare against a baseline."""
from __future__ import annotations

import asyncio
import copy
import json
import re
from collections import defaultdict
from dataclasses import asdict
from typing import Optional

from .intel import analytics
from .sim.engine import Agent, Shock, SimConfig, Topic
from .sim.runner import SimulationRun


def agents_from_pop(pop: dict) -> list[Agent]:
    out = []
    for d in pop["agents"]:
        d = {k: v for k, v in d.items() if k in Agent.__dataclass_fields__}
        out.append(Agent(**copy.deepcopy(d)))
    return out


def topics_from_pop(pop: dict) -> list[Topic]:
    return [Topic(**t) for t in pop["spec"]["topics"]]


def shock_from_dict(d: dict) -> Shock:
    return Shock(**{k: v for k, v in d.items() if k in Shock.__dataclass_fields__})


def _run_sync(pop: dict, shocks: list[dict], rounds: int, seed: int) -> dict:
    agents = agents_from_pop(pop)
    cfg = SimConfig(f"mc-{seed}", seed=seed, rounds=rounds, topics=topics_from_pop(pop), shocks=[shock_from_dict(s) for s in shocks], mode="native")
    run = SimulationRun(agents, cfg)
    asyncio.run(run.run())
    end = run.events[-1]["result"]
    topic = end["topic"]
    seg: dict = defaultdict(list)
    by_id = {a.id: a for a in agents}
    for aid, op in end["final_opinions"].items():
        seg[by_id[int(aid)].segment].append(op)
    n = len(agents)
    return {"seed": seed, "mean_opinion": end["mean_opinion"], "polarisation": end["polarisation"], "support_share": end["support"] / n,
            "oppose_share": end["oppose"] / n, "groups": end["groups"], "max_cascade": end["max_cascade"], "interactions": end["interactions_total"],
            "modularity": end["modularity"], "segments": {k: sum(v) / len(v) for k, v in seg.items()}, "topic": topic}


async def monte_carlo(pop: dict, shocks: list[dict], rounds: int, seeds: list[int]) -> list[dict]:
    return list(await asyncio.gather(*[asyncio.to_thread(_run_sync, pop, shocks, rounds, s) for s in seeds]))


def summarise_runs(runs: list[dict]) -> dict:
    keys = ["mean_opinion", "polarisation", "support_share", "oppose_share", "groups", "max_cascade", "interactions", "modularity"]
    out = {k: analytics.summarise([r[k] for r in runs]) for k in keys}
    segs = defaultdict(list)
    for r in runs:
        for s, v in r["segments"].items():
            segs[s].append(v)
    out["segments"] = {s: analytics.summarise(v) for s, v in segs.items()}
    out["support_majority"] = analytics.beta_posterior(sum(1 for r in runs if r["support_share"] > r["oppose_share"]), len(runs))
    return out


def compare(base_runs: list[dict], var_runs: list[dict]) -> dict:
    n = min(len(base_runs), len(var_runs))
    b, v = base_runs[:n], var_runs[:n]
    keys = ["mean_opinion", "polarisation", "support_share", "oppose_share", "groups", "max_cascade", "interactions"]
    diffs = {k: analytics.paired_difference([r[k] for r in b], [r[k] for r in v]) for k in keys}
    seg = {}
    for s in b[0]["segments"]:
        seg[s] = analytics.paired_difference([r["segments"][s] for r in b], [r["segments"][s] for r in v if s in r["segments"]])
    return {"differences": diffs, "segment_differences": seg, "pairs": n,
            "method": "Paired Monte Carlo replicates: same population and seed, only the stated assumptions differ. Intervals are ±1.96 SE of the paired difference.",
            "uncertainty": ("These are conditional on the model and on unverified assumptions about agents and effects. They show direction and rough size "
                            "of change within the simulated society, not probabilities about the real world.")}


async def sensitivity(pop: dict, shocks: list[dict], rounds: int, seeds: list[int], scales=(0.0, 0.5, 1.0, 1.5, 2.0)) -> list[dict]:
    out = []
    for sc in scales:
        sh = copy.deepcopy(shocks)
        for s in sh:
            for e in s["effects"]:
                e["delta"] = e["delta"] * sc
        runs = await monte_carlo(pop, sh, rounds, seeds)
        sm = analytics.summarise([r["mean_opinion"] for r in runs])
        out.append({"scale": sc, "mean_opinion": sm["mean"], "se": sm["se"], "support_share": analytics.summarise([r["support_share"] for r in runs])["mean"]})
    return out


# --------------------------------------------------------------------------- interpreting what-ifs

def _sens_keys(pop: dict) -> list[str]:
    ks: set = set()
    for a in pop["agents"]:
        ks.update(a.get("sensitivities", {}))
    return sorted(ks)


def validate_shocks(raw: list, pop: dict, rounds: int) -> list[dict]:
    segs = {s["name"] for s in pop["spec"]["segments"]}
    sens = set(_sens_keys(pop))
    topics = {t["id"] for t in pop["spec"]["topics"]}
    topic = pop["spec"]["topics"][0]["id"]
    out = []
    for s in raw or []:
        if not isinstance(s, dict):
            continue
        effs = []
        for e in s.get("effects", []) or []:
            try:
                d = max(-0.6, min(0.6, float(e.get("delta", 0))))
            except (TypeError, ValueError):
                continue
            seg = e.get("segment", "*")
            sk = e.get("sensitivity") if e.get("sensitivity") in sens else None
            effs.append({"segment": seg if seg in segs or seg == "*" else "*", "sensitivity": sk, "delta": d})
        if not effs:
            continue
        try:
            rnd = max(1, min(rounds, int(s.get("round", max(2, rounds // 3)))))
        except (TypeError, ValueError):
            rnd = max(2, rounds // 3)
        out.append({"round": rnd, "label": str(s.get("label", "External event"))[:160], "description": str(s.get("description", ""))[:400],
                    "topic": s.get("topic") if s.get("topic") in topics else topic, "salience_boost": max(0.0, min(3.0, float(s.get("salience_boost", 0) or 0))), "effects": effs, "reach": max(0.05, min(1.0, float(s.get("reach", 1.0)))), "assumption": True})
    return out


def keyword_shock(text: str, pop: dict, rounds: int) -> dict:
    sens = _sens_keys(pop)
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    pct = float(m.group(1)) if m else 20.0
    mag = min(0.5, pct / 100 * 1.5)
    t = text.lower()
    other = bool(re.search(r"competitor|rival|they|other brand|alternative", t))
    sign = -1 if other else 1
    if re.search(r"increase|raise|hike|higher", t) and "price" in t:
        sign = -sign if not other else 1
    sk = next((k for k in sens if k in t or (k == "price" and re.search(r"cheap|discount|cost|price", t))), sens[0] if sens else None)
    return {"round": max(2, rounds // 3), "label": text[:150], "description": "Keyword-parsed fallback (no LLM): effect size and direction are crude assumptions — review before relying on them.",
            "effects": [{"segment": "*", "sensitivity": sk, "delta": sign * mag}], "reach": 1.0}


async def interpret_shock(provider, text: str, pop: dict, rounds: int, project_id: str = None) -> dict:
    if provider is not None:
        sens = _sens_keys(pop)
        segs = [s["name"] for s in pop["spec"]["segments"]]
        user = (f"Simulated population segments: {segs}. Agent sensitivities available (0..1 each): {sens}. The simulated opinion topic is: "
                f"{pop['spec']['topics'][0]['label']} (+1 = {pop['spec']['topics'][0]['pos_label']}, -1 = {pop['spec']['topics'][0]['neg_label']}). Total rounds: {rounds}.\n"
                f"Scenario assumption to model: \"{text}\".\nTranslate it into external shock(s). Each effect shifts opinion by delta (−0.6..0.6) "
                "for the segment, scaled by the agent's sensitivity. Think about who is affected and in which direction. List your assumptions explicitly.\n"
                'Return JSON: {"shocks":[{"round":int,"label":str,"description":str,"reach":0..1,"effects":[{"segment":"*"|<segment name>,"sensitivity":<key or null>,"delta":float}]}],"assumptions":[str],"rationale":str}')
        try:
            data, res = await provider.chat_json("reasoning", [{"role": "user", "content": user}], temperature=0.3, max_tokens=3500, project_id=project_id)
            shocks = validate_shocks(data.get("shocks"), pop, rounds)
            if shocks:
                return {"shocks": shocks, "assumptions": data.get("assumptions", []), "rationale": data.get("rationale", ""), "method": f"llm:{res.model}"}
        except Exception as e:  # noqa
            fallback_note = f"LLM interpretation failed ({getattr(e, 'kind', e.__class__.__name__)}); keyword fallback used."
            ks = validate_shocks([keyword_shock(text, pop, rounds)], pop, rounds)
            return {"shocks": ks, "assumptions": [fallback_note], "rationale": "", "method": "keyword-fallback"}
    ks = validate_shocks([keyword_shock(text, pop, rounds)], pop, rounds)
    return {"shocks": ks, "assumptions": ["No LLM configured: crude keyword interpretation."], "rationale": "", "method": "keyword-fallback"}


async def propose_scenarios(provider, situation: str, pop: dict, rounds: int, project_id: str = None) -> list[dict]:
    base = {"name": "Baseline", "kind": "baseline", "prompt": "No external change — the population evolves on its own.", "shocks": [], "assumptions": []}
    if provider is None:
        return [base]
    user = (f"Situation under study: {situation}\nPopulation segments: {[s['name'] for s in pop['spec']['segments']]}.\n"
            "Propose 3 plausible alternative scenarios to test against the baseline: one optimistic, one pessimistic, one alternative. "
            "Each is a single concrete external development stated in one sentence. Return JSON: "
            '{"scenarios":[{"name":str,"kind":"optimistic|pessimistic|alternative","prompt":str}]}')
    try:
        data, _ = await provider.chat_json("reasoning", [{"role": "user", "content": user}], temperature=0.6, max_tokens=1500, project_id=project_id)
    except Exception:
        return [base]
    out = [base]
    for s in (data.get("scenarios") or [])[:4]:
        if isinstance(s, dict) and s.get("prompt"):
            k = s.get("kind") if s.get("kind") in ("optimistic", "pessimistic", "alternative") else "alternative"
            out.append({"name": str(s.get("name", k.title()))[:80], "kind": k, "prompt": str(s["prompt"])[:300], "shocks": [], "assumptions": []})
    return out
