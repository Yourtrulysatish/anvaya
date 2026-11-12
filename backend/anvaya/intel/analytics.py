"""Analytical methods. The platform selects methods from the question rather than defaulting to a multi-agent simulation."""
from __future__ import annotations

import math
import random
import statistics as st
from collections import Counter, defaultdict
from typing import Optional

import numpy as np

METHODS = {
    "descriptive": "Descriptive statistics over supplied datasets",
    "trend": "Trend analysis (linear fit with uncertainty)",
    "diagnostic": "Diagnostic analysis of what drove changes in a run",
    "scenario": "Scenario analysis (baseline vs alternative assumptions)",
    "sensitivity": "One-at-a-time sensitivity analysis of the key assumption",
    "monte_carlo": "Monte Carlo replicates of the stochastic simulation model",
    "bayesian": "Bayesian (Beta-Binomial) estimate of model-conditional outcome probabilities",
    "multi_agent": "Multi-agent simulation of interacting individuals",
    "financial": "Financial / market arithmetic on supplied figures",
    "causal": "Causal reasoning — only where explicit assumptions support it",
}


def select_methods(question: str, has_dataset: bool, has_docs: bool, n_agents_hint: Optional[int] = None) -> dict:
    q = question.lower()
    has = lambda *ws: any(w in q for w in ws)
    chosen: list[str] = []
    why: list[str] = []
    social = has("react", "opinion", "spread", "viral", "adopt", "sentiment", "public", "consumers", "voters", "customers", "community", "polaris",
                 "rumour", "rumor", "misinformation", "social", "population", "stakeholder", "crowd", "audience", "behaviour", "behavior")
    whatif = has("what if", "scenario", "if the", "if a ", "suppose", "alternative", "compare", "versus", " vs ")
    numeric = has("forecast", "trend", "growth", "revenue", "price", "cost", "sales", "profit", "margin", "average", "correlat", "statistic", "how many", "how much")
    risk = has("risk", "probab", "likelihood", "chance", "uncertain", "odds")
    if has_dataset and (numeric or not social):
        chosen += ["descriptive"]; why.append("Structured data is supplied and the question is quantitative, so descriptive statistics come first.")
        if has("trend", "forecast", "growth", "over time"):
            chosen.append("trend"); why.append("The question asks about change over time.")
        if has("revenue", "profit", "margin", "cost", "price", "roi", "valuation"):
            chosen.append("financial"); why.append("Financial quantities are involved.")
    if social:
        chosen.append("multi_agent")
        why.append("The question concerns how many interacting people form, spread or change opinions — an emergent social process that "
                   "aggregate statistics cannot represent, so a multi-agent simulation is warranted.")
        chosen.append("diagnostic")
    if whatif:
        chosen += ["scenario", "sensitivity"]; why.append("The question compares alternative assumptions, so scenario and sensitivity analysis are used.")
    if social or whatif or risk:
        chosen += ["monte_carlo"]; why.append("The simulation is stochastic, so results are reported across replicates with intervals instead of single runs.")
    if risk:
        chosen.append("bayesian"); why.append("A probability-style question: reported only as a model-conditional Beta-Binomial estimate, not a real-world probability.")
    if has("because", "cause", "effect of", "impact of", "why did"):
        chosen.append("causal"); why.append("Causal wording detected; conclusions are conditional on stated assumptions and flagged as such.")
    if not chosen:
        chosen = ["descriptive"] + (["diagnostic"] if has_docs else [])
        why.append("No simulation-specific signals found; ordinary analysis of the supplied material is sufficient.")
    chosen = list(dict.fromkeys(chosen))
    sim_needed = "multi_agent" in chosen
    return {"methods": [{"id": m, "name": METHODS[m]} for m in chosen], "rationale": why, "simulation_recommended": sim_needed,
            "note": None if sim_needed else "A multi-agent simulation is NOT recommended here: it would add cost without adding insight."}


# --------------------------------------------------------------------------- datasets

