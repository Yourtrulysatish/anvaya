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
    from collections import Counter
    print(len(run.events), "events", path.stat().st_size // 1024, "KB", dict(Counter(e["type"] for e in run.events)))
    for e in [x for x in run.events if x["type"] == "round_end"][::4]:
        r = e["result"]; print(e["round"], r["mean_opinion"], r["polarisation"], r["groups"], r["max_cascade"], r["support"], r["neutral"], r["oppose"])


asyncio.run(main())
