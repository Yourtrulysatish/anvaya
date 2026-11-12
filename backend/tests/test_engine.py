import asyncio
import json

from anvaya.sim.engine import Shock, SimConfig
from anvaya.sim.runner import SimulationRun
from tests.conftest import make_agents


def run_sim(seed=3, rounds=8, n=60, shocks=None):
    spec, agents = make_agents(n, 1)
    cfg = SimConfig("s", seed=seed, rounds=rounds, topics=spec.topics, shocks=shocks or [], mode="native")
    r = SimulationRun(agents, cfg)
    asyncio.run(r.run())
    return r


def test_deterministic_for_same_seed():
    a, b = run_sim(), run_sim()
    strip = lambda evs: [{k: v for k, v in e.items() if k != "timestamp"} for e in evs]
    assert json.dumps(strip(a.events), sort_keys=True) == json.dumps(strip(b.events), sort_keys=True)
    assert json.dumps(strip(run_sim(seed=4).events), sort_keys=True) != json.dumps(strip(a.events), sort_keys=True)


def test_event_invariants():
    r = run_sim(shocks=[Shock(4, "Shock", effects=[{"segment": "*", "sensitivity": "cost", "delta": -0.3}])])
    assert r.status == "completed", r.error
    ev = r.events
    assert [e["seq"] for e in ev] == list(range(len(ev)))                     # ordered, gap-free
    assert len({e["id"] for e in ev}) == len(ev)                              # unique ids
    assert ev[0]["type"] == "sim_start" and ev[-1]["type"] == "sim_end"
    n = len(r.engine.agents)
    for e in ev:
        for a in e["agents"] + [x for x in (e["source_agent"], e["target_agent"]) if x is not None]:
            assert 0 <= a < n
        if e["type"] in ("post", "reply", "agree", "disagree", "share"):
            assert e["reason"] and e["content"] and e["content_source"] == "template"   # every interaction has a reason; text is labelled
            assert e["source_agent"] is not None
        if e["type"] in ("agree", "disagree", "reply", "share"):
            assert e["target_agent"] is not None
    rounds = [e["round"] for e in ev]
    assert rounds == sorted(rounds)


def test_opinions_stay_bounded_and_events_match_state():
    r = run_sim(rounds=10)
    final = r.events[-1]["result"]["final_opinions"]
    assert all(-1 <= v <= 1 for v in final.values())
    # replaying state_changes reproduces final opinions exactly
    ops = {a.id: a.initial_opinions["t1"] for a in r.engine.agents.values()}
    for e in r.events:
        for k, c in (e["state_changes"].get("opinion") or {}).items():
            ops[int(k)] = c["to"]
    for k, v in final.items():
        assert abs(ops[int(k)] - v) < 1e-3


def test_shock_changes_outcome_and_is_recorded():
    base = run_sim(rounds=10)
    shocked = run_sim(rounds=10, shocks=[Shock(3, "Cost shock", effects=[{"segment": "*", "sensitivity": "cost", "delta": -0.5}])])
    ext = [e for e in shocked.events if e["type"] == "external_event"]
    assert len(ext) == 1 and ext[0]["result"]["assumption"] is True and ext[0]["content_source"] == "external"
    assert shocked.events[-1]["result"]["mean_opinion"] < base.events[-1]["result"]["mean_opinion"]


def test_groups_and_cascades_only_from_computed_state():
    r = run_sim(rounds=12)
    joins = [e for e in r.events if e["type"] == "join_group"]
    assert joins and all("label propagation" in e["reason"] for e in joins)
    for e in r.events:
        if e["type"] == "cascade":
            assert e["result"]["size"] >= 4


def test_pause_stop_semantics():
    async def go():
        spec, agents = make_agents(40, 1)
        cfg = SimConfig("p", seed=1, rounds=30, topics=spec.topics)
        r = SimulationRun(agents, cfg, round_delay=0.02)
        t = asyncio.create_task(r.run())
        await asyncio.sleep(0.15)
        r.pause()
        await asyncio.sleep(0.1)
        n = len(r.events) + len(r._pending)
        await asyncio.sleep(0.3)
        assert len(r.events) + len(r._pending) <= n + 3           # no progress while paused (pause marker only)
        assert r.status == "paused"
        r.resume(); await asyncio.sleep(0.1)
        r.stop(); await t
        return r
    r = asyncio.run(go())
    assert r.status == "stopped" and r.events[-1]["type"] == "sim_end"
    types = [e["type"] for e in r.events]
    assert "sim_pause" in types and "sim_resume" in types


def test_event_payloads_are_json_stable():
    """In-memory events must equal their JSON round-trip (string keys), so analysis is identical live vs. from the database."""
    r = run_sim(rounds=6)
    assert json.loads(json.dumps(r.events)) == r.events
