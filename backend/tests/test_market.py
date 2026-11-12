import asyncio
import json
import random

import pytest

from anvaya.sim.engine import Agent, SimConfig, Topic
from anvaya.sim.market import ACTIVE, STATES, Market, merge_spec
from anvaya.sim.runner import SimulationRun

TOPIC = Topic("t1", "Adopt Focal", "q", "adopt", "reject")


def pop(n=80, seed=1):
    r = random.Random(seed)
    ag = []
    for i in range(n):
        ag.append(Agent(i, f"C{i}", "Consumer · General", "p", traits={k: r.random() for k in ("openness", "agreeableness", "conformity", "extraversion", "stubbornness")},
                        sensitivities={"price": r.random(), "loyalty": r.random(), "novelty": r.random(), "social": r.random()}, activity=.4, influence=r.random() * .5,
                        opinions={"t1": r.gauss(0.15, .25)}, salience={"t1": 1.0}))
    ag.append(Agent(n, "Store A", "Retailer · Store A", "r", traits={"stubbornness": .5}, opinions={"t1": 0.2}, activity=.2, influence=.3, salience={"t1": 1.0}))
    ag.append(Agent(n + 1, "Store B", "Retailer · Store B", "r", traits={"stubbornness": .5}, opinions={"t1": -0.6}, activity=.2, influence=.3, salience={"t1": 1.0}))
    ag.append(Agent(n + 2, "BrandX", "Competitor · BrandX", "c", traits={"stubbornness": .8}, opinions={"t1": -0.6}, activity=.2, influence=.3, salience={"t1": 1.0}))
    return ag


SPEC = {"focal": "Focal", "brands": [{"name": "Focal", "price": 1.0, "quality": 0.7}, {"name": "BrandX", "price": 1.1, "quality": 0.7}, {"name": "House", "price": 0.7, "quality": 0.4}],
        "retailers": {"Store A": {"initially_listed": True}, "Store B": {"initially_listed": False, "min_stance": 9}},
        "competitors": {"BrandX": {"agent": "BrandX", "budget": 2, "cost": 1, "trigger": 0.03, "discount": 0.2, "duration": 2}},
        "segment_brand_shares": {"Consumer · General": {"BrandX": 0.5, "House": 0.5}}, "segment_store_shares": {"Consumer · General": {"Store A": 0.5, "Store B": 0.5}},
        "marketing": [{"round": 2, "reach": 0.5, "rounds": 3}], "taste_fit": {"Consumer · General": 0.7}}


def run(spec=SPEC, rounds=14, seed=3, n=80):
    cfg = SimConfig("m", seed=seed, rounds=rounds, topics=[TOPIC], market=spec)
    r = SimulationRun(pop(n), cfg)
    asyncio.run(r.run())
    assert r.status == "completed", r.error
    return r


def test_deterministic_and_json_stable():
    a, b = run(), run()
    strip = lambda evs: [{k: v for k, v in e.items() if k != "timestamp"} for e in evs]
    assert strip(a.events) == strip(b.events)
    assert json.loads(json.dumps(a.events)) == a.events


def test_funnel_is_valid_and_reported_every_round():
    r = run()
    rounds = [e for e in r.events if e["type"] == "round_end"]
    assert all("market" in e["result"] for e in rounds)
    for e in rounds:
        f = e["result"]["market"]["funnel"]
        assert set(f) == set(STATES) and sum(f.values()) == 80
    aw = [e["result"]["market"]["awareness"] for e in rounds]
    assert aw == sorted(aw) and aw[-1] > aw[0]                      # awareness never decreases (unaware -> aware is one-way)
    end = r.events[-1]["result"]["market"]
    assert abs(sum(end["share_cumulative"].values()) - 1) < 1e-3


def test_unlisted_store_never_sells_focal_and_listing_requires_conditions():
    r = run()
    m = r.market
    assert m.store_focal["Store B"] == 0 and m.listed["Store B"] is False       # stance threshold 9 can never be met
    assert m.store_focal["Store A"] > 0
    assert not [e for e in r.events if e["type"] == "listing_decision" and e["result"]["retailer"] == "Store B"]


def test_listing_decision_event_when_conditions_met():
    spec = json.loads(json.dumps(SPEC)); spec["retailers"]["Store B"] = {"initially_listed": False, "min_stance": -1.0, "min_demand": 0.0}
    r = run(spec)
    ev = [e for e in r.events if e["type"] == "listing_decision" and e["result"]["retailer"] == "Store B" and e["result"]["listed"]]
    assert ev and "stance" in ev[0]["reason"] and ev[0]["source_agent"] == 81


def test_marketing_raises_awareness():
    none = json.loads(json.dumps(SPEC)); none["marketing"] = []
    boosted = json.loads(json.dumps(SPEC)); boosted["marketing"] = [{"round": 1, "reach": 0.8, "rounds": 6}]
    a = sum(run(none, 8, s).market.snapshot(8)["awareness"] for s in range(1, 5))
    b = sum(run(boosted, 8, s).market.snapshot(8)["awareness"] for s in range(1, 5))
    assert b > a


def test_competitor_promotion_is_budget_limited_and_explained():
    r = run(rounds=20)
    acts = [e for e in r.events if e["type"] == "competitor_action"]
    assert 1 <= len(acts) <= 2                                       # budget 2, cost 1
    assert all("budget left" in e["reason"] and e["source_agent"] == 82 for e in acts)


def test_price_lowers_focal_choice_probability():
    cfg = SimConfig("m", seed=1, rounds=1, topics=[TOPIC], market=SPEC)
    run_ = SimulationRun(pop(40), cfg); m = run_.market
    i = next(i for i in m.cons if m.store[i] == "Store A")
    m.state[i] = "considering"
    low = m.choice_probs(i, 1)["Focal"]
    m.brands["Focal"]["price"] = 2.0
    assert m.choice_probs(i, 1)["Focal"] < low
    m.state[i] = "rejecter"
    assert "Focal" not in m.choice_probs(i, 1)                       # rejecters / unaware never choose the focal brand


def test_merge_spec_overrides_nested():
    s = merge_spec(SPEC, {"retailers": {"Store B": {"initially_listed": True}}, "bass_q": 0.1})
    assert s["retailers"]["Store B"]["initially_listed"] is True and s["retailers"]["Store A"]["initially_listed"] is True and s["bass_q"] == 0.1


def test_invalid_spec_rejected():
    with pytest.raises(ValueError):
        Market(SimulationRun(pop(10), SimConfig("x", topics=[TOPIC])).engine, {"focal": "Nope", "brands": [{"name": "A", "price": 1}]})


def test_negotiated_listing_and_eligibility_start():
    spec = json.loads(json.dumps(SPEC))
    spec["retailers"]["Store B"] = {"initially_listed": False, "min_stance": 9, "list_at": 5}
    r = run(spec, 8)
    ev = [e for e in r.events if e["type"] == "listing_decision" and e["result"]["retailer"] == "Store B"]
    assert len(ev) == 1 and ev[0]["round"] == 5 and ev[0]["result"]["negotiated"] and "scenario assumption" in ev[0]["reason"]
    late = json.loads(json.dumps(SPEC)); late["retailers"]["Store B"] = {"initially_listed": False, "min_stance": -1.0, "min_demand": 0.0, "eval_from": 9}
    r2 = run(late, 8)
    assert not [e for e in r2.events if e["type"] == "listing_decision" and e["result"]["retailer"] == "Store B"]   # not yet approached within 8 rounds
