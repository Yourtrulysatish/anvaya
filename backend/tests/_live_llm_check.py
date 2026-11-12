"""Manual live check against FreeModel (not part of the unit-test run): python tests/_live_llm_check.py"""
import asyncio
import random
import time
from collections import Counter

from anvaya.llm.provider import provider
from anvaya.sim.engine import Agent, SimConfig, Topic
from anvaya.sim.runner import Budget, SimulationRun


def mk(n):
    topic = Topic("t1", "Upgrade to the new phone", "Is it worth upgrading to the new flagship?", "worth upgrading", "not worth it")
    segs = ["Students", "Professionals", "Enthusiasts", "Budget shoppers", "Brand loyalists"]
    agents = []
    for i in range(n):
        r = random.Random(i)
        s = segs[i % 5]
        agents.append(Agent(
            i, f"{['Asha', 'Ravi', 'Meera', 'Karan', 'Zoya', 'Dev', 'Isha', 'Nikhil'][i % 8]} {['Rao', 'Shah', 'Iyer', 'Khan', 'Das'][i % 5]}",
            s, f"A {s.lower()} consumer in India",
            traits={k: r.random() for k in ["openness", "agreeableness", "conformity", "extraversion", "stubbornness"]},
            sensitivities={"price": r.random()}, activity=0.3 + r.random() * 0.4, influence=r.random() ** 2,
            goals=["get good value"], beliefs=["reviews matter"], opinions={"t1": r.gauss(0, 0.4)}, salience={"t1": 1}))
    return topic, agents


async def main():
    topic, agents = mk(24)
    cfg = SimConfig("llmtest", seed=2, rounds=3, topics=[topic], llm_agents_per_round=4)
    run = SimulationRun(agents, cfg, provider=provider, use_llm=True, budget=Budget(max_calls=20, provider=provider))
    t = time.time()
    await run.run()
    print("time", round(time.time() - t, 1), run.status, run.error)
    print(Counter((e["type"], e["content_source"]) for e in run.events if e["type"] in ("post", "reply", "agree", "disagree", "share")))
    for e in run.events:
        if e["type"] in ("post", "reply", "disagree") and e["content_source"] == "llm":
            print(e["round"], e["type"], e["result"].get("decided_by"), "|", e["content"], "|", e["reason"][:80])
    print([e["content"] for e in run.events if e["type"] == "error"])
    print(provider.session_usage)


asyncio.run(main())
