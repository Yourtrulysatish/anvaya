"""ANVAYA native simulation engine.

A *hybrid cognitive model*: the structure of every interaction (who speaks to whom, agree/disagree, shares, tie changes,
opinion shifts, group formation) is produced by a seeded, inspectable model driven by persona traits, goals, memory,
relationships and the environment. Language is added afterwards by a ContentWriter (an LLM, or deterministic templates in
demo mode) and, optionally, a small set of "deliberating" agents are decided directly by an LLM per round.

Everything is recorded as normalised events; every event carries `reason`, `content_source` and `provenance`.
"""
from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

EVENT_TYPES = [
    "sim_start", "round_start", "external_event", "post", "reply", "agree", "disagree", "share", "cascade",
    "opinion_change", "relationship_change", "join_group", "leave_group", "round_end", "sim_pause", "sim_resume",
    "sim_end", "error",
]


def clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def band(x: float) -> str:
    return "support" if x > 0.33 else "oppose" if x < -0.33 else "neutral"


@dataclass
class Topic:
    id: str
    label: str
    question: str = ""
    pos_label: str = "in favour"
    neg_label: str = "against"


@dataclass
class Agent:
    id: int
    name: str
    segment: str
    persona: str
    age: int = 30
    occupation: str = ""
    location: str = ""
    traits: dict = field(default_factory=dict)        # openness, agreeableness, conformity, extraversion, stubbornness (0..1)
    sensitivities: dict = field(default_factory=dict)  # e.g. price, novelty, trust, social (0..1)
    activity: float = 0.3
    influence: float = 0.3
    goals: list = field(default_factory=list)
    beliefs: list = field(default_factory=list)
    opinions: dict = field(default_factory=dict)       # topic_id -> [-1, 1]
    salience: dict = field(default_factory=dict)       # topic_id -> weight
    sentiment: float = 0.0
    memory: list = field(default_factory=list)         # recent detailed memories
    digest: str = ""                                   # compressed older memory
    group: Optional[int] = None
    attributes_basis: str = "assumption"               # "assumption" | "document" | "user"
    initial_opinions: dict = field(default_factory=dict)

    def public(self) -> dict:
        d = {k: getattr(self, k) for k in ("id", "name", "segment", "persona", "age", "occupation", "location", "traits",
                                           "sensitivities", "activity", "influence", "goals", "beliefs", "attributes_basis")}
        d["opinions"] = {k: round(v, 3) for k, v in self.initial_opinions.items()}
        return d


@dataclass
class Shock:
    round: int
    label: str
    description: str = ""
    topic: str = ""
    effects: list = field(default_factory=list)  # [{segment:"*"|name, sensitivity:"price"|None, delta: float}]
    reach: float = 1.0
    assumption: bool = True

    def to_dict(self):
        return self.__dict__.copy()


@dataclass
class SimConfig:
    simulation_id: str = "sim"
    seed: int = 7
    rounds: int = 20
    topics: list = field(default_factory=list)
    shocks: list = field(default_factory=list)
    max_actions_per_round: int = 400
    llm_agents_per_round: int = 0       # deliberating agents decided by an LLM each round
    mode: str = "native"                # native | demo
    title: str = ""
    description: str = ""


@dataclass
class Post:
    id: str            # event id of the creating event (filled by sink) or temp id
    author: int
    round: int
    topic: str
    stance: float
    strength: float
    text: str = ""
    root: str = ""
    parent: Optional[str] = None
    depth: int = 0
    reach: int = 0


@dataclass
class Intent:
    type: str                 # post | reply | agree | disagree | share | ignore
    source: int
    topic: str
    stance: float             # expressed stance toward topic [-1,1]
    strength: float           # persuasive force 0..1
    target: Optional[int] = None
    post: Optional[Post] = None
    audience: list = field(default_factory=list)
    reason: str = ""
    text: str = ""
    content_source: str = ""
    decided_by: str = "rule"
    shift_override: Optional[float] = None


