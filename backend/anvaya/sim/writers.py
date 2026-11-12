"""Content writers: turn engine intents into language.

TemplateWriter  – deterministic, no network. Used by DEMO mode and as the labelled fallback when the LLM is unavailable.
LLMWriter       – batches intents into few FreeModel calls (the provider allows 60 req/min, so one call per agent is impossible).
"""
from __future__ import annotations

import asyncio
import random
from typing import Optional

from .engine import Agent, Engine, Intent, band, clamp

OPEN_POST = {
    "strong_for": ["Honestly, I can't wait on this one.", "I've made up my mind — count me in.", "This is exactly what I've been waiting for."],
    "for": ["Leaning positive on this.", "I think this makes sense.", "Cautiously optimistic here."],
    "mixed": ["Still on the fence, to be honest.", "Mixed feelings on this.", "I see both sides here."],
    "against": ["I'm not convinced.", "Hard to justify this for me.", "Sceptical, to be fair."],
    "strong_against": ["Absolutely not for me.", "This is a clear no from my side.", "I think people are being misled on this."],
}
REPLY_AGREE = ["Agree with {t} —", "{t} is right,", "Same here, {t}:", "Fair point, {t}."]
REPLY_DISAGREE = ["I don't buy that, {t} —", "Respectfully disagree, {t}:", "{t}, that overlooks something:", "Not so sure, {t}."]
REPLY_NEUTRAL = ["Interesting, {t} —", "{t}, partly true, but", "Hmm {t}, though"]
SHARE = ["Worth a read:", "Passing this on —", "This matches my experience:", "Sharing because it matters:"]


def stance_bucket(x: float) -> str:
    return "strong_for" if x > 0.6 else "for" if x > 0.2 else "against" if x < -0.2 and x >= -0.6 else "strong_against" if x < -0.6 else "mixed"


def _frag(s: str, n: int = 90) -> str:
    s = (s or "").strip().rstrip(".")
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0]


class TemplateWriter:
    source = "template"

    def __init__(self, engine: Engine):
        self.e = engine

    def text_for(self, it: Intent, rnd: int) -> str:
        a: Agent = self.e.agents[it.source]
        rng = random.Random(self.e.cfg.seed * 7919 + rnd * 131 + a.id)
        topic = self.e.topics[it.topic]
        clause = topic.pos_label if it.stance > 0.15 else topic.neg_label if it.stance < -0.15 else "undecided"
        hooks = a.goals + a.beliefs
        hook = _frag(rng.choice(hooks)) if hooks else a.segment
        if it.type == "post":
            op = rng.choice(OPEN_POST[stance_bucket(it.stance)])
            return f"{op} As someone who cares about {hook.lower()}, I'm {clause}."
        tname = self.e.agents[it.target].name.split()[0] if it.target is not None else "friend"
        if it.type == "agree":
            return f"{rng.choice(REPLY_AGREE).format(t=tname)} {hook.lower()} is why I'm {clause} too."
        if it.type == "disagree":
            return f"{rng.choice(REPLY_DISAGREE).format(t=tname)} for me, {hook.lower()} matters more, so I'm {clause}."
        if it.type == "share":
            return f"{rng.choice(SHARE)} {tname}'s take on “{topic.label}” fits what I think ({clause})."
        return f"{rng.choice(REPLY_NEUTRAL).format(t=tname)} given {hook.lower()}, I'm {clause}."

    async def write(self, intents: list[Intent], rnd: int):
        for it in intents:
            if not it.text:
                it.text = self.text_for(it, rnd)
                it.content_source = "template"


def _stance_words(x: float) -> str:
    return "strongly in favour" if x > 0.6 else "leaning in favour" if x > 0.2 else "strongly against" if x < -0.6 else "leaning against" if x < -0.2 else "undecided / mixed"