def describe_table(table: dict) -> dict:
    cols, rows = table["columns"], table["rows"]
    out = {"rows": len(rows), "columns": []}
    numeric_cols: dict[str, list[float]] = {}
    for j, c in enumerate(cols):
        vals = [r[j] for r in rows if j < len(r)]
        missing = sum(1 for v in vals if v in ("", "None", "nan", "NaN", "null"))
        nums = []
        for v in vals:
            try:
                nums.append(float(str(v).replace(",", "")))
            except ValueError:
                pass
        info = {"name": c, "missing": missing}
        if len(nums) >= max(3, 0.7 * (len(vals) - missing)) and nums:
            arr = np.array(nums)
            info.update(type="numeric", count=len(nums), mean=round(float(arr.mean()), 4), std=round(float(arr.std(ddof=1)) if len(arr) > 1 else 0.0, 4),
                        min=float(arr.min()), q1=float(np.percentile(arr, 25)), median=float(np.median(arr)), q3=float(np.percentile(arr, 75)), max=float(arr.max()))
            numeric_cols[c] = nums
        else:
            top = Counter(v for v in vals if v).most_common(5)
            info.update(type="categorical", unique=len(set(vals)), top=[{"value": v, "count": n} for v, n in top])
        out["columns"].append(info)
    names = [c for c, v in numeric_cols.items() if len(v) == len(rows)]
    if len(names) >= 2:
        m = np.array([numeric_cols[c] for c in names])
        corr = np.corrcoef(m)
        out["correlations"] = [{"a": names[i], "b": names[j], "r": round(float(corr[i, j]), 3)} for i in range(len(names)) for j in range(i + 1, len(names)) if not math.isnan(corr[i, j])]
        out["correlations"].sort(key=lambda c: -abs(c["r"]))
        out["correlations"] = out["correlations"][:12]
    out["trends"] = {c: linear_trend(v) for c, v in list(numeric_cols.items())[:6] if len(v) >= 6}
    return out


def linear_trend(values: list[float]) -> dict:
    y = np.array(values, dtype=float); x = np.arange(len(y), dtype=float)
    n = len(y)
    slope, intercept = np.polyfit(x, y, 1)
    resid = y - (slope * x + intercept)
    se = math.sqrt(float((resid ** 2).sum()) / max(1, n - 2)) / math.sqrt(float(((x - x.mean()) ** 2).sum()) or 1)
    ss_tot = float(((y - y.mean()) ** 2).sum()) or 1
    return {"slope_per_step": round(float(slope), 5), "ci95": [round(float(slope - 1.96 * se), 5), round(float(slope + 1.96 * se), 5)],
            "r2": round(1 - float((resid ** 2).sum()) / ss_tot, 4), "n": n,
            "significant": bool(abs(slope) > 1.96 * se), "kind": "ESTIMATE"}


# --------------------------------------------------------------------------- simulation analytics