class Engine:
    def __init__(self, agents: list[Agent], cfg: SimConfig):
        self.cfg = cfg
        self.agents = {a.id: a for a in agents}
        self.topics = {t.id: t for t in cfg.topics}
        self.rng = random.Random(cfg.seed)
        self.ties: dict[int, dict[int, float]] = defaultdict(dict)
        self.posts: dict[str, Post] = {}
        self.feed: list[Post] = []
        self.cascade_size: Counter = Counter()
        self.cascade_milestones: dict[str, int] = {}
        self.influenced_by: dict[tuple, float] = defaultdict(float)   # (source, target) -> total |Δ| toward source
        self.interactions = 0
        self.round = 0
        self.group_names: dict[int, str] = {}
        for a in self.agents.values():
            a.initial_opinions = dict(a.opinions)
        self._build_network()

    # ------------------------------------------------------------------ network
    def _build_network(self):
        ids = list(self.agents)
        topic = next(iter(self.topics), None)
        for i in ids:
            a = self.agents[i]
            want = int(3 + a.traits.get("extraversion", 0.5) * 6)
            scored = []
            for j in ids:
                if j == i or j in self.ties[i]:
                    continue
                b = self.agents[j]
                same = 2.5 if a.segment == b.segment else 1.0
                sim = math.exp(-abs(a.opinions.get(topic, 0) - b.opinions.get(topic, 0)) * 1.5) if topic else 1.0
                score = same * sim * (0.3 + b.influence) * self.rng.uniform(0.6, 1.4)
                scored.append((score, j))
            scored.sort(reverse=True)
            for _, j in scored[: want]:
                w = round(self.rng.uniform(0.25, 0.85), 3)
                self.ties[i][j] = w
                self.ties[j][i] = round(w * self.rng.uniform(0.6, 1.0), 3)

    def edges(self) -> list:
        seen, out = set(), []
        for i, nb in self.ties.items():
            for j, w in nb.items():
                key = (min(i, j), max(i, j))
                if key in seen or w < 0.1:
                    continue
                seen.add(key)
                out.append([key[0], key[1], round((w + self.ties[j].get(i, 0)) / 2, 3)])
        return out

    # ------------------------------------------------------------------ helpers
    def _rng(self, r: int, salt: int = 0) -> random.Random:
        return random.Random(self.cfg.seed * 1_000_003 + r * 97 + salt)

    def neighbours(self, i: int, min_w: float = 0.1):
        return [j for j, w in self.ties[i].items() if w >= min_w]

    def visible_posts(self, agent: Agent, rnd: int, rng: random.Random) -> list[Post]:
        nb = set(self.neighbours(agent.id))
        vis = [p for p in self.feed if p.round >= rnd - 3 and p.author != agent.id and p.author in nb]
        trending = sorted((p for p in self.feed if p.round >= rnd - 2 and p.author != agent.id and p.author not in nb),
                          key=lambda p: -(self.cascade_size[p.root] + p.strength))[:3]
        if trending and rng.random() < 0.35 + 0.4 * agent.traits.get("extraversion", 0.5):
            vis.append(rng.choice(trending))
        return vis

    def _bound(self, a: Agent) -> float:
        # bounded-confidence radius: more open agents tolerate larger disagreement
        return 0.25 + 0.75 * a.traits.get("openness", 0.5) * (1 - 0.5 * a.traits.get("stubbornness", 0.5))

    def _susceptibility(self, a: Agent) -> float:
        return (1 - a.traits.get("stubbornness", 0.5)) * (0.35 + 0.65 * a.traits.get("conformity", 0.5)) * 1.3

    def remember(self, a: Agent, rnd: int, text: str):
        a.memory.append({"round": rnd, "text": text})
        if len(a.memory) > 10:
            old = a.memory[:-8]
            a.memory = a.memory[-8:]
            a.digest = (a.digest + " " + "; ".join(m["text"][:70] for m in old[-2:])).strip()[-420:]

    # ------------------------------------------------------------------ planning
    def plan_round(self, rnd: int) -> list[Intent]:
        self.round = rnd
        rng = self._rng(rnd, 1)
        intents: list[Intent] = []
        topic_ids = list(self.topics)
        order = list(self.agents.values())
        rng.shuffle(order)
        boost = 1.25 if any(s.round == rnd for s in self.cfg.shocks) else 1.0
        for a in order:
            if len(intents) >= self.cfg.max_actions_per_round:
                break
            if rng.random() > min(0.95, a.activity * boost):
                continue
            posts = self.visible_posts(a, rnd, rng)
            it = self._decide(a, posts, rnd, rng, topic_ids)
            if it:
                intents.append(it)
        return intents

    def _decide(self, a: Agent, posts: list[Post], rnd: int, rng: random.Random, topic_ids: list) -> Optional[Intent]:
        ext = a.traits.get("extraversion", 0.5)
        # engage with something already said, or originate? Originating is likelier early and for extraverts/influencers.
        p_original = 0.18 + 0.25 * ext + 0.2 * a.influence + (0.3 if rnd <= 2 else 0)
        if not posts or rng.random() < p_original * (0.5 if posts else 1.0):
            return self._originate(a, rng, topic_ids, rnd)
        # choose a post: closer ties and stronger/relevant posts attract attention
        weights = []
        for p in posts:
            tie = self.ties[a.id].get(p.author, 0.05)
            sal = a.salience.get(p.topic, 1.0)
            weights.append(max(0.01, (0.2 + tie) * sal * (0.4 + p.strength) * (0.6 + self.agents[p.author].influence)))
        p = rng.choices(posts, weights)[0]
        x = a.opinions.get(p.topic, 0.0)
        d = abs(x - p.stance)
        eps = self._bound(a)
        tie = self.ties[a.id].get(p.author, 0.0)
        z = (eps - d) * 3.0 + tie * 1.2 + (a.traits.get("agreeableness", 0.5) - 0.5) * 1.2
        p_agree = 1 / (1 + math.exp(-z))
        agrees = rng.random() < p_agree
        topic = p.topic
        author = self.agents[p.author]
        if agrees:
            my_stance = clamp(x + 0.5 * (p.stance - x))
            if d < 0.25 and abs(x) > 0.25 and rng.random() < 0.18 + 0.5 * ext:
                typ = "share"
            elif d < 0.5 and rng.random() < 0.55:
                typ = "agree"
            else:
                typ = "reply"
            reason = (f"{typ.capitalize()}: stance gap {d:.2f} is inside {a.name.split()[0]}'s openness bound {eps:.2f}; "
                      f"tie to {author.name.split()[0]} {tie:.2f}")
        else:
            my_stance = clamp(x - 0.25 * (p.stance - x) if d > eps else x)
            typ = "disagree" if d > 0.45 or rng.random() < 0.5 else "reply"
            why = (f"stance gap {d:.2f} exceeds openness bound {eps:.2f}" if d > eps else
                   f"stance gap {d:.2f} is within openness bound {eps:.2f} but pushback won out (weak pull)")
            reason = f"{typ.capitalize()}: {why}; tie {tie:.2f}, agreeableness {a.traits.get('agreeableness', .5):.2f}"
        strength = clamp(0.25 + 0.5 * abs(my_stance) + 0.25 * a.influence, 0, 1)
        it = Intent(typ, a.id, topic, my_stance, strength, target=p.author, post=p, reason=reason)
        if typ == "share":
            it.audience = self._audience(a, rng, exclude={p.author})
        return it

    def _audience(self, a: Agent, rng: random.Random, exclude=()) -> list:
        nb = [j for j in self.neighbours(a.id) if j not in exclude]
        nb.sort(key=lambda j: -self.ties[a.id][j])
        k = min(len(nb), 2 + int(a.influence * 3))
        return nb[:k] if k else []

    def _originate(self, a: Agent, rng: random.Random, topic_ids: list, rnd: int) -> Optional[Intent]:
        tw = [max(0.05, a.salience.get(t, 1.0)) for t in topic_ids]
        topic = rng.choices(topic_ids, tw)[0]
        x = a.opinions.get(topic, 0.0)
        stance = clamp(x + rng.gauss(0, 0.08))
        strength = clamp(0.2 + 0.55 * abs(x) + 0.25 * a.influence, 0, 1)
        aud = self._audience(a, rng)
        if not aud:
            return None
        reason = (f"Originates a post: salience of topic {a.salience.get(topic, 1.0):.2f}, "
                  f"extraversion {a.traits.get('extraversion', .5):.2f}, influence {a.influence:.2f}")
        return Intent("post", a.id, topic, stance, strength, target=aud[0], audience=aud, reason=reason)

    # ------------------------------------------------------------------ apply
    def apply(self, intents: list[Intent], rnd: int, emit) -> None:
        """Apply intents sequentially, emitting events through `emit(type, **fields) -> event_id`."""
        for it in intents:
            if it.type == "ignore":
                continue
            src = self.agents[it.source]
            self.interactions += 1
            changes: dict[str, Any] = {"opinion": {}, "relationships": [], "sentiment": {}}
            if it.type == "post":
                self._apply_post(it, src, rnd, emit, changes)
            else:
                self._apply_response(it, src, rnd, emit, changes)

    def _nudge(self, listener: Agent, speaker: Agent, topic: str, stance: float, strength: float, factor: float,
               changes: dict, rng: random.Random, cause_event: str):
        x = listener.opinions.get(topic, 0.0)
        d = stance - x
        eps = self._bound(listener)
        mu = self._susceptibility(listener) * (0.5 + 0.5 * speaker.influence) * (0.4 + 0.6 * strength) * factor
        if abs(d) <= eps:
            new = x + mu * d
        else:  # backlash only for low-agreeableness agents
            back = 0.12 * (1 - listener.traits.get("agreeableness", 0.5)) * factor
            new = x - back * d
        new = clamp(new)
        delta = new - x
        if abs(delta) >= 0.004:
            listener.opinions[topic] = new
            ch = changes["opinion"].setdefault(str(listener.id), {"topic": topic, "from": round(x, 3), "to": round(new, 3)})
            ch["to"] = round(new, 3)
            if delta * d > 0:
                self.influenced_by[(speaker.id, listener.id)] += abs(delta)
            if band(x) != band(new) and abs(new - x) > 0.0:
                self._pending_band.append((listener, speaker, topic, x, new, cause_event))
        return delta

    def _tie_update(self, a: int, b: int, delta: float, changes: dict, emit_list: list):
        old = self.ties[a].get(b, 0.0)
        new = max(-1.0, min(1.0, old + delta))
        self.ties[a][b] = new
        old_b = self.ties[b].get(a, 0.0)
        self.ties[b][a] = max(-1.0, min(1.0, old_b + delta * 0.6))
        if abs(new - old) > 1e-6:
            changes["relationships"].append({"a": a, "b": b, "from": round(old, 3), "to": round(new, 3)})
        if (old < 0.25 <= new) or (old > -0.2 >= new):
            emit_list.append((a, b, old, new))

    def _apply_post(self, it: Intent, src: Agent, rnd: int, emit, changes: dict):
        rng = self._rng(rnd, 10 + it.source)
        self._pending_band = []
        rel_emits: list = []
        post = Post("", src.id, rnd, it.topic, it.stance, it.strength, root="", depth=0)
        ev_id = emit("post", source=it.source, target=it.target, agents=[it.source] + it.audience, topic=it.topic,
                     content=it.text, content_source=it.content_source or "pending", reason=it.reason,
                     result={"stance": round(it.stance, 3), "strength": round(it.strength, 3), "audience": it.audience,
                             "decided_by": it.decided_by}, state_changes=changes, deferred=True)
        post.id = ev_id; post.root = ev_id; post.text = it.text
        self.posts[ev_id] = post; self.feed.append(post)
        self.cascade_size[ev_id] += 1
        for j in it.audience:
            listener = self.agents[j]
            self._nudge(listener, src, it.topic, it.stance, it.strength, 0.35, changes, rng, ev_id)
            self.remember(listener, rnd, f"{src.name} said: {it.text[:110]}" if it.text else f"{src.name} posted about {it.topic}")
            post.reach += 1
        self.remember(src, rnd, f"I posted my view on {it.topic}.")
        self._flush_band(emit, rnd, ev_id)
        emit("__finalize__", ref=ev_id, state_changes=changes, post=post)

    def _apply_response(self, it: Intent, src: Agent, rnd: int, emit, changes: dict):
        rng = self._rng(rnd, 10 + it.source)
        self._pending_band = []
        rel_emits: list = []
        p = it.post
        author = self.agents[it.target]
        # the engaging agent is influenced by what they read (bounded confidence), the author mildly by the reply
        ev_id = emit(it.type, source=it.source, target=it.target, agents=[it.source, it.target] + [x for x in it.audience],
                     topic=it.topic, content=it.text, content_source=it.content_source or "pending", reason=it.reason,
                     result={"stance": round(it.stance, 3), "strength": round(it.strength, 3), "in_reply_to": p.id if p else None,
                             "decided_by": it.decided_by}, state_changes=changes, deferred=True)
        agrees = it.type in ("agree", "share") or (it.type == "reply" and (it.stance - src.opinions.get(it.topic, 0)) * (p.stance - src.opinions.get(it.topic, 0)) >= 0 and abs(it.stance - p.stance) < 0.6)
        if it.shift_override is not None:
            x = src.opinions.get(it.topic, 0.0)
            new = clamp(x + clamp(it.shift_override, -0.3, 0.3))
            if abs(new - x) >= 0.004:
                src.opinions[it.topic] = new
                changes["opinion"][str(src.id)] = {"topic": it.topic, "from": round(x, 3), "to": round(new, 3)}
                if band(x) != band(new):
                    self._pending_band.append((src, author, it.topic, x, new, ev_id))
        else:
            self._nudge(src, author, it.topic, p.stance, p.strength, 1.0, changes, rng, ev_id)
        self._nudge(author, src, it.topic, it.stance, it.strength, 0.25, changes, rng, ev_id)
        # sentiment + relationships
        src.sentiment = clamp(src.sentiment * 0.85 + (0.18 if agrees else -0.22))
        author.sentiment = clamp(author.sentiment * 0.9 + (0.1 if agrees else -0.12))
        changes["sentiment"][str(src.id)] = round(src.sentiment, 3)
        changes["sentiment"][str(author.id)] = round(author.sentiment, 3)
        self._tie_update(src.id, author.id, 0.09 if agrees else -0.08, changes, rel_emits)
        verb = {"agree": "agreed with", "disagree": "disagreed with", "reply": "replied to", "share": "shared a post by"}[it.type]
        self.remember(src, rnd, f"I {verb} {author.name}.")
        self.remember(author, rnd, f"{src.name} {verb.replace('agreed with', 'agreed with me').replace('disagreed with', 'disagreed with me').replace('replied to', 'replied to me').replace('shared a post by', 'shared my post')}")
        root = p.root if p else ev_id
        new_post = Post(ev_id, src.id, rnd, it.topic, it.stance, it.strength, text=it.text, root=root,
                        parent=p.id if p else None, depth=(p.depth + 1) if p else 0)
        self.posts[ev_id] = new_post
        if it.type in ("share", "reply", "agree"):
            self.feed.append(new_post)
        if it.type == "share" and p:
            p.reach += 1
            self.cascade_size[root] += 1
            for j in it.audience:
                self._nudge(self.agents[j], src, it.topic, it.stance, it.strength, 0.3, changes, rng, ev_id)
                self.remember(self.agents[j], rnd, f"{src.name} shared a post about {it.topic}.")
            self._cascade_check(root, rnd, emit)
        for a_, b_, old, new in rel_emits:
            kind = "formed a bond" if new >= 0.25 else "grew distrustful"
            emit("relationship_change", source=a_, target=b_, agents=[a_, b_], topic=it.topic,
                 content=f"{self.agents[a_].name} and {self.agents[b_].name} {kind}",
                 content_source="engine", reason=f"tie weight {old:.2f} → {new:.2f} after {it.type}",
                 result={"from": round(old, 3), "to": round(new, 3)}, state_changes={"relationships": [{"a": a_, "b": b_, "from": round(old, 3), "to": round(new, 3)}]},
                 cause=ev_id)
        self._flush_band(emit, rnd, ev_id)
        emit("__finalize__", ref=ev_id, state_changes=changes, post=new_post)

    def _flush_band(self, emit, rnd: int, cause: str):
        seen = set()
        for listener, speaker, topic, x, new, cause_ev in self._pending_band:
            if listener.id in seen:
                continue
            seen.add(listener.id)
            t = self.topics[topic]
            emit("opinion_change", source=speaker.id, target=listener.id, agents=[speaker.id, listener.id], topic=topic,
                 content=f"{listener.name} moved from {band(x)} to {band(new)} on “{t.label}”",
                 content_source="engine", reason=f"cumulative influence of {speaker.name} (influence {speaker.influence:.2f}) pushed opinion {x:+.2f} → {new:+.2f}",
                 result={"from": round(x, 3), "to": round(new, 3), "from_band": band(x), "to_band": band(new)},
                 state_changes={"opinion": {str(listener.id): {"topic": topic, "from": round(x, 3), "to": round(new, 3)}}}, cause=cause_ev)
        self._pending_band = []

    def _cascade_check(self, root: str, rnd: int, emit):
        size = self.cascade_size[root]
        for m in (4, 8, 16, 32):
            if size >= m and self.cascade_milestones.get(root, 0) < m:
                self.cascade_milestones[root] = m
                rp = self.posts.get(root)
                if rp:
                    emit("cascade", source=rp.author, target=None, agents=[rp.author], topic=rp.topic,
                         content=f"Information cascade from {self.agents[rp.author].name} reached {size} participants",
                         content_source="engine", reason=f"share chain rooted at {root} reached size {size}",
                         result={"root": root, "size": size}, state_changes={}, cause=root)

    # ------------------------------------------------------------------ external events
    def apply_shocks(self, rnd: int, emit) -> None:
        for s in [s for s in self.cfg.shocks if s.round == rnd]:
            rng = self._rng(rnd, 5000)
            affected, changes = [], {"opinion": {}}
            topic = s.topic or next(iter(self.topics))
            for a in self.agents.values():
                if rng.random() > s.reach:
                    continue
                delta = 0.0
                for eff in s.effects:
                    if eff.get("segment", "*") not in ("*", a.segment):
                        continue
                    sens = a.sensitivities.get(eff["sensitivity"], 0.5) if eff.get("sensitivity") else 1.0
                    delta += eff["delta"] * sens
                delta *= (1 - 0.6 * a.traits.get("stubbornness", 0.5))
                if abs(delta) < 0.01:
                    continue
                x = a.opinions.get(topic, 0.0)
                new = clamp(x + delta)
                a.opinions[topic] = new
                changes["opinion"][str(a.id)] = {"topic": topic, "from": round(x, 3), "to": round(new, 3)}
                affected.append(a.id)
                self.remember(a, rnd, f"News: {s.label}")
                a.activity = min(0.95, a.activity + 0.05)
            emit("external_event", source=None, target=None, agents=affected, topic=topic, content=s.label + (f" — {s.description}" if s.description else ""),
                 content_source="external", reason="scheduled scenario assumption" + (" (unverified)" if s.assumption else ""),
                 result={"affected": len(affected), "effects": s.effects, "assumption": s.assumption}, state_changes=changes)

    # ------------------------------------------------------------------ groups
    def update_groups(self, rnd: int, emit) -> None:
        """Label propagation over positive ties weighted by opinion similarity."""
        rng = self._rng(rnd, 777)
        topic = next(iter(self.topics))
        labels = {i: (a.group if a.group is not None else i) for i, a in self.agents.items()}
        ids = list(self.agents)
        for _ in range(6):
            rng.shuffle(ids)
            for i in ids:
                score: Counter = Counter()
                for j, w in self.ties[i].items():
                    if w <= 0.1:
                        continue
                    sim = 1 - abs(self.agents[i].opinions.get(topic, 0) - self.agents[j].opinions.get(topic, 0)) / 2
                    score[labels[j]] += w * (0.4 + sim)
                if score:
                    labels[i] = score.most_common(1)[0][0]
        sizes = Counter(labels.values())
        keep = [l for l, n in sizes.items() if n >= 4]
        remap = {l: k for k, l in enumerate(sorted(keep, key=lambda l: -sizes[l]))}
        for i, a in self.agents.items():
            new = remap.get(labels[i])
            if new != a.group:
                old = a.group
                a.group = new
                if new is not None:
                    members = [self.agents[m] for m in self.agents if remap.get(labels[m]) == new]
                    self.group_names[new] = self._group_name(new, members, topic)
                    emit("join_group", source=i, target=None, agents=[i], topic=topic,
                         content=f"{a.name} joined {self.group_names[new]}", content_source="engine",
                         reason=f"label propagation: strongest weighted ties and opinion similarity are in group {new}",
                         result={"group": new, "previous": old, "group_name": self.group_names[new], "size": len(members)},
                         state_changes={"group": {str(i): new}})
                elif old is not None:
                    emit("leave_group", source=i, target=None, agents=[i], topic=topic, content=f"{a.name} left their group",
                         content_source="engine", reason="no cohesive community (<4 members) at last re-clustering",
                         result={"previous": old}, state_changes={"group": {str(i): None}})

    def _group_name(self, gid: int, members: list, topic: str) -> str:
        seg = Counter(m.segment for m in members).most_common(1)[0][0]
        mean = sum(m.opinions.get(topic, 0) for m in members) / max(1, len(members))
        lean = "pro" if mean > 0.2 else "sceptical" if mean < -0.2 else "undecided"
        return f"{seg} · {lean} cluster {gid + 1}"

    # ------------------------------------------------------------------ metrics
    def metrics(self) -> dict:
        topic = next(iter(self.topics))
        xs = [a.opinions.get(topic, 0.0) for a in self.agents.values()]
        n = len(xs)
        mean = sum(xs) / n
        var = sum((x - mean) ** 2 for x in xs) / n
        std = math.sqrt(var)
        bands = Counter(band(x) for x in xs)
        groups = Counter(a.group for a in self.agents.values() if a.group is not None)
        return {
            "topic": topic, "mean_opinion": round(mean, 4), "std": round(std, 4), "polarisation": round(min(1.0, std), 4),
            "consensus": round(max(0.0, 1 - std), 4), "extreme_share": round(sum(1 for x in xs if abs(x) > 0.66) / n, 4),
            "support": bands["support"], "neutral": bands["neutral"], "oppose": bands["oppose"],
            "groups": len(groups), "largest_group": max(groups.values()) if groups else 0,
            "modularity": round(self.modularity(), 4), "max_cascade": max(self.cascade_size.values()) if self.cascade_size else 0,
            "interactions_total": self.interactions,
        }

    def modularity(self) -> float:
        total = 0.0
        deg: Counter = Counter()
        for i, nb in self.ties.items():
            for j, w in nb.items():
                if w > 0.1:
                    deg[i] += w; total += w
        if total == 0:
            return 0.0
        q = 0.0
        for i, nb in self.ties.items():
            gi = self.agents[i].group
            if gi is None:
                continue
            for j, w in nb.items():
                if w > 0.1 and self.agents[j].group == gi:
                    q += w - deg[i] * deg[j] / total
        return q / total

    def influence_scores(self, iters: int = 25, d: float = 0.85) -> dict:
        """PageRank over the 'who changed whose opinion' graph (edges source -> influenced)."""
        ids = list(self.agents)
        n = len(ids)
        out: dict = defaultdict(dict)
        for (s, t), w in self.influenced_by.items():
            out[t][s] = out[t].get(s, 0) + w   # rank flows to those who influenced you
        pr = {i: 1 / n for i in ids}
        for _ in range(iters):
            new = {i: (1 - d) / n for i in ids}
            for t in ids:
                srcs = out.get(t)
                if not srcs:
                    for i in ids:
                        new[i] += d * pr[t] / n
                    continue
                tot = sum(srcs.values())
                for s, w in srcs.items():
                    new[s] += d * pr[t] * w / tot
            pr = new
        mx = max(pr.values()) or 1
        return {i: round(v / mx, 4) for i, v in pr.items()}