class LLMWriter:
    source = "llm"

    def __init__(self, engine: Engine, provider, project_id: str = None, batch: int = 10, budget=None, max_items: int = 0):
        self.e, self.p, self.project_id, self.batch, self.budget = engine, provider, project_id, batch, budget
        self.max_items = max_items          # 0 = LLM writes every message; k = only the k most influential speakers per round
        self.fallback = TemplateWriter(engine)
        self.warnings: list[str] = []
        self.model: Optional[str] = None

    def _agent_card(self, i: int, it: Intent) -> dict:
        a = self.e.agents[it.source]
        card = {"i": i, "speaker": a.name, "persona": a.persona[:260], "goals": a.goals[:2], "beliefs": a.beliefs[:2],
                "type": it.type, "expressed_stance": _stance_words(it.stance),
                "recent_memory": [m["text"] for m in a.memory[-2:]]}
        if it.post is not None and it.target is not None:
            card["replying_to"] = {"author": self.e.agents[it.target].name, "text": it.post.text[:240]}
        return card

    async def _write_batch(self, rnd: int, chunk: list[tuple[int, Intent]]):
        topic = self.e.topics[chunk[0][1].topic]
        sys = ("You write short social-media style messages for simulated people in a research simulation. Stay strictly in "
               "each speaker's voice, consistent with persona, goals and the stance given. 12-40 words each, first person, "
               "no hashtags, no emojis, never claim to be a real person. For type agree/disagree/reply address the author "
               "naturally; for share add a short comment.")
        user = (f"Topic: {topic.label}. {topic.question}\n(In favour = {topic.pos_label}; against = {topic.neg_label})\n"
                f"Round {rnd}. Write one message per item.\nItems:\n" + __import__("json").dumps([self._agent_card(i, it) for i, it in chunk], ensure_ascii=False)
                + '\nReturn JSON: {"messages":[{"i":<int>,"text":"..."}]}')
        data, res = await self.p.chat_json("agent", [{"role": "system", "content": sys}, {"role": "user", "content": user}],
                                           temperature=0.8, max_tokens=3000, project_id=self.project_id)
        self.model = res.model
        by_i = {m.get("i"): (m.get("text") or "").strip() for m in data.get("messages", []) if isinstance(m, dict)}
        for i, it in chunk:
            t = by_i.get(i)
            if t:
                it.text, it.content_source = t[:600], "llm"

    async def write(self, intents: list[Intent], rnd: int):
        todo = [(i, it) for i, it in enumerate(intents) if not it.text]
        if self.max_items and len(todo) > self.max_items:
            todo.sort(key=lambda t: -self.e.agents[t[1].source].influence)
            todo = todo[: self.max_items]            # the rest fall through to the labelled template writer
        if self.budget and self.budget.exhausted():
            self.warnings.append("LLM budget exhausted – template text used")
        else:
            chunks = [todo[k:k + max(self.batch, self.max_items or 0)] for k in range(0, len(todo), max(self.batch, self.max_items or 0))]
            res = await asyncio.gather(*[self._write_batch(rnd, c) for c in chunks], return_exceptions=True)
            for r in res:
                if isinstance(r, Exception):
                    self.warnings.append(f"round {rnd}: LLM text batch failed ({getattr(r, 'kind', r.__class__.__name__)}) – template used")
        await self.fallback.write(intents, rnd)   # fills anything still empty, labelled content_source="template"

    # -- LLM-decided ("deliberating") agents ------------------------------------
    async def deliberate(self, intents: list[Intent], rnd: int, k: int):
        if k <= 0 or not intents or (self.budget and self.budget.exhausted()):
            return
        ranked = sorted(intents, key=lambda it: -(self.e.agents[it.source].influence * 0.6 + self.e.agents[it.source].activity * 0.4))[:k]
        cards = []
        for i, it in enumerate(ranked):
            a = self.e.agents[it.source]
            c = self._agent_card(i, it)
            c["current_opinion"] = round(a.opinions.get(it.topic, 0), 2)
            c["memory_digest"] = a.digest[-200:]
            c["allowed_actions"] = ["post", "ignore"] if it.post is None else ["reply", "agree", "disagree", "share", "ignore"]
            cards.append(c)
        topic = self.e.topics[ranked[0].topic]
        user = (f"Topic: {topic.label}. {topic.question}\n(+1 = {topic.pos_label}, -1 = {topic.neg_label})\nRound {rnd}.\n"
                "For each agent decide what they actually do, given their persona, goals, memory and what they just read. "
                "You may disagree with the rule-based default type. Opinion shift must be within ±0.25.\n"
                + __import__("json").dumps(cards, ensure_ascii=False)
                + '\nReturn JSON: {"decisions":[{"i":int,"action":str,"stance":-1..1,"opinion_shift":-0.25..0.25,"message":str,"reason":str}]}')
        try:
            data, res = await self.p.chat_json("agent", [{"role": "system", "content": "You simulate the decision-making of fictional people in a social-science simulation."},
                                                         {"role": "user", "content": user}], temperature=0.7, max_tokens=4000, project_id=self.project_id)
        except Exception as e:
            self.warnings.append(f"round {rnd}: deliberation failed ({getattr(e, 'kind', e.__class__.__name__)}) – rule decisions kept")
            return
        for d in data.get("decisions", []):
            try:
                it = ranked[int(d["i"])]
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            allowed = ["post", "ignore"] if it.post is None else ["reply", "agree", "disagree", "share", "ignore"]
            act = d.get("action")
            if act not in allowed:
                continue
            it.type = act
            if act == "ignore":
                continue
            try:
                it.stance = clamp(float(d.get("stance", it.stance)))
                it.shift_override = clamp(float(d.get("opinion_shift", 0.0)), -0.25, 0.25)
            except (TypeError, ValueError):
                pass
            if act == "share" and not it.audience:
                it.audience = self.e._audience(self.e.agents[it.source], self.e._rng(rnd, 3), exclude={it.target})
            if d.get("message"):
                it.text, it.content_source = str(d["message"])[:600], "llm"
            if d.get("reason"):
                it.reason = f"LLM decision: {str(d['reason'])[:200]}"
            it.decided_by = "llm"
