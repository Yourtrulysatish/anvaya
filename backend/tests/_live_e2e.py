"""Manual end-to-end run against a running backend with a real FreeModel key (not part of CI).

    uvicorn anvaya.main:app --port 8000 &
    PYTHONPATH=. python tests/_live_e2e.py
"""
import json
import sys
import time

import httpx

B = "http://127.0.0.1:8000/api"
c = httpx.Client(timeout=300)


def wait(h, jid):
    while True:
        j = c.get(f"{B}/jobs/{jid}", headers=h).json()
        if j["status"] != "running":
            return j
        print("   ·", j["message"], round(j["progress"], 2)); time.sleep(3)


r = c.post(f"{B}/auth/register", json={"email": f"e2e{int(time.time())}@example.com", "password": "e2e-password-123"}).json()
h = {"Authorization": f"Bearer {r['token']}"}
print("health", c.get(f"{B}/health").json())
st = c.get(f"{B}/settings", headers=h).json()
print("models:", len(st["models"]), {k: v.get("model") for k, v in st["assignments"].items()})
print("test:", c.post(f"{B}/settings/test", headers=h).json())

pid = c.post(f"{B}/projects", json={"name": "Smartphone launch", "situation": "A flagship phone launches in India at a premium price while a rival is rumoured to cut prices.",
                                    "objectives": "Understand how consumer opinion forms and how a competitor price cut would change it."}, headers=h).json()["id"]
c.post(f"{B}/projects/{pid}/documents/text", json={"name": "Market note", "text": "India's smartphone market shipped about 150 million units in 2024 according to analyst estimates. "
      "Premium devices above Rs 45,000 account for roughly 8% of shipments. Samsung and Apple lead the premium segment while Xiaomi and Realme dominate below Rs 20,000. "
      "Student buyers are highly price sensitive and rely on YouTube reviews. Analysts expect EMI financing to keep growing in 2025. "
      "Another report claims premium devices account for 12% of shipments in 2024."}, headers=h)
j = wait(h, c.post(f"{B}/projects/{pid}/analyse", json={"use_llm": True}, headers=h).json()["id"])
print("analyse:", j["status"], j.get("result"), j.get("error"))
kb = c.get(f"{B}/projects/{pid}/graph", headers=h).json()
print("graph nodes", len(kb["nodes"]), "edges", len(kb["edges"]), "facts", len(kb["facts"]), "contradictions", len(kb["contradictions"]))
print("   contradiction:", json.dumps(kb["contradictions"][:1])[:300])

j = wait(h, c.post(f"{B}/projects/{pid}/populations/generate", json={"description": "Simulate 60 Indian smartphone consumers, including students, professionals, technology enthusiasts, price-sensitive customers and brand loyalists.", "n": 60}, headers=h).json()["id"])
print("population:", j["status"], j.get("result"), j.get("error"))
pop_id = j["result"]["population_id"]
pop = c.get(f"{B}/projects/{pid}/populations/{pop_id}", headers=h).json()
print("segments:", [(s["name"], s["count"]) for s in pop["segments"]], "enriched", pop["enriched"])
print("sample persona:", pop["agents"][3]["name"], "|", pop["agents"][3]["persona"][:160])

s = c.post(f"{B}/projects/{pid}/simulations", json={"population_id": pop_id, "rounds": 6, "seed": 7, "use_llm": True, "llm_agents_per_round": 4, "budget_calls": 60}, headers=h)
print("sim start:", s.status_code, s.json())
sid = s.json()["id"]
n_events, t0 = 0, time.time()
with c.stream("GET", f"{B}/simulations/{sid}/stream", headers=h) as resp:
    for line in resp.iter_lines():
        if line.startswith("event: end"):
            break
        if line.startswith("data: ") and "[{" in line[:8]:
            n_events += len(json.loads(line[6:]))
print("streamed events:", n_events, "in", round(time.time() - t0), "s")
info = c.get(f"{B}/simulations/{sid}", headers=h).json()
print("sim status:", info["status"])
evs = c.get(f"{B}/simulations/{sid}/events", headers=h).json()["events"]
from collections import Counter
print(Counter((e["type"], e["content_source"]) for e in evs if e["type"] in ("post", "reply", "agree", "disagree", "share")))
print("sim_end llm usage:", evs[-1]["result"].get("llm_usage"))
print("warnings:", [e["content"] for e in evs if e["type"] == "error"])
print("interview:", c.post(f"{B}/simulations/{sid}/agents/3/interview", json={"question": "What matters most to you when choosing a phone?"}, headers=h).json())

sc = c.post(f"{B}/projects/{pid}/scenarios", json={"population_id": pop_id, "name": "Rival cuts price 20%", "kind": "pessimistic", "prompt": "What if the main competitor reduces its comparable smartphone price by 20%?", "rounds": 8}, headers=h).json()
print("scenario interp:", sc["interpretation"], json.dumps(sc["shocks"])[:400], sc["assumptions"][:2])
j = wait(h, c.post(f"{B}/scenarios/{sc['id']}/run", json={"replicates": 8}, headers=h).json()["id"])
print("scenario run:", j["status"], j.get("error"))
sc = c.get(f"{B}/projects/{pid}/scenarios", headers=h).json()[0]
print("mean_opinion diff:", sc["results"]["comparison"]["differences"]["mean_opinion"])
rec = c.post(f"{B}/projects/{pid}/recommendations", json={"simulation_id": sid, "scenario_ids": [sc["id"]]}, headers=h).json()
print("recs:", rec["method"], [(r["action"][:80], r["priority"]) for r in rec["recommendations"]])
rp = c.post(f"{B}/projects/{pid}/reports", json={"simulation_id": sid, "scenario_ids": [sc["id"]], "recommendation_id": rec["id"], "monte_carlo_replicates": 6}, headers=h)
print("report:", rp.status_code, len(rp.json()["report"]["sections"]) if rp.status_code == 200 else rp.text[:300])
print("exec summary:", rp.json()["report"]["sections"][0]["blocks"][0]["text"][:500])
print("usage:", c.get(f"{B}/settings", headers=h).json()["usage"])
sys.exit(0)
