"""Report generation. Every block is classified FACT | ANALYSIS | ESTIMATE | SIMULATION | RECOMMENDATION and carries sources."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

KINDS = ("FACT", "ANALYSIS", "ESTIMATE", "SIMULATION", "RECOMMENDATION")
SIM_DISCLAIMER = "Simulation outputs are model results under stated assumptions, not predictions of what will happen."


def B(kind: str, text: str, sources=None) -> dict:
    assert kind in KINDS
    return {"kind": kind, "text": text, "sources": sources or []}


def _pct(x): return f"{x * 100:.0f}%"


async def executive_summary(provider, ctx: dict, project_id: str) -> list[dict]:
    a = ctx["analysis"]; fin = a["final"]
    base = [B("SIMULATION", f"Across {ctx['population']['n']} simulated agents and {fin.get('rounds', len(a['trajectory']))} rounds, final mean opinion was {fin.get('mean_opinion', 0):+.2f} "
                            f"(support {fin.get('support', 0)}, neutral {fin.get('neutral', 0)}, oppose {fin.get('oppose', 0)}); polarisation index {fin.get('polarisation', 0):.2f}; "
                            f"{fin.get('groups', 0)} communities formed.")]
    for s in a["shock_responses"][:2]:
        base.append(B("SIMULATION", f"Scenario assumption at round {s['round']} (“{s['label'][:90]}”) moved mean opinion by {s['delta']:+.2f} within three rounds.{' This effect size is an unverified assumption.' if s['assumption'] else ''}"))
    for r in ctx.get("recommendations", [])[:2]:
        base.append(B("RECOMMENDATION", r["action"]))
    if provider is not None:
        try:
            facts = {"project": ctx["project"]["name"], "situation": ctx["project"].get("situation", "")[:800], "final": fin, "shock_responses": a["shock_responses"][:3],
                     "segments": a["segments"], "top_recommendations": [r["action"] for r in ctx.get("recommendations", [])[:3]]}
            res = await provider.chat("report", [
                {"role": "system", "content": "You write the executive summary of an analytical report in 120-170 words. Use ONLY the facts given. State that findings are simulation results, never certainties or probabilities of real events. No headings."},
                {"role": "user", "content": json.dumps(facts, default=str)}], temperature=0.3, max_tokens=2500, project_id=project_id)
            if res.content.strip():
                return [B("ANALYSIS", res.content.strip())] + base
        except Exception:
            pass
    return base


async def build_report(provider, ctx: dict, project_id: str = None) -> dict:
    p, a, pop, kb = ctx["project"], ctx["analysis"], ctx["population"], ctx.get("knowledge")
    S: list[dict] = []
    add = lambda title, blocks: S.append({"n": len(S) + 1, "title": title, "blocks": blocks})

    add("Executive summary", await executive_summary(provider, ctx, project_id))
    add("Situation overview", [B("FACT", p.get("situation") or "No situation text was provided.", [{"doc": "Provided by the user"}])])
    add("Research objectives", [B("FACT", p.get("objectives") or "No explicit objectives were provided; the default objective is to understand how collective opinion may evolve.", [{"doc": "Provided by the user"}])]
        + ([B("ANALYSIS", "Methodology: " + "; ".join(m["name"] for m in ctx["methodology"]["methods"]) + ". " + " ".join(ctx["methodology"]["rationale"]))] if ctx.get("methodology") else []))

    src_blocks = []
    docs = ctx.get("documents", [])
    if docs:
        for d in docs:
            src_blocks.append(B("FACT", f"Source “{d['name']}” ({d['kind']}, {len(d.get('text', ''))} characters)" + (f" — {d['url']}" if d.get("url") else ""), [{"doc": d["name"]}]))
    else:
        src_blocks.append(B("ANALYSIS", "No documents were supplied; the population and scenarios rest on simulation assumptions only."))
    if kb:
        by_t = {}
        for f in kb["facts"]:
            by_t[f["temporal"]] = by_t.get(f["temporal"], 0) + 1
        src_blocks.append(B("ANALYSIS", f"Extraction method: {kb['method']}. {len(kb['facts'])} facts extracted ({', '.join(f'{v} {k}' for k, v in by_t.items()) or 'none'}), classified as historical, current or assumption."))
        for f in [f for f in kb["facts"] if f["temporal"] != "assumption"][:8]:
            src_blocks.append(B("FACT", f"{f['text']} [{f['temporal']}]", [{"doc": f['source_ref']['doc'], "quote": f.get("quote", "")}]))
        for f in [f for f in kb["facts"] if f["temporal"] == "assumption"][:4]:
            src_blocks.append(B("ESTIMATE", f"{f['text']} [stated as assumption/forecast in source]", [{"doc": f['source_ref']['doc'], "quote": f.get("quote", "")}]))
        for c in kb.get("contradictions", [])[:5]:
            src_blocks.append(B("ANALYSIS", f"Contradiction: “{c['a']['text']}” ({c['a']['source']['doc']}) vs “{c['b']['text']}” ({c['b']['source']['doc']}). {c['explanation']}", [{"doc": c['a']['source']['doc']}, {"doc": c['b']['source']['doc']}]))
    add("Source analysis", src_blocks)

    st = []
    if kb:
        top = sorted([n for n in kb["nodes"] if n["type"] in ("person", "organisation", "stakeholder", "product", "market")], key=lambda n: -n["degree"])[:8]
        for n in top:
            st.append(B("FACT", f"{n['label']} ({n['type']}), {n['degree']} connections. {n['description']}", n["sources"][:2]))
        for o in kb.get("opinions", [])[:6]:
            st.append(B("FACT", f"{o['holder']}: {o['stance']}", [{"doc": o['source_ref']['doc'], "quote": o.get("quote", "")}]))
    for s in a["segments"]:
        st.append(B("SIMULATION", f"Simulated segment “{s['segment']}” (n={s['n']}): mean opinion {s['start']:+.2f} → {s['end']:+.2f}."))
    add("Stakeholder analysis", st or [B("ANALYSIS", "No stakeholders could be identified.")])

    kg = []
    if kb:
        kg.append(B("ANALYSIS", f"The knowledge graph has {len(kb['nodes'])} entities, {len(kb['edges'])} relationships and {len(set(n['cluster'] for n in kb['nodes']))} clusters."))
        for n in sorted(kb["nodes"], key=lambda n: -n["degree"])[:6]:
            kg.append(B("ANALYSIS", f"Influential entity: {n['label']} — {n['degree']} weighted connections, mentioned {n['mentions']}×.", n["sources"][:2]))
    add("Knowledge graph findings", kg or [B("ANALYSIS", "No knowledge graph was built for this project.")])

    pb = [B("ESTIMATE", f"{pop['n']} agents across {len(pop['segments'])} segments: " + "; ".join(f"{s['name']} ({_pct(s['share'])})" for s in pop["segments"]) + ".")]
    pb += [B("ESTIMATE", "Assumption: " + x) for x in pop.get("assumptions", [])]
    pb.append(B("ANALYSIS", f"Population basis: {pop.get('basis', 'assumption')}. Attributes not stated in supplied evidence are simulation assumptions. All agents are fictional; none represent real individuals."))
    add("Agent population", pb)

    ic = a["interaction_counts"]
    add("Interaction patterns", [B("SIMULATION", "Recorded interactions: " + ", ".join(f"{v} {k}" for k, v in ic.items()) + f". Disagreement rate among agree/disagree responses: {_pct(a['disagreement_rate'])}.")]
        + [B("SIMULATION", f"Most influential agent profiles (PageRank on who changed whose opinion): " + "; ".join(f"{t['name']} ({t['segment']}, {t['score']:.2f})" for t in a["top_influencers"][:5]) + ".")])

    sr = []
    if a["trajectory"]:
        t0, t1 = a["trajectory"][0], a["trajectory"][-1]
        sr.append(B("SIMULATION", f"Mean opinion moved {t0['mean_opinion']:+.2f} → {t1['mean_opinion']:+.2f}; polarisation {t0['polarisation']:.2f} → {t1['polarisation']:.2f}; communities {t0['groups']} → {t1['groups']}."))
    mc = ctx.get("monte_carlo")
    if mc:
        mo = mc["mean_opinion"]
        sr.append(B("ESTIMATE", f"Across {mo['n']} Monte Carlo replicates, final mean opinion averaged {mo['mean']:+.2f} (5–95%: {mo['p05']:+.2f} to {mo['p95']:+.2f}). "
                                f"Replicate-level support majority occurred {mc['support_majority']['k']}/{mc['support_majority']['n']} times (Beta posterior mean {mc['support_majority']['mean']:.2f}, 95% interval {mc['support_majority']['ci95'][0]:.2f}–{mc['support_majority']['ci95'][1]:.2f}) — a model-conditional figure, not a real-world probability."))
    sr.append(B("ANALYSIS", SIM_DISCLAIMER))
    add("Simulation results", sr)

    eb = []
    for c in a["largest_cascades"][:3]:
        eb.append(B("SIMULATION", f"Information cascade reached {c['size']} participants."))
    for g, name in list(a["groups"].items())[:5]:
        eb.append(B("SIMULATION", f"Community: {name}."))
    for ch in a["opinion_band_changes"][:4]:
        eb.append(B("SIMULATION", f"{ch['count']} agents moved from {ch['from']} to {ch['to']}."))
    for s in a["shock_responses"]:
        eb.append(B("SIMULATION", f"Round {s['round']} external event: mean opinion {s['mean_before']:+.2f} → {s['mean_after']:+.2f} three rounds later."))
    add("Emerging behaviours", eb or [B("ANALYSIS", "No notable emergent structures were detected.")])

    sc = []
    for s in ctx.get("scenarios", []):
        sc.append(B("ANALYSIS", f"Scenario “{s['name']}” ({s['kind']}): {s['prompt']}" + (f" Assumptions: {'; '.join(s['assumptions'])}" if s.get("assumptions") else "")))
        cmp_ = s.get("comparison")
        if cmp_:
            for k, label in (("mean_opinion", "mean opinion"), ("support_share", "support share"), ("polarisation", "polarisation")):
                d = cmp_["differences"][k]
                sc.append(B("SIMULATION", f"  {label}: {d['mean_diff']:+.3f} vs baseline (95% interval {d['ci95'][0]:+.3f} to {d['ci95'][1]:+.3f}; {'distinguishable from zero' if d['distinguishable_from_zero'] else 'not distinguishable from zero'}; n={d['n']} paired runs)."))
    if ctx.get("scenarios"):
        sc.append(B("ANALYSIS", "Uncertainty: " + ctx["scenarios"][-1].get("comparison", {}).get("uncertainty", SIM_DISCLAIMER)))
    add("Alternative scenarios", sc or [B("ANALYSIS", "No alternative scenarios were run.")])

    ro = []
    if kb:
        for r in kb.get("risks", [])[:5]:
            ro.append(B("FACT", "Risk stated in sources: " + r["text"], [{"doc": r["source_ref"]["doc"]}]))
    f = a["final"]
    if f.get("polarisation", 0) > 0.5:
        ro.append(B("SIMULATION", f"Risk: polarisation index {f['polarisation']:.2f} suggests entrenched camps."))
    worst = sorted(a["segments"], key=lambda s: s["end"])[:1]
    best = sorted(a["segments"], key=lambda s: -s["end"])[:1]
    for s in worst: ro.append(B("SIMULATION", f"Risk: segment “{s['segment']}” ends least favourable (mean {s['end']:+.2f})."))
    for s in best: ro.append(B("SIMULATION", f"Opportunity: segment “{s['segment']}” ends most favourable (mean {s['end']:+.2f}) and can be mobilised."))
    for t in a["top_influencers"][:1]: ro.append(B("SIMULATION", f"Opportunity: profiles like “{t['name']}” carry high influence in the simulated network."))
    add("Risks and opportunities", ro)

    rc = []
    for i, r in enumerate(ctx.get("recommendations", []), 1):
        rc.append(B("RECOMMENDATION", f"{i}. {r['action']}  [priority {r['priority']}/100 · impact {r['scores']['impact']} feasibility {r['scores']['feasibility']} urgency {r['scores']['urgency']} risk {r['scores']['risk']}]"))
        for key in ("reasoning", "simulation_findings", "evidence", "benefits", "risks", "tradeoffs", "assumptions", "resources", "success_indicators"):
            if r.get(key):
                rc.append(B("SIMULATION" if key == "simulation_findings" else "ANALYSIS" if key != "evidence" else "FACT", f"   {key.replace('_', ' ').capitalize()}: " + "; ".join(r[key])))
    add("Strategic recommendations", rc or [B("ANALYSIS", "No recommendations were generated.")])

    lim = [B("ANALYSIS", x) for x in [
        "Agents are fictional. Their traits, goals and starting opinions are simulation assumptions unless a source states otherwise.",
        "Interaction structure comes from an inspectable opinion-dynamics model (bounded confidence with backlash); language is added by " + ("a language model" if ctx.get("llm_text") else "deterministic templates") + ".",
        "Simulation results depend on the seed, population and scenario effect sizes; use the Monte Carlo intervals, not single runs.",
        SIM_DISCLAIMER, "Single-topic opinion model: richer attitudes, offline events and media effects are not represented."]]
    add("Limitations", lim)

    sa = [B("ANALYSIS", f"Report generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. Simulation engine: {ctx.get('engine', 'anvaya-native')}; mode: {ctx.get('mode', 'native')}.")]
    if ctx.get("usage"):
        sa.append(B("FACT", f"Model usage for this project: {ctx['usage']['total_tokens']:,} tokens, estimated cost ${ctx['usage']['total_cost_usd']:.4f} (from provider-listed per-1k prices)."))
    sa += [B("ESTIMATE", "Assumption: " + x) for x in ctx.get("assumptions", [])]
    add("Sources and assumptions", sa)
    return {"title": f"ANVAYA report · {p['name']}", "generated": datetime.now(timezone.utc).isoformat(), "sections": S}


def to_markdown(rep: dict) -> str:
    out = [f"# {rep['title']}", f"_Generated {rep['generated']}. Claim classes: FACT · ANALYSIS · ESTIMATE · SIMULATION · RECOMMENDATION. {SIM_DISCLAIMER}_", ""]
    for s in rep["sections"]:
        out += [f"## {s['n']}. {s['title']}", ""]
        for b in s["blocks"]:
            src = ""
            if b["sources"]:
                src = " _(sources: " + "; ".join(x.get("doc", "") + (f" — “{x['quote'][:80]}”" if x.get("quote") else "") for x in b["sources"][:3]) + ")_"
            out.append(f"- **[{b['kind']}]** {b['text'].strip()}{src}")
        out.append("")
    return "\n".join(out)


def to_pdf(rep: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape

    def clean(t: str) -> str:
        return escape(t.replace("→", "->").replace("“", '"').replace("”", '"').replace("’", "'").replace("—", "-").replace("–", "-").replace("×", "x").replace("·", "|").replace("≈", "~")
                      .encode("latin-1", "replace").decode("latin-1"))
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=20, spaceAfter=6, textColor=colors.HexColor("#1a1230"))
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=5, textColor=colors.HexColor("#4a2fbd"))
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.4, leading=13, spaceAfter=3.5)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.HexColor("#666666"))
    colmap = {"FACT": "#0b7a5a", "ANALYSIS": "#3b4bb8", "ESTIMATE": "#a56a00", "SIMULATION": "#6b2fd1", "RECOMMENDATION": "#b0173d"}
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm, title=clean(rep["title"]))
    el = [Paragraph(clean(rep["title"]), h1), Paragraph(clean(f"Generated {rep['generated'][:19]} UTC. {SIM_DISCLAIMER}"), small), Spacer(1, 6)]
    for s in rep["sections"]:
        el.append(Paragraph(clean(f"{s['n']}. {s['title']}"), h2))
        for b in s["blocks"]:
            src = ""
            if b["sources"]:
                src = " <font size=7 color='#888888'>(" + clean("; ".join(x.get("doc", "") for x in b["sources"][:3])) + ")</font>"
            el.append(Paragraph(f"<font color='{colmap[b['kind']]}'><b>[{b['kind']}]</b></font> {clean(b['text'].strip())}{src}", body))
    doc.build(el)
    return buf.getvalue()


def events_csv(events: list[dict], agents: list[dict]) -> str:
    name = {a["id"]: a["name"] for a in agents}
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["event_id", "seq", "round", "type", "source_id", "source_name", "target_id", "target_name", "topic", "content_source", "decided_by", "content", "reason", "timestamp"])
    for e in events:
        if e["type"] in ("round_start", "round_end", "sim_start", "sim_end"):
            continue
        w.writerow([e["id"], e["seq"], e["round"], e["type"], e.get("source_agent"), name.get(e.get("source_agent"), ""), e.get("target_agent"), name.get(e.get("target_agent"), ""),
                    e.get("topic"), e.get("content_source"), (e.get("result") or {}).get("decided_by", ""), e.get("content", ""), e.get("reason", ""), e.get("timestamp")])
    return buf.getvalue()


def metrics_csv(trajectory: list[dict]) -> str:
    buf = io.StringIO()
    if not trajectory:
        return ""
    w = csv.DictWriter(buf, fieldnames=list(trajectory[0].keys())); w.writeheader(); w.writerows(trajectory)
    return buf.getvalue()


def agents_csv(agents: list[dict], final_opinions: dict, topic: str) -> str:
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["id", "name", "segment", "age", "occupation", "location", "influence_base", "opinion_start", "opinion_end", "basis"])
    for a in agents:
        w.writerow([a["id"], a["name"], a["segment"], a["age"], a["occupation"], a["location"], a["influence"], a["opinions"].get(topic), final_opinions.get(str(a["id"])), a["attributes_basis"]])
    return buf.getvalue()
