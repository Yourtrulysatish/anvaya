"""MiroFish / OASIS adapter.

Converts MiroFish `actions.jsonl` (one JSON object per line, written by its OASIS subprocess scripts) into ANVAYA's normalised
events, preserving original identifiers in `provenance`. Format source: MiroFish backend/scripts/action_logger.py
(fields: round, timestamp, agent_id, agent_name, action_type, action_args, result, success; plus event_type lines
round_start / round_end / simulation_start / simulation_end).

STATUS: tested against that documented format with fixtures. NOT yet run against a live MiroFish install
(requires Python 3.11/3.12, camel-oasis, and a Zep Cloud key).

OASIS actions are mostly broadcast-style, so many carry no explicit target agent; those events keep `target_agent = None`
and are flagged `target_unknown` rather than inventing a recipient.
"""
from __future__ import annotations

import json
from typing import Iterable, Optional

ACTION_MAP = {
    "CREATE_POST": "post", "CREATE_COMMENT": "reply", "LIKE_POST": "agree", "LIKE_COMMENT": "agree",
    "DISLIKE_POST": "disagree", "DISLIKE_COMMENT": "disagree", "REPOST": "share", "QUOTE_POST": "share",
    "FOLLOW": "relationship_change", "UNFOLLOW": "relationship_change", "MUTE": "relationship_change", "UNMUTE": "relationship_change",
}
TARGET_KEYS = ["followee_id", "target_user_id", "target_agent_id", "original_author_id", "post_author_id", "author_id", "user_id"]
CONTENT_KEYS = ["content", "quote_content", "text", "post_content"]
IGNORED = {"DO_NOTHING", "REFRESH", "TREND", "SEARCH_POSTS", "SEARCH_USER", "SIGNUP", "INTERVIEW"}


def _target(args: dict, actor: int) -> Optional[int]:
    for k in TARGET_KEYS:
        v = args.get(k)
        if isinstance(v, int) and v != actor:
            return v
    return None


def normalise(lines: Iterable[str], simulation_id: str, platform: str = "unknown") -> dict:
    """Returns {agents, events, skipped}. Events follow ANVAYA's schema; ids/ordering are assigned in file order."""
    events: list[dict] = []
    agents: dict[int, str] = {}
    skipped = {"ignored_action": 0, "bad_line": 0}
    seq = 0
    cur_round = 0
    total_rounds = 0

    def push(type_: str, **kw):
        nonlocal seq
        ev = {"id": f"{simulation_id}:{seq}", "seq": seq, "simulation_id": simulation_id, "round": kw.pop("round", cur_round), "type": type_,
              "source_agent": kw.pop("source", None), "target_agent": kw.pop("target", None), "agents": kw.pop("agents", []), "topic": kw.pop("topic", None),
              "content": kw.pop("content", ""), "content_source": kw.pop("content_source", "mirofish"), "reason": kw.pop("reason", ""),
              "result": kw.pop("result", {}), "state_changes": kw.pop("state_changes", {}), "timestamp": kw.pop("timestamp", ""),
              "provenance": kw.pop("provenance", {})}
        seq += 1
        events.append(ev)

    for n, raw in enumerate(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            o = json.loads(raw)
        except json.JSONDecodeError:
            skipped["bad_line"] += 1
            continue
        prov = {"engine": "mirofish", "platform": platform, "line": n, "original": o}
        et = o.get("event_type")
        if et == "simulation_start":
            total_rounds = int(o.get("total_rounds", 0) or 0)
            push("sim_start", content="MiroFish simulation started", timestamp=o.get("timestamp", ""), provenance=prov,
                 result={"agents": o.get("agents_count"), "rounds": total_rounds, "edges": [], "mode": "mirofish", "llm": True, "topics": []})
            continue
        if et == "round_start":
            cur_round = int(o.get("round", cur_round + 1))
            push("round_start", content=f"Round {cur_round}", round=cur_round, timestamp=o.get("timestamp", ""), provenance=prov, result={"round": cur_round, "simulated_hour": o.get("simulated_hour")})
            continue
        if et == "round_end":
            push("round_end", content=f"Round {o.get('round', cur_round)} complete", round=int(o.get("round", cur_round)), timestamp=o.get("timestamp", ""), provenance=prov, result={"actions_count": o.get("actions_count")})
            continue
        if et == "simulation_end":
            push("sim_end", content="MiroFish simulation ended", timestamp=o.get("timestamp", ""), provenance=prov, result={"total_actions": o.get("total_actions"), "status": "completed"})
            continue
        at = o.get("action_type")
        if at is None:
            skipped["bad_line"] += 1
            continue
        aid = o.get("agent_id")
        if not isinstance(aid, int):
            skipped["bad_line"] += 1
            continue
        agents.setdefault(aid, o.get("agent_name") or f"Agent {aid}")
        if at in IGNORED or at not in ACTION_MAP:
            skipped["ignored_action"] += 1
            continue
        args = o.get("action_args") or {}
        tgt = _target(args, aid)
        content = next((str(args[k]) for k in CONTENT_KEYS if args.get(k)), "")
        typ = ACTION_MAP[at]
        rnd = int(o.get("round", cur_round) or cur_round)
        res = {"original_action": at, "success": o.get("success", True), "result": o.get("result")}
        if tgt is None and typ != "post":
            res["target_unknown"] = True
        if typ == "relationship_change":
            neg = at in ("UNFOLLOW", "MUTE")
            res["from"], res["to"] = (0.5, 0.0) if neg else (0.0, 0.5)
        push(typ, round=rnd, source=aid, target=tgt, agents=[aid] + ([tgt] if tgt is not None else []), content=content or f"{agents[aid]} {at.lower().replace('_', ' ')}",
             reason=f"OASIS action {at}" + ("" if tgt is not None else " (no explicit target in log)"), result=res, timestamp=o.get("timestamp", ""), provenance=prov)
        if tgt is not None:
            agents.setdefault(tgt, f"Agent {tgt}")
    return {"agents": agents, "events": events, "skipped": skipped, "rounds": max([e["round"] for e in events] + [total_rounds])}


def to_dataset(parsed: dict, simulation_id: str, title: str) -> tuple[list[dict], list[dict]]:
    """Build (agents, events) usable by the observatory. Opinions are unknown for MiroFish logs, so they start neutral."""
    ids = sorted(parsed["agents"])
    index = {aid: i for i, aid in enumerate(ids)}   # contiguous ids for the canvas; original ids kept in provenance/persona
    agents = [{"id": index[a], "name": parsed["agents"][a], "segment": "MiroFish agent", "persona": f"Agent {a} from an imported MiroFish run (no persona data in the action log).",
               "age": 0, "occupation": "", "location": "", "traits": {}, "sensitivities": {}, "activity": 0.3, "influence": 0.3, "goals": [], "beliefs": [],
               "attributes_basis": "imported", "opinions": {"t1": 0.0}, "mirofish_agent_id": a} for a in ids]
    events = []
    for e in parsed["events"]:
        e = dict(e)
        for k in ("source_agent", "target_agent"):
            if e[k] is not None:
                e[k] = index[e[k]]
        e["agents"] = [index[a] for a in e["agents"]]
        if e["type"] == "relationship_change" and e["source_agent"] is not None and e["target_agent"] is not None:
            e["state_changes"] = {"relationships": [{"a": e["source_agent"], "b": e["target_agent"], "from": e["result"]["from"], "to": e["result"]["to"]}]}
        events.append(e)
    return agents, events