def analyse_events(events: list[dict], agents: list[dict], topic: str) -> dict:
    ends = [e for e in events if e["type"] == "round_end"]
    final = next((e for e in reversed(events) if e["type"] == "sim_end"), None)
    traj = [{"round": e["round"], **{k: e["result"].get(k) for k in ("mean_opinion", "polarisation", "consensus", "support", "neutral", "oppose", "groups", "modularity", "max_cascade", "active_agents", "round_interactions")}} for e in ends]
    by_type = Counter(e["type"] for e in events if e["type"] in ("post", "reply", "agree", "disagree", "share"))
    # per-segment opinion shift (first vs last round) – diagnostic
    seg = defaultdict(lambda: {"n": 0, "start": 0.0, "end": 0.0})
    final_ops = (final or {}).get("result", {}).get("final_opinions", {})
    for a in agents:
        s = seg[a["segment"]]; s["n"] += 1
        s["start"] += a["opinions"].get(topic, 0); s["end"] += final_ops.get(str(a["id"]), a["opinions"].get(topic, 0))
    segments = [{"segment": k, "n": v["n"], "start": round(v["start"] / v["n"], 3), "end": round(v["end"] / v["n"], 3), "shift": round((v["end"] - v["start"]) / v["n"], 3)} for k, v in seg.items()]
    # cascades
    cascades = sorted((e["result"] for e in events if e["type"] == "cascade"), key=lambda r: -r["size"])
    sizes = Counter()
    for e in events:
        if e["type"] == "cascade":
            sizes[e["result"]["root"]] = max(sizes[e["result"]["root"]], e["result"]["size"])
    # response to external events: mean opinion 2 rounds before vs 3 after
    shocks = []
    for e in events:
        if e["type"] == "external_event":
            r = e["round"]
            pre = [t for t in traj if t["round"] == r - 1]; post = [t for t in traj if t["round"] == min(r + 3, len(traj))]
            if pre and post:
                shocks.append({"round": r, "label": e["content"], "affected": e["result"].get("affected"), "mean_before": pre[0]["mean_opinion"], "mean_after": post[0]["mean_opinion"],
                               "delta": round(post[0]["mean_opinion"] - pre[0]["mean_opinion"], 4), "assumption": e["result"].get("assumption", True)})
    infl = (final or {}).get("result", {}).get("influence", {})
    top = sorted(infl.items(), key=lambda kv: -kv[1])[:8]
    name = {str(a["id"]): a["name"] for a in agents}
    seg_of = {str(a["id"]): a["segment"] for a in agents}
    opinion_changes = [e for e in events if e["type"] == "opinion_change"]
    flips = Counter((e["result"]["from_band"], e["result"]["to_band"]) for e in opinion_changes)
    return {
        "trajectory": traj, "interaction_counts": dict(by_type), "segments": segments,
        "largest_cascades": cascades[:5], "cascade_count": len(sizes), "shock_responses": shocks,
        "top_influencers": [{"agent": int(i), "name": name.get(i, i), "segment": seg_of.get(i), "score": s} for i, s in top],
        "opinion_band_changes": [{"from": a, "to": b, "count": c} for (a, b), c in flips.most_common()],
        "final": {k: v for k, v in (final or {}).get("result", {}).items() if k not in ("influence", "final_opinions", "agent_groups")},
        "groups": (final or {}).get("result", {}).get("group_names", {}),
        "disagreement_rate": round(by_type["disagree"] / max(1, by_type["agree"] + by_type["disagree"]), 3),
    }


# --------------------------------------------------------------------------- Monte Carlo / sensitivity / Bayesian

def beta_posterior(k: int, n: int, a0: float = 1.0, b0: float = 1.0) -> dict:
    a, b = a0 + k, b0 + n - k
    rng = np.random.default_rng(11)
    s = rng.beta(a, b, 20000)
    return {"alpha": a, "beta": b, "mean": round(a / (a + b), 4), "ci95": [round(float(np.percentile(s, 2.5)), 4), round(float(np.percentile(s, 97.5)), 4)], "n": n, "k": k}


def summarise(values: list[float]) -> dict:
    arr = np.array(values, dtype=float)
    n = len(arr)
    return {"n": n, "mean": round(float(arr.mean()), 4), "sd": round(float(arr.std(ddof=1)) if n > 1 else 0.0, 4),
            "p05": round(float(np.percentile(arr, 5)), 4), "p50": round(float(np.percentile(arr, 50)), 4), "p95": round(float(np.percentile(arr, 95)), 4),
            "se": round(float(arr.std(ddof=1) / math.sqrt(n)) if n > 1 else 0.0, 4)}


def paired_difference(base: list[float], var: list[float]) -> dict:
    d = np.array(var) - np.array(base)
    n = len(d)
    se = float(d.std(ddof=1) / math.sqrt(n)) if n > 1 else 0.0
    m = float(d.mean())
    return {"mean_diff": round(m, 4), "ci95": [round(m - 1.96 * se, 4), round(m + 1.96 * se, 4)], "n": n,
            "distinguishable_from_zero": bool(n > 1 and abs(m) > 1.96 * se), "kind": "SIMULATION"}
