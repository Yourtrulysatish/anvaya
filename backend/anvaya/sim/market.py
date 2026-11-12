"""Market layer: purchase funnel, brand choice, retailer listing, competitor promotions.

Runs on top of the opinion-dynamics Engine. Consumers move through an explicit funnel
    unaware -> aware -> considering -> trial -> repeat -> advocate   (or rejecter)
driven by
  * awareness: Bass-style diffusion (external marketing + word-of-mouth from aware neighbours)
  * consideration: the agent's opinion on the focal-brand topic (from the opinion model) and novelty-seeking
  * purchase: a multinomial-logit brand choice among the brands *available at the agent's store*
      u_b = -beta_price * price_b * price_sensitivity + beta_loyalty * [b == usual brand] * loyalty
            + beta_quality * quality_b * taste_fit + [b == focal] * (beta_opinion * opinion + beta_consider * considered)
    (Guadagni-Little-style loyalty term)
  * retailers list/delist the focal brand from observed demand and their own stance;
    competitors run budget-limited promotions when the focal brand's share crosses their trigger.

Defaults for the (annual) Bass coefficients (p = 0.03, q = 0.38) are the values commonly cited from the Sultan-Farley-Lehmann
meta-analysis of diffusion models (obtained from a secondary source; verify before relying on them). EVERY other number in a
MarketSpec is a simulation assumption unless the caller supplies data. Nothing here is a forecast.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Callable, Optional

STATES = ["unaware", "aware", "considering", "trial", "repeat", "advocate", "rejecter"]
ACTIVE = ("considering", "trial", "repeat", "advocate")

DEFAULTS = {
    "focal": "Vegeta", "consumer_prefix": "Consumer",
    "bass_p": 0.03, "bass_q": 0.38,            # ANNUAL rates (literature defaults); converted to per-round below
    "rounds_per_year": 52,                     # one round ~ one week (assumption)
    "purchase_prob": 0.35,                     # chance a consumer buys seasoning in a round (round ~ a shopping cycle; assumption)
    "beta_price": 2.2, "beta_loyalty": 1.6, "beta_quality": 1.4, "beta_opinion": 1.2, "beta_consider": 0.5,
    "satisfaction_threshold": 0.38, "eval_every": 3, "listing_opinion": 0.0, "listing_demand": 0.12, "delist_after": 3,
    "brands": [], "marketing": [], "segment_brand_shares": {}, "segment_store_shares": {}, "initial_awareness": {}, "taste_fit": {},
    "retailers": {}, "competitors": {},
}


def merge_spec(spec: dict, overrides: Optional[dict]) -> dict:
    out = {**DEFAULTS, **(spec or {})}
    for k, v in (overrides or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def _softmax(us: dict) -> dict:
    m = max(us.values())
    ex = {b: math.exp(u - m) for b, u in us.items()}
    t = sum(ex.values())
    return {b: v / t for b, v in ex.items()}


class Market:
    def __init__(self, engine, spec: dict):
        self.e = engine
        self.spec = merge_spec(spec, None)
        s = self.spec
        self.focal = s["focal"]
        self.brands = {b["name"]: b for b in s["brands"]}
        if self.focal not in self.brands:
            raise ValueError(f"focal brand {self.focal!r} missing from brands")
        self.topic = next(iter(engine.topics))
        rng = engine._rng(0, 99)
        self.rng = rng
        self.cons = [a.id for a in engine.agents.values() if a.segment.startswith(s["consumer_prefix"])]
        self.state = {i: "unaware" for i in self.cons}
        self.usual: dict[int, str] = {}
        self.store: dict[int, str] = {}
        self.last_brand: dict[int, str] = {}
        self.initial_aware: dict[int, bool] = {}     # pre-existing users (e.g. diaspora) who already talk about the brand
        brand_names = list(self.brands)
        for i in self.cons:
            seg = engine.agents[i].segment
            bs = s["segment_brand_shares"].get(seg) or {b: 1.0 for b in brand_names if b != self.focal}
            self.usual[i] = rng.choices(list(bs), [max(0.0, w) for w in bs.values()])[0]
            ss = s["segment_store_shares"].get(seg) or {r: 1.0 for r in s["retailers"]}
            self.store[i] = rng.choices(list(ss), [max(0.0, w) for w in ss.values()])[0] if ss else ""
            if rng.random() < s["initial_awareness"].get(seg, 0.0):
                self.state[i] = "aware"; self.initial_aware[i] = True
        self.retailer_agent = {r: a.id for r in s["retailers"] for a in engine.agents.values() if a.name == r}
        self.listed = {r: bool(cfg.get("initially_listed", False)) for r, cfg in s["retailers"].items()}
        self.low_streak = {r: 0 for r in s["retailers"]}
        self.competitor_agent = {b: a.id for b, cfg in s["competitors"].items() for a in engine.agents.values() if a.name == cfg.get("agent", b)}
        self.budget = {b: cfg.get("budget", 0.0) for b, cfg in s["competitors"].items()}
        self.promo: dict[str, dict] = {}
        self.units = Counter(); self.revenue = Counter(); self.round_units = Counter(); self.store_focal = Counter(); self.store_total = Counter()
        self.tried: set = set()
        self.history: list[dict] = []

    # ------------------------------------------------------------------ helpers
    def _price(self, brand: str, rnd: int) -> float:
        p = self.brands[brand]["price"]
        pr = self.promo.get(brand)
        return p * (1 - pr["discount"]) if pr and pr["until"] >= rnd else p

    def _marketing_reach(self, rnd: int) -> float:
        reach = 0.0
        for m in self.spec["marketing"]:
            if m["round"] <= rnd < m["round"] + int(m.get("rounds", 1)):
                reach = 1 - (1 - reach) * (1 - float(m["reach"]))
        return reach

    def _neighbours(self, i):
        return [j for j, w in self.e.ties[i].items() if w >= 0.2]

    def choice_probs(self, i: int, rnd: int) -> dict:
        """Brand-choice probabilities for consumer i at their store (exposed for tests and explanations)."""
        s, a = self.spec, self.e.agents[i]
        avail = [b for b in self.brands if b != self.focal or (self.listed.get(self.store[i], True) and self.state[i] not in ("unaware", "rejecter"))]
        fit = s["taste_fit"].get(a.segment, 0.5)
        us = {}
        for b in avail:
            br = self.brands[b]
            u = -s["beta_price"] * (self._price(b, rnd) / 1.0) * (0.5 + a.sensitivities.get("price", 0.5))
            u += s["beta_loyalty"] * (1.0 if self.usual[i] == b else 0.0) * (0.4 + a.sensitivities.get("loyalty", 0.5))
            u += s["beta_quality"] * br.get("quality", 0.5) * (fit if b == self.focal else 0.6)
            if b == self.focal:
                u += s["beta_opinion"] * a.opinions.get(self.topic, 0.0) + (s["beta_consider"] if self.state[i] in ACTIVE else 0.0)
            us[b] = u
        return _softmax(us)

    # ------------------------------------------------------------------ one round
    def step(self, rnd: int, emit: Callable, max_events: int = 30) -> dict:
        s, e, rng = self.spec, self.e, self.e._rng(rnd, 4242)
        self.round_units = Counter()
        transitions: list[tuple] = []
        reach = self._marketing_reach(rnd)
        ppy = max(1, s["rounds_per_year"])
        p_ext = 1 - (1 - s["bass_p"]) ** (1 / ppy)         # annual Bass coefficients -> per-round rates
        q_round = s["bass_q"] / ppy

        # 1) awareness (Bass: external marketing + word of mouth from aware neighbours)
        # word of mouth only comes from people actually talking about the product (considering or using it), not from the merely aware
        aware_now = {i for i in self.cons if self.state[i] in ACTIVE or (self.state[i] == "aware" and self.initial_aware.get(i))}
        for i in self.cons:
            if self.state[i] != "unaware":
                continue
            nb = self._neighbours(i)
            frac = sum(1 for j in nb if j in aware_now) / len(nb) if nb else 0.0
            susc = 0.5 + 0.5 * e.agents[i].sensitivities.get("social", 0.5)
            p = 1 - (1 - p_ext) * (1 - reach * susc) * (1 - q_round * frac)
            if rng.random() < p:
                self.state[i] = "aware"

        # 2) consideration / rejection from opinion
        for i in self.cons:
            st, a = self.state[i], e.agents[i]
            op = a.opinions.get(self.topic, 0.0)
            if st == "aware":
                pc = 0.45 / (1 + math.exp(-(3.2 * op + 1.5 * (a.sensitivities.get("novelty", 0.5) - 0.5))))
                if rng.random() < pc:
                    self.state[i] = "considering"
                elif op < -0.5 and rng.random() < 0.08:
                    self.state[i] = "rejecter"
            elif st == "considering" and op < -0.45 and rng.random() < 0.15:
                self.state[i] = "rejecter"

        # 3) purchases (multinomial logit at the agent's store)
        notable = 0
        for i in self.cons:
            if rng.random() > s["purchase_prob"]:
                continue
            probs = self.choice_probs(i, rnd)
            brand = rng.choices(list(probs), list(probs.values()))[0]
            self.units[brand] += 1; self.round_units[brand] += 1; self.revenue[brand] += self._price(brand, rnd)
            store = self.store[i]
            self.store_total[store] += 1
            if brand == self.focal:
                self.store_focal[store] += 1; self.tried.add(i)
            prev = self.state[i]
            new = prev
            if brand == self.focal:
                if prev == "considering":
                    new = "trial"
                elif prev == "trial":
                    fit = s["taste_fit"].get(e.agents[i].segment, 0.5) + rng.gauss(0, 0.12)
                    new = "repeat" if fit >= s["satisfaction_threshold"] else "rejecter"
                elif prev == "repeat":
                    a = e.agents[i]
                    if a.opinions.get(self.topic, 0) > 0.35 and a.traits.get("extraversion", 0.5) > 0.5 and rng.random() < 0.3:
                        new = "advocate"
            self.last_brand[i] = brand
            if new != prev:
                self.state[i] = new
                transitions.append((i, prev, new, probs, store))

        # 4) word of mouth from advocates / rejecters + events (capped)
        for i, prev, new, probs, store in transitions:
            if new not in ("trial", "advocate", "rejecter") or notable >= max_events:
                continue
            notable += 1
            a = e.agents[i]
            changes: dict = {"opinion": {}}
            if new in ("advocate", "rejecter"):
                nudge = 0.05 if new == "advocate" else -0.04
                for j in self._neighbours(i)[:6]:
                    x = e.agents[j].opinions.get(self.topic, 0.0)
                    y = max(-1.0, min(1.0, x + nudge))
                    if abs(y - x) > 1e-9:
                        e.agents[j].opinions[self.topic] = y
                        changes["opinion"][str(j)] = {"topic": self.topic, "from": round(x, 3), "to": round(y, 3)}
                if new == "rejecter":
                    x = a.opinions.get(self.topic, 0.0); y = max(-1.0, x - 0.15)
                    a.opinions[self.topic] = y
                    changes["opinion"][str(i)] = {"topic": self.topic, "from": round(x, 3), "to": round(y, 3)}
            verb = {"trial": f"tried {self.focal} for the first time", "advocate": f"became an advocate of {self.focal}", "rejecter": f"rejected {self.focal} after trying it"}[new]
            emit("funnel_change", source=i, target=self.retailer_agent.get(store), agents=[i] + ([self.retailer_agent[store]] if store in self.retailer_agent else []),
                 topic=self.topic, content=f"{a.name} {verb}", content_source="engine",
                 reason=f"{prev} → {new}; brand-choice probability of {self.focal} {probs.get(self.focal, 0):.2f} at {store or 'their store'}; usual brand {self.usual[i]}",
                 result={"from": prev, "to": new, "store": store, "choice_prob": round(probs.get(self.focal, 0), 3), "usual_brand": self.usual[i]}, state_changes=changes)

        # 5) retailer listing decisions
        for r, cfg in s["retailers"].items():           # negotiated listings (a strategy decision, stated as an assumption)
            if cfg.get("list_at") == rnd and not self.listed[r]:
                self.listed[r] = True; self.low_streak[r] = 0
                rid = self.retailer_agent.get(r)
                emit("listing_decision", source=rid, target=None, agents=[rid] if rid is not None else [], topic=self.topic, content=f"{r} lists {self.focal} (negotiated)",
                     content_source="engine", reason=f"listing agreed under the distribution strategy at round {rnd} (scenario assumption, not an outcome of retailer evaluation)",
                     result={"retailer": r, "listed": True, "negotiated": True}, state_changes={})
        if rnd % s["eval_every"] == 0:
            for r, cfg in s["retailers"].items():
                if rnd < cfg.get("eval_from", 1):
                    continue                                   # not approached yet
                shoppers = [i for i in self.cons if self.store[i] == r]
                if not shoppers:
                    continue
                demand = sum(1 for i in shoppers if self.state[i] in ACTIVE) / len(shoppers)
                rid = self.retailer_agent.get(r)
                stance = e.agents[rid].opinions.get(self.topic, 0.0) if rid is not None else 0.0
                share = self.store_focal[r] / self.store_total[r] if self.store_total[r] else 0.0
                if not self.listed[r]:
                    if stance >= cfg.get("min_stance", s["listing_opinion"]) and demand >= cfg.get("min_demand", s["listing_demand"]):
                        self.listed[r] = True; self.low_streak[r] = 0
                        emit("listing_decision", source=rid, target=None, agents=[rid] if rid is not None else [], topic=self.topic, content=f"{r} lists {self.focal}",
                             content_source="engine", reason=f"stance {stance:+.2f} ≥ {cfg.get('min_stance', s['listing_opinion']):+.2f} and shopper demand {demand:.0%} ≥ {cfg.get('min_demand', s['listing_demand']):.0%}",
                             result={"retailer": r, "listed": True, "stance": round(stance, 3), "demand": round(demand, 3)}, state_changes={})
                else:
                    self.low_streak[r] = self.low_streak[r] + 1 if (share < cfg.get("min_share", 0.02) and stance < 0) else 0
                    if self.low_streak[r] >= s["delist_after"] and cfg.get("can_delist", True):
                        self.listed[r] = False
                        emit("listing_decision", source=rid, target=None, agents=[rid] if rid is not None else [], topic=self.topic, content=f"{r} delists {self.focal}",
                             content_source="engine", reason=f"focal share {share:.1%} below {cfg.get('min_share', 0.02):.0%} for {s['delist_after']} reviews with stance {stance:+.2f}",
                             result={"retailer": r, "listed": False, "share": round(share, 3), "stance": round(stance, 3)}, state_changes={})
                        self.low_streak[r] = 0

        # 6) competitor promotions (budget-limited)
        total = sum(self.round_units.values()) or 1
        focal_share = self.round_units[self.focal] / total
        for b, cfg in s["competitors"].items():
            active = self.promo.get(b)
            if active and active["until"] >= rnd:
                continue
            cost = cfg.get("cost", 1.0)
            if focal_share >= cfg.get("trigger", 0.05) and self.budget[b] >= cost:
                self.budget[b] -= cost
                dur = int(cfg.get("duration", 3))
                self.promo[b] = {"until": rnd + dur, "discount": cfg.get("discount", 0.15)}
                cid = self.competitor_agent.get(b)
                emit("competitor_action", source=cid, target=None, agents=[cid] if cid is not None else [], topic=self.topic,
                     content=f"{b} launches a {cfg.get('discount', .15):.0%} promotion for {dur} rounds", content_source="engine",
                     reason=f"{self.focal} share {focal_share:.1%} ≥ trigger {cfg.get('trigger', .05):.0%}; budget left {self.budget[b]:.1f}",
                     result={"brand": b, "discount": cfg.get("discount", .15), "until": rnd + dur, "budget_left": round(self.budget[b], 2)}, state_changes={})

        snap = self.snapshot(rnd, focal_share)
        self.history.append(snap)
        return snap

    def snapshot(self, rnd: int, focal_share: Optional[float] = None) -> dict:
        n = len(self.cons) or 1
        c = Counter(self.state.values())
        total_units = sum(self.units.values()) or 1
        ru = sum(self.round_units.values()) or 1
        return {
            "funnel": {k: c.get(k, 0) for k in STATES}, "awareness": round(1 - c.get("unaware", 0) / n, 4),
            "ever_tried": round(len(self.tried) / n, 4), "repeat_or_advocate": round((c.get("repeat", 0) + c.get("advocate", 0)) / n, 4),
            "share_round": {b: round(self.round_units[b] / ru, 4) for b in self.brands}, "share_cumulative": {b: round(self.units[b] / total_units, 4) for b in self.brands},
            "focal_share_round": round(self.round_units[self.focal] / ru, 4), "focal_units": self.units[self.focal], "focal_revenue": round(self.revenue[self.focal], 3),
            "listed_retailers": sorted(r for r, v in self.listed.items() if v), "listed_count": sum(self.listed.values()),
            "promotions_active": sorted(b for b, p in self.promo.items() if p["until"] >= rnd),
        }
