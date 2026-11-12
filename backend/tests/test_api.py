import time

import pytest
from fastapi.testclient import TestClient

from anvaya.api import RUNS, create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def auth(c, email="u1@example.com"):
    r = c.post("/api/auth/register", json={"email": email, "password": "a-long-password"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def wait_job(c, h, jid, timeout=30):
    t = time.time()
    while time.time() - t < timeout:
        j = c.get(f"/api/jobs/{jid}", headers=h).json()
        if j["status"] != "running":
            return j
        time.sleep(0.1)
    raise AssertionError("job timeout")


def test_requires_auth_and_isolates_users(client):
    assert client.get("/api/projects").status_code == 401
    a, b = auth(client, "a@example.com"), auth(client, "b@example.com")
    pid = client.post("/api/projects", json={"name": "Mine"}, headers=a).json()["id"]
    assert client.get(f"/api/projects/{pid}", headers=b).status_code == 404
    assert client.delete(f"/api/projects/{pid}", headers=b).status_code == 404
    assert client.get(f"/api/projects/{pid}", headers=a).status_code == 200


def test_cors_allows_only_configured_origin(client):
    ok = client.options("/api/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    bad = client.options("/api/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


def test_upload_rules(client):
    h = auth(client)
    pid = client.post("/api/projects", json={"name": "P"}, headers=h).json()["id"]
    assert client.post(f"/api/projects/{pid}/documents", files={"file": ("x.exe", b"MZ", "application/octet-stream")}, headers=h).status_code == 400
    assert client.post(f"/api/projects/{pid}/documents", files={"file": ("fake.pdf", b"nope", "application/pdf")}, headers=h).status_code == 400
    ok = client.post(f"/api/projects/{pid}/documents", files={"file": ("d.csv", b"month,sales\n1,10\n2,12\n3,15\n4,15\n5,19\n6,22\n", "text/csv")}, headers=h)
    assert ok.status_code == 200 and ok.json()["tabular"] is True
    assert client.post(f"/api/projects/{pid}/documents/url", json={"url": "http://127.0.0.1:1/"}, headers=h).status_code == 400


def test_settings_never_expose_key(client):
    h = auth(client)
    body = client.get("/api/settings", headers=h).text
    assert "FREEMODEL_API_KEY" not in body and "fm_" not in body
    assert client.get("/api/health").json()["llm_configured"] is False


def test_full_offline_pipeline(client):
    h = auth(client)
    pid = client.post("/api/projects", json={"name": "Transit", "situation": "A city raises transit fares by 15%.", "objectives": "Understand rider reaction"}, headers=h).json()["id"]
    client.post(f"/api/projects/{pid}/documents/text", json={"name": "brief", "text": "City Transit Authority plans to raise fares by 15% in 2026. City Transit Authority serves Riverside District. Riders Union opposes the City Transit Authority plan. Riders Union says ridership fell in 2024."}, headers=h)
    j = client.post(f"/api/projects/{pid}/analyse", json={"use_llm": False}, headers=h).json()
    assert wait_job(client, h, j["id"])["status"] == "done"
    g = client.get(f"/api/projects/{pid}/graph", headers=h).json()
    assert g["nodes"] and g["method"].startswith("heuristic")

    j = client.post(f"/api/projects/{pid}/populations/generate", json={"description": "300 transit riders and commuters", "n": 60, "use_llm": False}, headers=h).json()
    res = wait_job(client, h, j["id"]); assert res["status"] == "done", res
    pop_id = res["result"]["population_id"]
    pop = client.get(f"/api/projects/{pid}/populations/{pop_id}", headers=h).json()
    assert pop["basis"] == "heuristic" and pop["n"] == 60 and pop["warnings"]
    assert all(a["attributes_basis"] == "assumption" for a in pop["agents"])

    # edit a persona and remove an agent
    a0 = pop["agents"][0]
    r = client.put(f"/api/projects/{pid}/populations/{pop_id}", json={"agents": [{"id": a0["id"], "name": "Renamed Rider", "persona": "edited", "goals": ["x"], "beliefs": ["y"], "activity": 0.5, "influence": 0.5, "opinions": {"t1": 0.9}, "traits": {}}], "remove": [1]}, headers=h)
    assert r.status_code == 200 and r.json()["n"] == 59
    pop = client.get(f"/api/projects/{pid}/populations/{pop_id}", headers=h).json()
    assert pop["agents"][0]["name"] == "Renamed Rider" and pop["agents"][0]["attributes_basis"] == "user"

    s = client.post(f"/api/projects/{pid}/simulations", json={"population_id": pop_id, "rounds": 8, "seed": 5}, headers=h)
    assert s.status_code == 200, s.text
    sid = s.json()["id"]
    for _ in range(100):
        info = client.get(f"/api/simulations/{sid}", headers=h).json()
        if info["status"] in ("completed", "failed", "stopped"): break
        time.sleep(0.1)
    assert info["status"] == "completed", info
    evs = client.get(f"/api/simulations/{sid}/events", headers=h).json()["events"]
    assert evs[0]["type"] == "sim_start" and evs[-1]["type"] == "sim_end"
    # SSE replay: complete stream of a finished run, resumable from Last-Event-ID
    with client.stream("GET", f"/api/simulations/{sid}/stream?after=-1", headers=h) as resp:
        text = "".join(resp.iter_text())
    assert "event: events" in text and "event: end" in text
    mid = evs[len(evs) // 2]["seq"]
    with client.stream("GET", f"/api/simulations/{sid}/stream", headers={**h, "Last-Event-ID": str(mid)}) as resp:
        text2 = "".join(resp.iter_text())
    assert f'"seq":{mid},' not in text2 and f'"seq":{mid + 1},' in text2
    an = client.get(f"/api/simulations/{sid}/analysis", headers=h).json()
    assert an["trajectory"] and an["segments"]

    sc = client.post(f"/api/projects/{pid}/scenarios", json={"population_id": pop_id, "name": "Competitor", "kind": "alternative", "prompt": "What if a rival service cuts its price by 20%?", "rounds": 8}, headers=h)
    assert sc.status_code == 200, sc.text
    assert sc.json()["interpretation"] == "keyword-fallback" and sc.json()["shocks"] and sc.json()["assumptions"]
    j = client.post(f"/api/scenarios/{sc.json()['id']}/run", json={"replicates": 4, "sensitivity": True, "visible_run": True}, headers=h).json()
    res = wait_job(client, h, j["id"], 60); assert res["status"] == "done", res
    sc2 = client.get(f"/api/projects/{pid}/scenarios", headers=h).json()[0]
    cmp_ = sc2["results"]["comparison"]
    assert cmp_["pairs"] == 4 and "mean_opinion" in cmp_["differences"] and "uncertainty" in cmp_
    assert len(sc2["results"]["sensitivity"]) == 5

    rec = client.post(f"/api/projects/{pid}/recommendations", json={"simulation_id": sid, "scenario_ids": [sc2["id"]]}, headers=h).json()
    assert rec["method"].startswith("heuristic") and all(r["kind"] == "RECOMMENDATION" for r in rec["recommendations"])
    rp = client.post(f"/api/projects/{pid}/reports", json={"simulation_id": sid, "scenario_ids": [sc2["id"]], "recommendation_id": rec["id"], "monte_carlo_replicates": 3}, headers=h)
    assert rp.status_code == 200, rp.text
    rid = rp.json()["id"]
    secs = rp.json()["report"]["sections"]
    assert [s["title"] for s in secs][:3] == ["Executive summary", "Situation overview", "Research objectives"] and len(secs) == 15
    kinds = {b["kind"] for s in secs for b in s["blocks"]}
    assert kinds <= {"FACT", "ANALYSIS", "ESTIMATE", "SIMULATION", "RECOMMENDATION"} and {"SIMULATION", "FACT"} <= kinds
    md = client.get(f"/api/reports/{rid}/export?format=md", headers=h)
    assert md.status_code == 200 and "[SIMULATION]" in md.text and "not predictions" in md.text
    pdf = client.get(f"/api/reports/{rid}/export?format=pdf", headers=h)
    assert pdf.content[:4] == b"%PDF"
    for part in ("events", "metrics", "agents"):
        c = client.get(f"/api/reports/{rid}/export?format=csv&part={part}", headers=h)
        assert c.status_code == 200 and "," in c.text.splitlines()[0]


def test_mirofish_import_endpoint(client):
    from tests.test_misc import LINES
    h = auth(client)
    pid = client.post("/api/projects", json={"name": "MF"}, headers=h).json()["id"]
    r = client.post(f"/api/projects/{pid}/import/mirofish", files={"file": ("actions.jsonl", "\n".join(LINES).encode(), "application/json")}, data={"platform": "twitter"}, headers=h)
    assert r.status_code == 200, r.text
    sim = client.get(f"/api/simulations/{r.json()['id']}", headers=h).json()
    assert sim["mode"] == "mirofish" and sim["label"].startswith("IMPORTED")


def test_rate_limit_on_auth(client):
    codes = [client.post("/api/auth/login", json={"email": "x@y.zz", "password": "nope"}).status_code for _ in range(16)]
    assert 429 in codes


def test_import_spec_named_agents_fixed_counts_and_explicit_shocks(client):
    h = auth(client)
    pid = client.post("/api/projects", json={"name": "Spec"}, headers=h).json()["id"]
    t = {"id": "t1", "label": "Accept the product", "question": "q", "pos_label": "accept", "neg_label": "reject"}
    seg = lambda name, **kw: {"name": name, "share": 0.5, "description": name, "sensitivities": {"price": [0.5, 0.1]}, "opinion": {"t1": [0.0, 0.2]}, **kw}
    spec = {"title": "S", "description": "d", "topics": [t], "segments": [seg("Consumers"), seg("Retailers", count=3, fixed_names=["Alpha Mart", "Beta Shop", "Gamma Store"])], "assumptions": ["a"], "basis": "user"}
    j = client.post(f"/api/projects/{pid}/populations/import", json={"spec": spec, "n": 30}, headers=h).json()
    res = wait_job(client, h, j["id"]); assert res["status"] == "done", res
    pop = client.get(f"/api/projects/{pid}/populations/{res['result']['population_id']}", headers=h).json()
    names = [a["name"] for a in pop["agents"] if a["segment"] == "Retailers"]
    assert pop["n"] == 30 and sorted(names) == ["Alpha Mart", "Beta Shop", "Gamma Store"]
    assert client.post(f"/api/projects/{pid}/populations/import", json={"spec": {"title": "x"}}, headers=h).status_code == 422
    sc = client.post(f"/api/projects/{pid}/scenarios", headers=h, json={"population_id": res["result"]["population_id"], "name": "Explicit", "kind": "alternative", "prompt": "x", "rounds": 8,
        "shocks": [{"round": 3, "label": "Price cut", "effects": [{"segment": "Consumers", "sensitivity": "price", "delta": 0.3}, {"segment": "Nope", "delta": 9}]}], "assumptions": ["scripted"]}).json()
    assert sc["interpretation"] == "user-specified" and sc["shocks"][0]["effects"][0]["delta"] == 0.3
    assert sc["shocks"][0]["effects"][1] == {"segment": "*", "sensitivity": None, "delta": 0.6}   # unknown segment -> '*', delta clamped
