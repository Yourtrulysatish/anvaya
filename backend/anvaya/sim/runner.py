"""Run orchestration: executes an Engine round by round, records normalised events, streams them to subscribers."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

from ..db import Store
from .engine import Agent, Engine, SimConfig
from .writers import LLMWriter, TemplateWriter


class Budget:
    def __init__(self, max_calls: int = 0, max_tokens: int = 0, provider=None):
        self.max_calls, self.max_tokens, self.p = max_calls, max_tokens, provider
        self.start_calls = provider.session_usage["calls"] if provider else 0
        self.start_tokens = (provider.session_usage["prompt"] + provider.session_usage["completion"]) if provider else 0

    def used(self):
        u = self.p.session_usage
        return u["calls"] - self.start_calls, u["prompt"] + u["completion"] - self.start_tokens

    def exhausted(self) -> bool:
        if not self.p:
            return False
        c, t = self.used()
        return bool((self.max_calls and c >= self.max_calls) or (self.max_tokens and t >= self.max_tokens))


class SimulationRun:
    def __init__(self, agents: list[Agent], cfg: SimConfig, *, store: Optional[Store] = None, provider=None,
                 use_llm: bool = False, project_id: str = None, budget: Optional[Budget] = None, round_delay: float = 0.0):
        self.cfg, self.store, self.project_id = cfg, store, project_id
        self.engine = Engine(agents, cfg)
        self.use_llm = use_llm and provider is not None
        self.provider = provider
        self.budget = budget or Budget(provider=provider)
        self.writer = LLMWriter(self.engine, provider, project_id, budget=self.budget) if self.use_llm else TemplateWriter(self.engine)
        self.round_delay = round_delay
        self.events: list[dict] = []
        self._pending: list[dict] = []
        self.seq = 0
        self.status = "created"       # created | running | paused | stopped | completed | failed
        self.current_round = 0
        self._stop = False
        self._resume = asyncio.Event(); self._resume.set()
        self.subscribers: list[asyncio.Queue] = []
        self.started_at = None
        self.error: Optional[str] = None
        self._rid = 0

    # ---------------------------------------------------------------- events
    def emit(self, type: str, **f) -> str:
        if type == "__finalize__":
            return ""
        f.pop("deferred", None)
        ev = {"id": f"{self.cfg.simulation_id}:{self.seq}", "seq": self.seq, "simulation_id": self.cfg.simulation_id,
              "round": self.current_round, "type": type, "source_agent": f.pop("source", None), "target_agent": f.pop("target", None),
              "agents": f.pop("agents", []), "topic": f.pop("topic", None), "content": f.pop("content", ""),
              "content_source": f.pop("content_source", ""), "reason": f.pop("reason", ""), "result": f.pop("result", {}),
              "state_changes": f.pop("state_changes", {}), "timestamp": datetime.now(timezone.utc).isoformat(),
              "provenance": {"engine": "anvaya-native", "mode": self.cfg.mode, "seed": self.cfg.seed}}
        if "cause" in f:
            ev["cause_event"] = f.pop("cause")
        self.seq += 1
        self._pending.append(ev)
        return ev["id"]

    def _flush(self):
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        self.events.extend(batch)
        if self.store:
            self.store.append_events(self.cfg.simulation_id, batch)
        for q in list(self.subscribers):
            q.put_nowait(batch)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q):
        if q in self.subscribers:
            self.subscribers.remove(q)

    # ---------------------------------------------------------------- control
    def pause(self):
        if self.status == "running":
            self.status = "paused"; self._resume.clear()

    def resume(self):
        if self.status == "paused":
            self.status = "running"; self._resume.set()

    def stop(self):
        self._stop = True; self._resume.set()

    # ---------------------------------------------------------------- main loop
    async def run(self):
        e, cfg = self.engine, self.cfg
        self.status, self.started_at = "running", time.time()
        try:
            self.current_round = 0
            self.emit("sim_start", content=cfg.title or "Simulation started", content_source="engine",
                      result={"agents": len(e.agents), "rounds": cfg.rounds, "topics": [t.__dict__ for t in e.topics.values()],
                              "edges": e.edges(), "mode": cfg.mode, "llm": self.use_llm,
                              "llm_agents_per_round": cfg.llm_agents_per_round, "shocks": [s.to_dict() for s in cfg.shocks]})
            self._flush()
            for rnd in range(1, cfg.rounds + 1):
                if self._stop:
                    break
                if self.status == "paused" or not self._resume.is_set():
                    self.emit("sim_pause", content=f"Paused before round {rnd}", content_source="engine"); self._flush()
                    await self._resume.wait()
                    if self._stop:
                        break
                    self.emit("sim_resume", content=f"Resumed at round {rnd}", content_source="engine"); self._flush()
                self.current_round = rnd
                self.emit("round_start", content=f"Round {rnd}", content_source="engine", result={"round": rnd})
                e.apply_shocks(rnd, self.emit)
                intents = e.plan_round(rnd)
                if self.use_llm:
                    await self.writer.deliberate(intents, rnd, cfg.llm_agents_per_round)
                await self.writer.write(intents, rnd)
                e.apply(intents, rnd, self.emit)
                if rnd % 3 == 0 or rnd == 1:
                    e.update_groups(rnd, self.emit)
                m = e.metrics()
                m["active_agents"] = len({it.source for it in intents if it.type != "ignore"})
                m["round_interactions"] = sum(1 for it in intents if it.type != "ignore")
                infl = e.influence_scores()
                m["top_influencers"] = [{"agent": i, "score": s} for i, s in sorted(infl.items(), key=lambda kv: -kv[1])[:5]]
                warnings = getattr(self.writer, "warnings", [])
                self.emit("round_end", content=f"Round {rnd} complete", content_source="engine", result=m)
                if warnings:
                    self.emit("error", content="; ".join(warnings[-3:]), content_source="engine", result={"level": "warning"})
                    warnings.clear()
                self._flush()
                if self.round_delay:
                    await asyncio.sleep(self.round_delay)
                else:
                    await asyncio.sleep(0)
            final = e.metrics()
            final["influence"] = {str(k): v for k, v in e.influence_scores().items()}
            final["final_opinions"] = {str(i): round(a.opinions.get(final["topic"], 0), 3) for i, a in e.agents.items()}
            final["agent_groups"] = {str(i): a.group for i, a in e.agents.items()}
            final["group_names"] = {str(k): v for k, v in e.group_names.items()}
            self.status = "stopped" if self._stop else "completed"
            final["status"] = self.status
            if self.use_llm:
                c, t = self.budget.used()
                final["llm_usage"] = {"calls": c, "tokens": t, "model": getattr(self.writer, "model", None)}
            self.emit("sim_end", content=f"Simulation {self.status}", content_source="engine", result=final)
            self._flush()
        except Exception as ex:  # noqa
            self.status, self.error = "failed", f"{ex.__class__.__name__}: {ex}"
            self.emit("error", content=self.error, content_source="engine", result={"level": "fatal"})
            self._flush()
        finally:
            for q in list(self.subscribers):
                q.put_nowait(None)
