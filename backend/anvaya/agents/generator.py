"""Population generation: plain-English description -> segments -> diverse, inspectable agents.

Pipeline
  1. interpret(description) -> PopulationSpec     (LLM 'reasoning' model; offline heuristic fallback, clearly labelled)
  2. sample(spec, n, seed) -> list[Agent]          (deterministic trait sampling – guarantees diversity)
  3. enrich_personas(agents)                       (LLM 'agent' model writes persona/goals/beliefs per agent in batches)

Anything not backed by an uploaded document is labelled `attributes_basis = "assumption"`.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Optional

from ..sim.engine import Agent, Topic, clamp

TRAIT_KEYS = ["openness", "agreeableness", "conformity", "extraversion", "stubbornness"]

GENERIC_FIRST = ["Aarav", "Meera", "Kabir", "Ananya", "Rohan", "Isha", "Vikram", "Zoya", "Arjun", "Diya", "Imran", "Sana", "Neel", "Tara",
                 "Dev", "Riya", "Yash", "Nisha", "Farhan", "Pooja", "Kiran", "Lakshmi", "Harsh", "Mira", "Omar", "Elena", "Mateo", "Chloe"]
GENERIC_LAST = ["Sharma", "Iyer", "Khan", "Patel", "Nair", "Reddy", "Das", "Gill", "Menon", "Joshi", "Bose", "Rao", "Kapoor", "Singh", "Verma", "Ali"]


@dataclass
class SegmentSpec:
    name: str
    share: float
    description: str = ""
    traits: dict = field(default_factory=dict)          # trait -> [mean, sd]
    sensitivities: dict = field(default_factory=dict)   # name -> [mean, sd]
    opinion: dict = field(default_factory=dict)         # topic_id -> [mean, sd]
    activity: list = field(default_factory=lambda: [0.3, 0.12])
    influence: list = field(default_factory=lambda: [0.25, 0.2])
    goals: list = field(default_factory=list)
    beliefs: list = field(default_factory=list)
    occupations: list = field(default_factory=list)
    locations: list = field(default_factory=list)
    age: list = field(default_factory=lambda: [30, 8])
    first_names: list = field(default_factory=list)
    last_names: list = field(default_factory=list)


@dataclass
class PopulationSpec:
    title: str
    description: str
    topics: list                       # list[Topic]
    segments: list                     # list[SegmentSpec]
    assumptions: list = field(default_factory=list)
    suggested_rounds: int = 20
    basis: str = "assumption"          # "llm" | "heuristic" | "document" | "demo"

    def to_dict(self):
        return {"title": self.title, "description": self.description, "topics": [t.__dict__ for t in self.topics],
                "segments": [s.__dict__ for s in self.segments], "assumptions": self.assumptions,
                "suggested_rounds": self.suggested_rounds, "basis": self.basis}

    @staticmethod
    def from_dict(d: dict) -> "PopulationSpec":
        return PopulationSpec(d["title"], d.get("description", ""), [Topic(**t) for t in d["topics"]],
                              [SegmentSpec(**s) for s in d["segments"]], d.get("assumptions", []),
                              d.get("suggested_rounds", 20), d.get("basis", "assumption"))


def _g(rng: random.Random, ms, lo=0.0, hi=1.0) -> float:
    m, sd = (ms + [0.15])[:2] if isinstance(ms, list) else (ms, 0.15)
    return min(hi, max(lo, rng.gauss(m, sd)))


def sample(spec: PopulationSpec, n: int, seed: int = 1) -> list[Agent]:
    rng = random.Random(seed)
    total = sum(s.share for s in spec.segments) or 1
    counts = [max(1, round(n * s.share / total)) for s in spec.segments]
    while sum(counts) > n:
        counts[counts.index(max(counts))] -= 1
    while sum(counts) < n:
        counts[counts.index(min(counts))] += 1
    agents, aid, used = [], 0, set()
    for seg, c in zip(spec.segments, counts):
        for _ in range(c):
            first = rng.choice(seg.first_names or GENERIC_FIRST)
            last = rng.choice(seg.last_names or GENERIC_LAST)
            name = f"{first} {last}"
            k = 2
            while name in used:
                name = f"{first} {last} {k}"; k += 1
            used.add(name)
            traits = {t: round(_g(rng, seg.traits.get(t, [0.5, 0.2])), 3) for t in TRAIT_KEYS}
            sens = {k: round(_g(rng, v), 3) for k, v in seg.sensitivities.items()}
            ops = {t.id: round(clamp(rng.gauss(*(seg.opinion.get(t.id, [0.0, 0.35])[:2]))), 3) for t in spec.topics}
            infl = _g(rng, seg.influence)
            infl = min(1.0, infl ** 1.3 + (0.4 if rng.random() < 0.04 else 0))   # a few heavy-tailed influencers
            ag = Agent(
                aid, name, seg.name, "", age=int(max(16, rng.gauss(*seg.age))),
                occupation=rng.choice(seg.occupations) if seg.occupations else seg.name,
                location=rng.choice(seg.locations) if seg.locations else "",
                traits=traits, sensitivities=sens, activity=round(_g(rng, seg.activity, 0.05, 0.9), 3), influence=round(infl, 3),
                goals=rng.sample(seg.goals, min(len(seg.goals), 2)) if seg.goals else [],
                beliefs=rng.sample(seg.beliefs, min(len(seg.beliefs), 2)) if seg.beliefs else [],
                opinions=ops, salience={t.id: round(rng.uniform(0.6, 1.4), 2) for t in spec.topics},
                attributes_basis=spec.basis if spec.basis in ("document", "demo") else "assumption")
            ag.persona = template_persona(ag, seg)
            agents.append(ag)
            aid += 1
    rng.shuffle(agents)
    for i, a in enumerate(agents):      # re-number after shuffle so ids are contiguous
        a.id = i
    return agents


def template_persona(a: Agent, seg: SegmentSpec) -> str:
    tone = []
    t = a.traits
    if t.get("extraversion", .5) > .65: tone.append("outspoken")
    elif t.get("extraversion", .5) < .35: tone.append("reserved")
    if t.get("openness", .5) > .65: tone.append("open to new ideas")
    elif t.get("openness", .5) < .35: tone.append("set in their ways")
    if t.get("stubbornness", .5) > .65: tone.append("slow to change their mind")
    where = f" in {a.location}" if a.location else ""
    return f"{a.name}, {a.age}, {a.occupation}{where}. {seg.description} Tends to be {', '.join(tone) or 'balanced'}."


# --------------------------------------------------------------------------- LLM interpretation

SPEC_SCHEMA = """{
 "title": str, "description": str,
 "topics": [{"id": "t1", "label": str, "question": str, "pos_label": str, "neg_label": str}],   // 1-3 topics, the issue(s) agents form opinions about
 "segments": [{"name": str, "share": float, "description": str,
   "traits": {"openness":[mean,sd],"agreeableness":[..],"conformity":[..],"extraversion":[..],"stubbornness":[..]},   // 0..1
   "sensitivities": {"price":[mean,sd], ...2-4 domain-relevant factors in 0..1},
   "opinion": {"t1":[mean,sd]},      // -1..1 starting stance on each topic
   "activity":[mean,sd], "influence":[mean,sd],
   "goals":[str x4], "beliefs":[str x4], "occupations":[str x4], "locations":[str x3], "age":[mean,sd],
   "first_names":[str x10], "last_names":[str x10]}],   // culturally appropriate names for the described population
 "assumptions": [str],   // every demographic/behavioural attribute NOT stated by the user, phrased as an assumption
 "suggested_rounds": int
}"""


async def interpret(description: str, provider, n: int = 120, context: str = "", project_id: str = None) -> PopulationSpec:
    sys = ("You are a computational social scientist designing a simulated population. Produce diverse, grounded segments. "
           "Be explicit that attributes you invent are assumptions. Use culturally appropriate names. Segment shares must sum to ~1.")
    user = (f"User request: {description}\nTarget population size: {n}\n"
            + (f"Evidence extracted from the user's documents (use it, cite it as evidence not assumption):\n{context[:6000]}\n" if context else "")
            + f"Return JSON matching:\n{SPEC_SCHEMA}")
    data, res = await provider.chat_json("reasoning", [{"role": "system", "content": sys}, {"role": "user", "content": user}],
                                         temperature=0.6, max_tokens=7000, project_id=project_id)
    spec = spec_from_llm(data)
    spec.basis = "llm"
    return spec


def _pair(v, default):
    """Coerce the many shapes models emit for a (mean, sd) pair."""
    try:
        if isinstance(v, bool):
            return default
        if isinstance(v, (int, float)):
            return [float(v), 0.15]
        if isinstance(v, (list, tuple)) and v:
            return [float(v[0]), float(v[1]) if len(v) > 1 else 0.15]
        if isinstance(v, dict):
            m = v.get("mean", v.get("m", v.get("avg")))
            return [float(m), float(v.get("sd", v.get("std", v.get("stdev", 0.15))))]
        if isinstance(v, str):
            return [float(v.strip().rstrip("%")), 0.15]
    except (TypeError, ValueError):
        pass
    return default


def _strs(v, limit=8) -> list:
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if isinstance(x, (str, int, float))][:limit]
    return []


def _num(v, default):
    try:
        return float(str(v).strip().rstrip("%"))
    except (TypeError, ValueError):
        return default


def spec_from_llm(data) -> PopulationSpec:
    if not isinstance(data, dict):
        raise ValueError("model returned a non-object")
    raw_topics = [t for t in (data.get("topics") or []) if isinstance(t, dict) and t.get("label")]
    if not raw_topics or not isinstance(data.get("segments"), list) or not data["segments"]:
        raise ValueError("model output lacks topics or segments")
    topics = [Topic(str(t.get("id") or f"t{i+1}"), str(t["label"]), str(t.get("question", "")), str(t.get("pos_label", "in favour")), str(t.get("neg_label", "against")))
              for i, t in enumerate(raw_topics)][:3]
    segs = []
    for s in data["segments"][:10]:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        traits = s.get("traits") if isinstance(s.get("traits"), dict) else {}
        sens = s.get("sensitivities") if isinstance(s.get("sensitivities"), dict) else {}
        op = s.get("opinion") if isinstance(s.get("opinion"), dict) else {}
        segs.append(SegmentSpec(
            name=str(s["name"]), share=_num(s.get("share", 1), 1.0), description=str(s.get("description", "")),
            traits={k: _pair(v, [0.5, 0.2]) for k, v in traits.items() if k in TRAIT_KEYS},
            sensitivities={str(k): _pair(v, [0.5, 0.2]) for k, v in list(sens.items())[:6]},
            opinion={str(k): _pair(v, [0.0, 0.35]) for k, v in op.items()},
            activity=_pair(s.get("activity"), [0.3, 0.12]), influence=_pair(s.get("influence"), [0.25, 0.2]),
            goals=_strs(s.get("goals")), beliefs=_strs(s.get("beliefs")), occupations=_strs(s.get("occupations")),
            locations=_strs(s.get("locations")), age=_pair(s.get("age"), [30, 8]),
            first_names=_strs(s.get("first_names"), 20), last_names=_strs(s.get("last_names"), 20)))
    if not segs:
        raise ValueError("no usable segments")
    ids = {t.id for t in topics}
    for s in segs:
        s.opinion = {k: v for k, v in s.opinion.items() if k in ids}
    return PopulationSpec(str(data.get("title", "Population")), str(data.get("description", "")), topics, segs,
                          _strs(data.get("assumptions"), 20), int(_num(data.get("suggested_rounds", 20), 20)))


def interpret_offline(description: str) -> PopulationSpec:
    """No-LLM fallback. Deliberately generic and labelled 'heuristic' – it does not pretend to understand the request."""
    d = description.strip().rstrip(".")
    topic = Topic("t1", d[:80] or "The situation", f"How do people feel about: {d[:120]}?", "supportive", "opposed")
    mk = lambda name, share, op, desc: SegmentSpec(
        name, share, desc, traits={"openness": [0.5, .2], "agreeableness": [0.5, .2], "conformity": [0.5, .2], "extraversion": [0.5, .2], "stubbornness": [0.5, .2]},
        sensitivities={"cost": [0.5, .2], "trust": [0.5, .2]}, opinion={"t1": [op, 0.3]},
        goals=["protect their own interests", "stay informed"], beliefs=["institutions should be accountable"])
    return PopulationSpec("Generic population", description, [topic], [
        mk("Early supporters", .25, .55, "Quick to embrace change."), mk("Pragmatists", .35, .0, "Weigh costs and benefits."),
        mk("Sceptics", .25, -.5, "Distrust claims until proven."), mk("Disengaged", .15, .0, "Rarely participate.")],
        ["All segments, shares, traits and opinions are generic placeholders – no LLM was available to interpret the request."], 15, "heuristic")


async def enrich_personas(agents: list[Agent], spec: PopulationSpec, provider, project_id: str = None, batch: int = 12) -> int:
    """Have the agent model write a distinct first-person persona/goal/belief set per agent. Returns agents enriched."""
    import asyncio
    seg_by_name = {s.name: s for s in spec.segments}
    topic = spec.topics[0]

    async def one(chunk):
        items = [{"id": a.id, "name": a.name, "segment": a.segment, "age": a.age, "occupation": a.occupation, "location": a.location,
                  "traits": {k: round(v, 2) for k, v in a.traits.items()}, "stance_on_topic": round(a.opinions.get(topic.id, 0), 2),
                  "segment_context": seg_by_name[a.segment].description if a.segment in seg_by_name else ""} for a in chunk]
        user = (f"Topic simulated: {topic.label}. Write a distinct, concrete persona for each fictional person below (these are "
                "simulated agents, not real people). Their traits and stance are fixed; reflect them. Avoid repeating phrasing.\n"
                + json.dumps(items, ensure_ascii=False)
                + '\nReturn JSON: {"agents":[{"id":int,"persona":"2 sentences","goals":["..",".."],"beliefs":["..",".."]}]}')
        data, _ = await provider.chat_json("agent", [{"role": "user", "content": user}], temperature=0.9, max_tokens=5000, project_id=project_id)
        by = {x["id"]: x for x in data.get("agents", []) if isinstance(x, dict) and "id" in x}
        n = 0
        for a in chunk:
            x = by.get(a.id)
            if x and x.get("persona"):
                a.persona = str(x["persona"])[:500]
                if x.get("goals"): a.goals = [str(g)[:120] for g in x["goals"]][:3]
                if x.get("beliefs"): a.beliefs = [str(b)[:140] for b in x["beliefs"]][:3]
                n += 1
        return n

    res = await asyncio.gather(*[one(agents[i:i + batch]) for i in range(0, len(agents), batch)], return_exceptions=True)
    return sum(r for r in res if isinstance(r, int))
