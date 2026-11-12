"""Generate the reproducible DEMO run (no LLM, deterministic seed). Output is a static JSON the frontend replays.

    python scripts/make_demo.py            -> ../frontend/public/demo/run.json
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anvaya.agents.generator import PopulationSpec, SegmentSpec, sample  # noqa: E402
from anvaya.sim.engine import SimConfig, Shock, Topic  # noqa: E402
from anvaya.sim.runner import SimulationRun  # noqa: E402
from anvaya import scenarios as scen, decisions, reports  # noqa: E402
from anvaya.intel import analytics  # noqa: E402
from dataclasses import asdict  # noqa: E402

SEED, N, ROUNDS = 42, 140, 24

T = lambda o, c, s, a, e: {"openness": [o, .15], "conformity": [c, .15], "extraversion": [s, .18], "agreeableness": [a, .15], "stubbornness": [e, .15]}
IN_FIRST = ["Aarav", "Meera", "Kabir", "Ananya", "Rohan", "Isha", "Vikram", "Zoya", "Arjun", "Diya", "Imran", "Sana", "Neel", "Tara", "Dev",
            "Riya", "Yash", "Nisha", "Farhan", "Pooja", "Kiran", "Lakshmi", "Harsh", "Mira", "Sameer", "Priya", "Tanvi", "Rahul"]
IN_LAST = ["Sharma", "Iyer", "Khan", "Patel", "Nair", "Reddy", "Das", "Gill", "Menon", "Joshi", "Bose", "Rao", "Kapoor", "Singh", "Verma", "Ali", "Pillai", "Mehta"]

SEGMENTS = [
    SegmentSpec("Students", .22, "A college student managing a tight allowance and following tech reels.",
                traits=T(.7, .6, .65, .55, .3), sensitivities={"price": [.85, .1], "novelty": [.6, .2], "brand": [.35, .2]},
                opinion={"t1": [-.15, .35]}, activity=[.42, .12], influence=[.2, .15],
                goals=["get the best camera under budget", "avoid EMI debt", "keep up with friends' phones"],
                beliefs=["flagship prices are unjustified", "YouTube reviews beat shop advice", "last year's model is good enough"],
                occupations=["engineering student", "arts student", "medical student", "design student"], locations=["Pune", "Delhi", "Chennai", "Kolkata"], age=[21, 2],
                first_names=IN_FIRST, last_names=IN_LAST),
    SegmentSpec("Young professionals", .2, "An early-career professional who upgrades for productivity and status.",
                traits=T(.6, .45, .55, .5, .45), sensitivities={"price": [.5, .15], "novelty": [.6, .2], "brand": [.55, .2]},
                opinion={"t1": [.2, .35]}, activity=[.35, .12], influence=[.3, .2],
                goals=["a reliable phone for work calls", "good camera for travel", "resale value"],
                beliefs=["time matters more than a few thousand rupees", "ecosystem lock-in is a feature", "battery life beats benchmarks"],
                occupations=["software engineer", "consultant", "product manager", "marketing associate"], locations=["Bengaluru", "Mumbai", "Hyderabad", "Gurugram"], age=[28, 3],
                first_names=IN_FIRST, last_names=IN_LAST),
    SegmentSpec("Tech enthusiasts", .14, "A gadget enthusiast who reads spec sheets and posts hot takes.",
                traits=T(.9, .3, .85, .4, .6), sensitivities={"price": [.3, .15], "novelty": [.95, .05], "brand": [.4, .2]},
                opinion={"t1": [.65, .2]}, activity=[.6, .1], influence=[.55, .2],
                goals=["be first to try new hardware", "share benchmark results", "shape what friends buy"],
                beliefs=["innovation justifies the premium", "mid-range phones cut too many corners", "early adopters drive the market"],
                occupations=["hardware blogger", "developer", "reviewer", "gaming streamer"], locations=["Bengaluru", "Delhi", "Pune"], age=[26, 4],
                first_names=IN_FIRST, last_names=IN_LAST),
    SegmentSpec("Price-sensitive families", .22, "A household budget-keeper who buys one phone for the long haul.",
                traits=T(.35, .65, .35, .65, .55), sensitivities={"price": [.95, .05], "novelty": [.2, .1], "brand": [.4, .2]},
                opinion={"t1": [-.6, .25]}, activity=[.22, .1], influence=[.2, .15],
                goals=["spend as little as possible", "a phone that lasts five years", "easy repairs nearby"],
                beliefs=["a phone is a tool, not a status symbol", "never pay full price", "trust relatives' recommendations"],
                occupations=["shopkeeper", "teacher", "government clerk", "small-business owner"], locations=["Lucknow", "Jaipur", "Nagpur", "Patna"], age=[41, 7],
                first_names=IN_FIRST, last_names=IN_LAST),
    SegmentSpec("Brand loyalists", .14, "A long-time user of the brand who defends it in conversations.",
                traits=T(.35, .55, .55, .5, .85), sensitivities={"price": [.35, .15], "novelty": [.4, .2], "brand": [.95, .05]},
                opinion={"t1": [.55, .25]}, activity=[.38, .12], influence=[.4, .2],
                goals=["stay inside the ecosystem", "defend the brand's reputation", "get the new colour first"],
                beliefs=["the brand has never let me down", "competitors copy us", "service network matters"],
                occupations=["banker", "doctor", "business owner", "architect"], locations=["Mumbai", "Delhi", "Ahmedabad", "Chandigarh"], age=[36, 6],
                first_names=IN_FIRST, last_names=IN_LAST),
    SegmentSpec("Value-seeking switchers", .08, "A comparison shopper who switches brands for the better deal.",
                traits=T(.7, .35, .5, .45, .3), sensitivities={"price": [.75, .1], "novelty": [.5, .2], "brand": [.15, .1]},
                opinion={"t1": [-.05, .4]}, activity=[.4, .12], influence=[.35, .2],
                goals=["maximise specs per rupee", "catch sale windows", "switch if a rival undercuts"],
                beliefs=["brands are interchangeable", "discounts always come", "spec sheets don't lie"],
                occupations=["analyst", "freelancer", "sales executive"], locations=["Indore", "Kochi", "Coimbatore"], age=[30, 5],
                first_names=IN_FIRST, last_names=IN_LAST),
]
TOPIC = Topic("t1", "Upgrade to the new flagship smartphone", "Is the new flagship worth buying at its launch price?",
              "worth buying at launch", "not worth the price")
SPEC = PopulationSpec("Indian smartphone consumers", "Synthetic Indian smartphone consumers reacting to a flagship launch.", [TOPIC], SEGMENTS,
                      ["Segment shares, trait distributions, names and opinions are illustrative simulation assumptions — not survey data.",
                       "The competitor price cut in round 9 is a scripted what-if, not a forecast."], ROUNDS, "demo")


async def main():
    agents = sample(SPEC, N, SEED)
    shock = Shock(9, "A rival brand announces a 20% price cut on its comparable flagship",
                  "Scripted scenario assumption (not real news).", "t1",
                  [{"segment": "*", "sensitivity": "price", "delta": -0.30}, {"segment": "Brand loyalists", "sensitivity": "brand", "delta": 0.12}], 1.0, True)
    cfg = SimConfig("demo", seed=SEED, rounds=ROUNDS, topics=[TOPIC], shocks=[shock], mode="demo",
                    title="DEMO · Indian smartphone market reacts to a flagship launch")
    run = SimulationRun(agents, cfg)
    await run.run()
    assert run.status == "completed", run.error
    out = {"meta": {"label": "DEMO", "synthetic": True, "title": cfg.title, "seed": SEED, "agents": N, "rounds": ROUNDS,
                    "generator": "anvaya-native, template text, no LLM", "assumptions": SPEC.assumptions},
           "agents": [a.public() for a in agents], "events": run.events}
    path = Path(__file__).resolve().parents[2] / "frontend/public/demo/run.json"
    path.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
    out_dir = path.parent
    # ---- derived DEMO knowledge graph: every node/edge comes from the recorded simulation, nothing is invented
    ags = [a.public() for a in agents]
    an = analytics.analyse_events(run.events, ags, "t1")
    end = run.events[-1]["result"]
    nodes = [{"id": "topic", "label": TOPIC.label, "type": "topic", "description": TOPIC.question, "degree": 0, "mentions": 1, "cluster": 0, "sources": [{"doc": "DEMO simulation"}]},
             {"id": "shock", "label": shock.label, "type": "event", "description": shock.description, "degree": 0, "mentions": 1, "cluster": 0, "sources": [{"doc": "DEMO scenario assumption"}]}]
    edges = [{"source": "shock", "target": "topic", "type": "scripted at round 9", "weight": 3, "evidence": [{"quote": shock.label, "doc": "DEMO scenario assumption"}]}]
    for i, sg in enumerate(an["segments"]):
        sid = f"seg{i}"
        nodes.append({"id": sid, "label": sg["segment"], "type": "segment", "description": f"{sg['n']} simulated agents; mean opinion {sg['start']:+.2f} → {sg['end']:+.2f}", "degree": 0, "mentions": sg["n"], "cluster": i % 6, "sources": [{"doc": "DEMO simulation"}]})
        edges.append({"source": sid, "target": "topic", "type": f"opinion {sg['end']:+.2f}", "weight": max(1, int(abs(sg['end']) * 6)), "evidence": [{"quote": f"mean opinion {sg['start']:+.2f} → {sg['end']:+.2f}", "doc": "DEMO simulation"}]})
        edges.append({"source": "shock", "target": sid, "type": f"shift {sg['shift']:+.2f}", "weight": max(1, int(abs(sg['shift']) * 10)), "evidence": [{"quote": "segment mean change over the run", "doc": "DEMO simulation"}]})
    seg_idx = {sg["segment"]: f"seg{i}" for i, sg in enumerate(an["segments"])}
    for t in an["top_influencers"][:10]:
        nid = f"ag{t['agent']}"
        nodes.append({"id": nid, "label": t["name"], "type": "agent", "description": f"Influence score {t['score']:.2f} (PageRank over who moved whose opinion)", "degree": 0, "mentions": 1, "cluster": 0, "sources": [{"doc": "DEMO simulation"}]})
        edges.append({"source": nid, "target": seg_idx[t["segment"]], "type": "member of", "weight": 2, "evidence": [{"quote": "influence ranking", "doc": "DEMO simulation"}]})
        edges.append({"source": nid, "target": "topic", "type": "influences opinion", "weight": max(1, int(t["score"] * 6)), "evidence": [{"quote": "top-10 influence score", "doc": "DEMO simulation"}]})
    deg = {}
    for e in edges:
        deg[e["source"]] = deg.get(e["source"], 0) + e["weight"]; deg[e["target"]] = deg.get(e["target"], 0) + e["weight"]
    for n in nodes: n["degree"] = deg.get(n["id"], 0)
    (out_dir / "graph.json").write_text(json.dumps({"nodes": nodes, "edges": edges, "method": "derived from the DEMO simulation", "synthetic": True}, ensure_ascii=False))

    # ---- DEMO scenarios: paired Monte Carlo (offline engine, no LLM)
    pop = {"spec": SPEC.to_dict(), "agents": [asdict(a) for a in sample(SPEC, N, SEED)]}
    optimistic = {"round": 9, "label": "Launch bundle: trade-in + EMI offer for students and families", "description": "Scripted assumption.", "topic": "t1", "reach": 1.0, "assumption": True,
                  "effects": [{"segment": "Students", "sensitivity": "price", "delta": 0.25}, {"segment": "Price-sensitive families", "sensitivity": "price", "delta": 0.22}]}
    pess = shock.to_dict()
    seeds = list(range(101, 113))

    async def mc():
        base = await scen.monte_carlo(pop, [], ROUNDS, seeds)
        out = []
        for name, kind, prompt, sh in [("Baseline", "baseline", "No external change.", []), ("Rival cuts price 20%", "pessimistic", shock.label, [pess]), ("Student & family bundle", "optimistic", optimistic["label"], [optimistic])]:
            runs = base if not sh else await scen.monte_carlo(pop, sh, ROUNDS, seeds)
            out.append({"id": kind, "name": name, "kind": kind, "prompt": prompt, "shocks": sh, "assumptions": ["Effect sizes are scripted DEMO assumptions, not estimates."] if sh else [], "status": "complete", "interpretation": "scripted",
                        "results": {"summary": scen.summarise_runs(runs), "baseline_summary": scen.summarise_runs(base), "comparison": scen.compare(base, runs) if sh else None, "replicates": len(seeds),
                                    "sensitivity": (await scen.sensitivity(pop, sh, ROUNDS, seeds[:6])) if sh else None}})
        return out, base
    scenarios, base_runs = await mc()
    (out_dir / "scenarios.json").write_text(json.dumps({"synthetic": True, "scenarios": scenarios}, ensure_ascii=False))

    # ---- DEMO report (offline builder, no LLM)
    rctx = {"analysis": an}
    an["final"]["rounds"] = ROUNDS
    recs = decisions.heuristic_recommendations(rctx)
    segs = [{"name": sg.name, "share": sg.share} for sg in SEGMENTS]
    ctx = {"project": {"name": "DEMO · Indian smartphone market", "situation": "Synthetic demonstration: a flagship smartphone launches in India; at round 9 a rival announces a 20% price cut (scripted).", "objectives": "Show how opinion forms, spreads and shifts in a simulated society."},
           "documents": [], "knowledge": None, "analysis": an, "methodology": analytics.select_methods("How will consumers react if a competitor cuts prices 20%?", False, False), "monte_carlo": scen.summarise_runs(base_runs),
           "recommendations": recs, "population": {"n": N, "segments": segs, "assumptions": SPEC.assumptions, "basis": "demo"},
           "scenarios": [{"name": x["name"], "kind": x["kind"], "prompt": x["prompt"], "assumptions": x["assumptions"], "comparison": x["results"]["comparison"]} for x in scenarios if x["results"]["comparison"]],
           "usage": None, "engine": "anvaya-native", "mode": "DEMO", "llm_text": False, "assumptions": SPEC.assumptions}
    rep = await reports.build_report(None, ctx)
    (out_dir / "report.json").write_text(json.dumps({"report": rep, "recommendations": recs, "analysis": an, "synthetic": True}, ensure_ascii=False))
    from collections import Counter
    print(len(run.events), "events", path.stat().st_size // 1024, "KB", dict(Counter(e["type"] for e in run.events)))
    for e in [x for x in run.events if x["type"] == "round_end"][::4]:
        r = e["result"]; print(e["round"], r["mean_opinion"], r["polarisation"], r["groups"], r["max_cascade"], r["support"], r["neutral"], r["oppose"])


asyncio.run(main())
