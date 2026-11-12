"""Knowledge extraction with provenance. LLM extraction per chunk, with a labelled heuristic fallback."""
from __future__ import annotations

import asyncio
import re
from collections import Counter, defaultdict
from itertools import combinations

from ..ingest import chunk_text

ENTITY_TYPES = ["person", "organisation", "product", "event", "topic", "location", "stakeholder", "risk", "market"]
SCHEMA = """{"entities":[{"name":str,"type":"person|organisation|product|event|topic|location|stakeholder|risk|market","description":str}],
 "relations":[{"source":str,"target":str,"type":str,"quote":str}],
 "facts":[{"text":str,"entity":str,"temporal":"historical|current|assumption","quote":str}],
 "opinions":[{"holder":str,"stance":str,"quote":str}],
 "risks":[str], "variables":[{"name":str,"value":str,"unit":str}]}"""


async def extract_chunk(provider, text: str, doc: dict, idx: int, project_id: str) -> dict:
    sys = ("You extract structured knowledge from source text for an analyst. Only extract what the text states. Every relation and "
           "fact MUST include a short verbatim `quote` from the text as evidence. Classify each fact as historical (past), current "
           "(stated as present), or assumption (speculation/forecast/hypothetical). Do not invent entities.")
    data, _ = await provider.chat_json("extraction", [{"role": "system", "content": sys},
                                                      {"role": "user", "content": f"SOURCE: {doc['name']}\n---\n{text}\n---\nReturn JSON: {SCHEMA}"}],
                                       temperature=0.1, max_tokens=5000, project_id=project_id)
    src = {"doc_id": doc["id"], "doc": doc["name"], "chunk": idx}
    out = {"entities": [], "relations": [], "facts": [], "opinions": [], "risks": [], "variables": []}
    for e in data.get("entities", []) or []:
        if isinstance(e, dict) and e.get("name"):
            out["entities"].append({"name": str(e["name"]).strip()[:120], "type": e.get("type") if e.get("type") in ENTITY_TYPES else "topic",
                                    "description": str(e.get("description", ""))[:300], "source": src})
    for r in data.get("relations", []) or []:
        if isinstance(r, dict) and r.get("source") and r.get("target"):
            out["relations"].append({"source": str(r["source"]).strip()[:120], "target": str(r["target"]).strip()[:120],
                                     "type": str(r.get("type", "related to"))[:60], "quote": str(r.get("quote", ""))[:300], "source_ref": src})
    for f in data.get("facts", []) or []:
        if isinstance(f, dict) and f.get("text"):
            out["facts"].append({"text": str(f["text"])[:400], "entity": str(f.get("entity", ""))[:120],
                                 "temporal": f.get("temporal") if f.get("temporal") in ("historical", "current", "assumption") else "current",
                                 "quote": str(f.get("quote", ""))[:300], "source_ref": src})
    for o in data.get("opinions", []) or []:
        if isinstance(o, dict) and o.get("holder"):
            out["opinions"].append({"holder": str(o["holder"])[:120], "stance": str(o.get("stance", ""))[:300], "quote": str(o.get("quote", ""))[:300], "source_ref": src})
    out["risks"] = [{"text": str(x)[:300], "source_ref": src} for x in (data.get("risks") or []) if x][:20]
    out["variables"] = [{**v, "source_ref": src} for v in (data.get("variables") or []) if isinstance(v, dict) and v.get("name")][:30]
    return out


_CAP = re.compile(r"\b([A-Z][a-zA-Z0-9&.-]+(?:\s+(?:of|and|for|the)?\s*[A-Z][a-zA-Z0-9&.-]+){0,3})\b")
_STOP = {"The", "This", "That", "These", "Those", "A", "An", "In", "On", "At", "It", "We", "He", "She", "They", "For", "And", "But", "However", "Also", "If", "When", "With", "As", "By", "Is", "Are", "Our", "Their", "There"}


def extract_heuristic(text: str, doc: dict, idx: int) -> dict:
    """No-LLM fallback: capitalised phrases as entities, sentence co-mentions as relations, numeric sentences as facts."""
    src = {"doc_id": doc["id"], "doc": doc["name"], "chunk": idx}
    sents = re.split(r"(?<=[.!?])\s+|\n+", text)
    counts: Counter = Counter()
    per_sent = []
    for s in sents:
        names = {m.group(1).strip() for m in _CAP.finditer(s) if m.group(1).strip() not in _STOP and len(m.group(1)) > 2}
        per_sent.append((s, names))
        counts.update(names)
    keep = {n for n, c in counts.items() if c >= 2 or len(n.split()) >= 2}
    ents = [{"name": n, "type": "topic", "description": "", "source": src} for n, _ in counts.most_common(60) if n in keep]
    rels = []
    for s, names in per_sent:
        ns = sorted(n for n in names if n in keep)[:5]
        for a, b in combinations(ns, 2):
            rels.append({"source": a, "target": b, "type": "co-mentioned", "quote": s[:240], "source_ref": src})
    facts = [{"text": s[:300], "entity": "", "temporal": "historical" if re.search(r"\b(19|20)\d\d\b", s) and not re.search(r"\bwill\b", s) else "current",
              "quote": s[:240], "source_ref": src} for s, _ in per_sent if re.search(r"\d", s) and 25 < len(s) < 320][:12]
    return {"entities": ents, "relations": rels[:150], "facts": facts, "opinions": [], "risks": [], "variables": []}


