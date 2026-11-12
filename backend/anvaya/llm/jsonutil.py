"""Tolerant JSON extraction. FreeModel's `json_object` mode was observed to wrap output in ```json fences."""
from __future__ import annotations

import json
import re

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)


def extract_json(text: str):
    if text is None:
        raise ValueError("empty model output")
    t = text.strip()
    m = _FENCE.search(t)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost balanced {...} or [...]
    for open_c, close_c in (("{", "}"), ("[", "]")):
        s = t.find(open_c)
        if s == -1:
            continue
        depth, in_str, esc = 0, False, False
        for i in range(s, len(t)):
            ch = t[i]
            if in_str:
                if esc: esc = False
                elif ch == "\\": esc = True
                elif ch == '"': in_str = False
                continue
            if ch == '"': in_str = True
            elif ch == open_c: depth += 1
            elif ch == close_c:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[s:i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError("no valid JSON found in model output")
