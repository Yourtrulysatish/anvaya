"""Decision intelligence: ranked recommendations grounded in measured results."""
from __future__ import annotations

import json
from typing import Optional

REC_KEYS = ["action", "reasoning", "evidence", "simulation_findings", "benefits", "risks", "tradeoffs", "assumptions", "resources", "success_indicators"]


def priority(scores: dict) -> float:
    """Impact, feasibility and urgency raise priority; risk lowers it. All inputs 1-5. Returns 0-100."""
    i, f, u, r = (max(1, min(5, float(scores.get(k, 3)))) for k in ("impact", "feasibility", "urgency", "risk"))
    return round(((i * 0.35 + f * 0.25 + u * 0.2 + (6 - r) * 0.2) - 1) / 4 * 100, 1)


def _clean(rec: dict) -> Optional[dict]:
    if not isinstance(rec, dict) or not rec.get("action"):
        return None
    out = {"action": str(rec["action"])[:240], "kind": "RECOMMENDATION"}
    for k in REC_KEYS[1:]:
        v = rec.get(k, [])
        out[k] = [str(x)[:300] for x in v][:6] if isinstance(v, list) else ([str(v)[:300]] if v else [])
    sc = rec.get("scores") or {}
    out["scores"] = {k: max(1, min(5, int(float(sc.get(k, 3))))) for k in ("impact", "feasibility", "urgency", "risk")}
    out["priority"] = priority(out["scores"])
    return out


def heuristic_recommendations(ctx: dict) -> list[dict]:
    """Rule-based fallback driven only by computed metrics (labelled as such)."""
    fin = ctx["analysis"]["final"]; recs = []
    segs = sorted(ctx["analysis"]["segments"], key=lambda s: s["end"])
    if segs:
        low = segs[0]
        recs.append(_clean({"action": f"Prioritise engagement with the '{low['segment']}' segment, which ends least favourable (mean {low['end']:+.2f}).",
                            "reasoning": ["It is the segment with the lowest final mean opinion in the simulation."], "evidence": [],
                            "simulation_findings": [f"{low['segment']}: mean opinion {low['start']:+.2f} → {low['end']:+.2f}"],
                            "benefits": ["Targets the largest gap in support."], "risks": ["Segment attributes are simulation assumptions."], "tradeoffs": ["Effort diverted from already-favourable segments."],
                            "assumptions": ["Segment composition reflects the real audience."], "resources": ["Segment-specific messaging and channel plan."],
                            "success_indicators": ["Segment support share rises in follow-up measurement."], "scores": {"impact": 4, "feasibility": 3, "urgency": 3, "risk": 2}}))
    if fin.get("polarisation", 0) > 0.55:
        recs.append(_clean({"action": "Address polarisation early: provide neutral, evidence-based information before positions harden.",
                            "reasoning": [f"Polarisation index reached {fin['polarisation']:.2f} (0–1)."], "evidence": [],
                            "simulation_findings": [f"{fin.get('oppose', 0)} opposed vs {fin.get('support', 0)} supportive at the end"],
                            "benefits": ["Reduces entrenched opposition."], "risks": ["Neutral messaging may be ignored by committed agents."], "tradeoffs": ["Slower than persuasive campaigns."],
                            "assumptions": ["Opinion dynamics resemble bounded confidence."], "resources": ["Communications lead, fact sheet."], "success_indicators": ["Polarisation index declines."],
                            "scores": {"impact": 3, "feasibility": 4, "urgency": 4, "risk": 2}}))
    for t in ctx["analysis"]["top_influencers"][:1]:
        recs.append(_clean({"action": f"Engage high-influence voices such as profiles like '{t['name']}' ({t['segment']}).",
                            "reasoning": ["Highest computed influence score (PageRank on who-changed-whose-opinion)."], "evidence": [],
                            "simulation_findings": [f"influence score {t['score']}"], "benefits": ["Information cascades start from influential agents."],
                            "risks": ["Real influencers may differ from simulated ones."], "tradeoffs": ["Dependence on few voices."], "assumptions": ["Influence structure resembles the simulated network."],
                            "resources": ["Partnership budget"], "success_indicators": ["Cascade size, reach."], "scores": {"impact": 4, "feasibility": 3, "urgency": 3, "risk": 3}}))
    out = [r for r in recs if r]
    out.sort(key=lambda r: -r["priority"])
    return out


async def recommend(provider, ctx: dict, project_id: str = None) -> dict:
    """ctx: {situation, objectives, analysis, scenarios:[{name,summary,comparison}], knowledge_facts:[...]}"""
    if provider is not None:
        sys = ("You are a decision analyst. Produce 3-5 recommendations that follow from the MEASURED results provided. Every item must cite the "
               "specific simulation findings or evidence that support it (quote the numbers given). Never claim certainty or probabilities about the real world; "
               "simulation results are model outputs. List the assumptions each recommendation depends on. Score impact, feasibility, urgency and risk from 1 to 5.")
        user = ("Situation: " + str(ctx.get("situation", "")) + "\nObjectives: " + str(ctx.get("objectives", "")) + "\nSimulation analysis (computed):\n"
                + json.dumps(ctx["analysis"], default=str)[:7000] + "\nScenario comparisons (computed):\n" + json.dumps(ctx.get("scenarios", []), default=str)[:5000]
                + "\nEvidence facts from sources:\n" + json.dumps(ctx.get("knowledge_facts", [])[:15], default=str)[:2500]
                + '\nReturn JSON: {"recommendations":[{"action":str,"reasoning":[str],"evidence":[str],"simulation_findings":[str],"benefits":[str],"risks":[str],"tradeoffs":[str],'
                '"assumptions":[str],"resources":[str],"success_indicators":[str],"scores":{"impact":1-5,"feasibility":1-5,"urgency":1-5,"risk":1-5}}]}')
        try:
            data, res = await provider.chat_json("reasoning", [{"role": "system", "content": sys}, {"role": "user", "content": user}], temperature=0.4, max_tokens=6000, project_id=project_id)
            recs = [r for r in (_clean(x) for x in data.get("recommendations", [])) if r]
            if recs:
                recs.sort(key=lambda r: -r["priority"])
                return {"recommendations": recs, "method": f"llm:{res.model}", "priority_formula": "35% impact + 25% feasibility + 20% urgency + 20% (inverse risk)"}
        except Exception as e:  # noqa
            return {"recommendations": heuristic_recommendations(ctx), "method": f"heuristic (LLM failed: {getattr(e, 'kind', e.__class__.__name__)})", "priority_formula": "35% impact + 25% feasibility + 20% urgency + 20% (inverse risk)"}
    return {"recommendations": heuristic_recommendations(ctx), "method": "heuristic (no LLM)", "priority_formula": "35% impact + 25% feasibility + 20% urgency + 20% (inverse risk)"}