def _norm(n: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", n.lower()).strip()


def merge_and_build(parts: list[dict], method: str) -> dict:
    """Merge chunk extractions into a deduplicated knowledge base + graph."""
    ents: dict[str, dict] = {}
    for p in parts:
        for e in p["entities"]:
            k = _norm(e["name"])
            if not k:
                continue
            cur = ents.setdefault(k, {"id": f"n{len(ents)}", "label": e["name"], "type": e["type"], "description": e["description"], "sources": [], "mentions": 0})
            cur["mentions"] += 1
            if e["description"] and len(e["description"]) > len(cur["description"]): cur["description"] = e["description"]
            if e["source"] not in cur["sources"]: cur["sources"].append(e["source"])
    edges: dict[tuple, dict] = {}
    for p in parts:
        for r in p["relations"]:
            a, b = _norm(r["source"]), _norm(r["target"])
            for k, label in ((a, r["source"]), (b, r["target"])):
                if k and k not in ents:
                    ents[k] = {"id": f"n{len(ents)}", "label": label, "type": "topic", "description": "", "sources": [r["source_ref"]], "mentions": 1}
            if not a or not b or a == b:
                continue
            key = (ents[a]["id"], ents[b]["id"], _norm(r["type"]))
            e = edges.setdefault(key, {"source": ents[a]["id"], "target": ents[b]["id"], "type": r["type"], "weight": 0, "evidence": []})
            e["weight"] += 1
            if len(e["evidence"]) < 4: e["evidence"].append({"quote": r["quote"], **r["source_ref"]})
    deg: Counter = Counter()
    for e in edges.values():
        deg[e["source"]] += e["weight"]; deg[e["target"]] += e["weight"]
    nodes = list(ents.values())
    for n in nodes:
        n["degree"] = deg[n["id"]]
    comm = label_propagation([n["id"] for n in nodes], list(edges.values()))
    for n in nodes:
        n["cluster"] = comm.get(n["id"], 0)
    facts = [f for p in parts for f in p["facts"]]
    return {"method": method, "nodes": nodes, "edges": list(edges.values()), "facts": facts,
            "opinions": [o for p in parts for o in p["opinions"]], "risks": [r for p in parts for r in p["risks"]],
            "variables": [v for p in parts for v in p["variables"]]}


def label_propagation(ids: list, edges: list, iters: int = 8) -> dict:
    import random
    rng = random.Random(1)
    adj = defaultdict(list)
    for e in edges:
        adj[e["source"]].append((e["target"], e["weight"])); adj[e["target"]].append((e["source"], e["weight"]))
    lab = {i: i for i in ids}
    order = list(ids)
    for _ in range(iters):
        rng.shuffle(order)
        for i in order:
            sc: Counter = Counter()
            for j, w in adj[i]:
                sc[lab[j]] += w
            if sc:
                lab[i] = sc.most_common(1)[0][0]
    remap = {l: k for k, l in enumerate(dict.fromkeys(lab.values()))}
    return {i: remap[l] for i, l in lab.items()}


async def find_contradictions(provider, facts: list[dict], project_id: str) -> list[dict]:
    """One LLM pass: pairs of facts that conflict. Returns [] when no LLM / nothing found."""
    if len(facts) < 2 or provider is None:
        return []
    numbered = [{"i": i, "text": f["text"], "entity": f["entity"], "doc": f["source_ref"]["doc"], "temporal": f["temporal"]} for i, f in enumerate(facts[:80])]
    import json
    user = ("Identify pairs of statements that contradict each other (different numbers, dates, or claims about the same thing). "
            "Ignore pairs that differ only because they describe different time periods. Statements:\n" + json.dumps(numbered, ensure_ascii=False)
            + '\nReturn JSON: {"contradictions":[{"a":int,"b":int,"explanation":str}]}')
    try:
        data, _ = await provider.chat_json("extraction", [{"role": "user", "content": user}], temperature=0, max_tokens=3000, project_id=project_id)
    except Exception:
        return []
    out = []
    for c in data.get("contradictions", []) or []:
        try:
            a, b = facts[int(c["a"])], facts[int(c["b"])]
            out.append({"a": {"text": a["text"], "source": a["source_ref"]}, "b": {"text": b["text"], "source": b["source_ref"]}, "explanation": str(c.get("explanation", ""))[:300]})
        except (KeyError, ValueError, IndexError, TypeError):
            continue
    return out


async def build_knowledge(provider, docs: list[dict], project_id: str, use_llm: bool, max_chunks: int = 14, progress=None) -> dict:
    work = []
    for d in docs:
        for i, c in enumerate(chunk_text(d["text"])):
            work.append((d, i, c))
    work = work[:max_chunks]
    parts, errors = [], []
    if use_llm:
        sem = asyncio.Semaphore(3)

        async def one(d, i, c):
            async with sem:
                try:
                    return await extract_chunk(provider, c, d, i, project_id)
                except Exception as e:  # noqa
                    errors.append(f"{d['name']}#{i}: {getattr(e, 'kind', e.__class__.__name__)}")
                    return extract_heuristic(c, d, i)
        parts = await asyncio.gather(*[one(*w) for w in work])
        method = "llm" if not errors else f"llm (+heuristic fallback on {len(errors)} chunk(s))"
    else:
        parts = [extract_heuristic(c, d, i) for d, i, c in work]
        method = "heuristic (no LLM)"
    kb = merge_and_build(parts, method)
    kb["contradictions"] = await find_contradictions(provider, kb["facts"], project_id) if use_llm else []
    kb["errors"] = errors
    kb["chunks_processed"], kb["chunks_total"] = len(work), sum(len(chunk_text(d["text"])) for d in docs)
    return kb
