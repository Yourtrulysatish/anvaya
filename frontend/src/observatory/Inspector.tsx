import { useMemo, useState } from 'react'
import { X, MessageSquare } from 'lucide-react'
import type { AgentInfo } from '../lib/types'
import type { Playback } from '../lib/simState'
import { INTERACTION_TYPES } from '../lib/types'
import { opinionColor } from './renderer'
import { headline, TYPE_META } from './format'

interface Props {
  pb: Playback; agentId: number; agents: AgentInfo[]; topic: string; tick: number; synthetic: boolean
  interview?: (agentId: number, q: string) => Promise<{ answer: string; model?: string }>
  onClose: () => void; onSelectAgent: (id: number) => void
}

export function Inspector({ pb, agentId, agents, topic, tick, synthetic, interview, onClose, onSelectAgent }: Props) {
  const a = agents[agentId], st = pb.state
  const [q, setQ] = useState(''); const [chat, setChat] = useState<{ q: string; a: string; model?: string }[]>([]); const [busy, setBusy] = useState(false)

  const { history, decisions, memory, trajectory } = useMemo(() => {
    const idxs = (pb.byAgent.get(agentId) ?? []).filter(i => i < tick)
    const evs = idxs.map(i => pb.events[i])
    const history = evs.filter(e => INTERACTION_TYPES.includes(e.type)).slice(-14).reverse()
    const decisions = evs.filter(e => e.source_agent === agentId && INTERACTION_TYPES.includes(e.type)).slice(-6).reverse()
    const memory = evs.filter(e => e.source_agent !== agentId && INTERACTION_TYPES.includes(e.type) && e.content).slice(-6).reverse()
    const traj: number[] = [a.opinions[topic] ?? 0]
    for (const e of evs) { const c = e.state_changes?.opinion?.[String(agentId)]; if (c && c.topic === topic) traj.push(c.to) }
    return { history, decisions, memory, trajectory: traj }
  }, [pb, agentId, tick, a, topic])

  const ties = useMemo(() => {
    const out: [number, number][] = []
    for (let j = 0; j < st.n; j++) { if (j === agentId) continue; const w = Math.max(st.ties.get(agentId * st.n + j) ?? 0, st.ties.get(j * st.n + agentId) ?? 0); if (Math.abs(w) >= 0.15) out.push([j, w]) }
    return out.sort((x, y) => y[1] - x[1]).slice(0, 7)
  }, [st, agentId, tick])

  const op = st.opinion[agentId]
  const ask = async () => {
    if (!interview || !q.trim()) return
    setBusy(true)
    try { const r = await interview(agentId, q); setChat(c => [...c, { q, a: r.answer, model: r.model }]); setQ('') }
    catch (e: any) { setChat(c => [...c, { q, a: `⚠ ${e.message ?? 'interview failed'}` }]) }
    finally { setBusy(false) }
  }

  return (
    <aside className="absolute bottom-24 left-4 top-4 z-20 flex w-[22rem] max-w-[calc(100%-2rem)] flex-col rounded-2xl panel reveal md:left-[17.5rem]">
      <div className="flex items-start justify-between gap-3 border-b hairline p-4">
        <div>
          <div className="flex items-center gap-2"><i className="h-2.5 w-2.5 rounded-full" style={{ background: opinionColor(op) }} /><h3 className="text-base font-semibold">{a.name}</h3></div>
          <div className="mt-0.5 text-xs text-silver-500">{a.segment} · {a.age} · {a.occupation}{a.location ? ` · ${a.location}` : ''}</div>
          <div className="mt-2 inline-flex rounded border border-violet/30 bg-violet/10 px-1.5 py-0.5 font-mono text-[9.5px] tracking-widest text-violet-soft">SIMULATED AGENT · NOT A REAL PERSON</div>
        </div>
        <button onClick={onClose} aria-label="Close inspector" className="rounded-md p-1 text-silver-500 hover:text-white"><X size={16} /></button>
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto p-4 text-[13px]">
        <p className="leading-relaxed text-silver-300">{a.persona}</p>
        <section>
          <div className="label mb-2">Live state · from events</div>
          <div className="grid grid-cols-3 gap-2 font-mono text-xs">
            <Box k="Opinion" v={op.toFixed(2)} c={opinionColor(op)} /><Box k="Sentiment" v={st.sentiment[agentId].toFixed(2)} />
            <Box k="Influence" v={st.influence(agentId).toFixed(2)} sub={`base ${a.influence.toFixed(2)}`} />
            <Box k="Group" v={st.group[agentId] >= 0 ? String(st.group[agentId] + 1) : '—'} /><Box k="Acts" v={String(st.actions[agentId])} /><Box k="Active" v={st.lastActiveRound[agentId] >= 0 ? `R${st.lastActiveRound[agentId]}` : 'not yet'} />
          </div>
          {st.group[agentId] >= 0 && <div className="mt-1.5 text-[11px] text-silver-500">{st.groupNames.get(st.group[agentId])}</div>}
          <Traj values={trajectory} />
        </section>
        <section><div className="label mb-1.5">Goals</div><ul className="list-disc space-y-0.5 pl-4 text-silver-300">{a.goals.map(g => <li key={g}>{g}</li>)}</ul></section>
        <section><div className="label mb-1.5">Beliefs</div><ul className="list-disc space-y-0.5 pl-4 text-silver-300">{a.beliefs.map(g => <li key={g}>{g}</li>)}</ul></section>
        <section>
          <div className="label mb-1.5">Personality & sensitivities <span className="normal-case tracking-normal text-silver-700">({a.attributes_basis === 'assumption' ? 'simulation assumptions' : a.attributes_basis})</span></div>
          <div className="space-y-1">{[...Object.entries(a.traits), ...Object.entries(a.sensitivities)].map(([k, v]) => (
            <div key={k} className="flex items-center gap-2"><span className="w-24 text-silver-500">{k}</span><div className="h-1 flex-1 rounded bg-ink-700"><div className="h-1 rounded bg-violet-soft" style={{ width: `${v * 100}%` }} /></div><span className="w-8 text-right font-mono text-[10px] text-silver-500">{v.toFixed(2)}</span></div>))}</div>
        </section>
        <section>
          <div className="label mb-1.5">Relationships</div>
          {ties.length === 0 ? <div className="text-silver-500">None above threshold yet.</div> : <div className="space-y-1">{ties.map(([j, w]) => (
            <button key={j} onClick={() => onSelectAgent(j)} className="flex w-full items-center gap-2 text-left hover:text-white"><i className="h-1.5 w-1.5 rounded-full" style={{ background: opinionColor(st.opinion[j]) }} /><span className="flex-1 truncate text-silver-300">{agents[j].name}</span><div className="h-1 w-16 rounded bg-ink-700"><div className="h-1 rounded bg-cyan" style={{ width: `${Math.min(1, Math.abs(w)) * 100}%` }} /></div><span className="w-9 text-right font-mono text-[10px] text-silver-500">{w.toFixed(2)}</span></button>))}</div>}
        </section>
        <section>
          <div className="label mb-1.5">Decisions & reasons</div>
          {decisions.length === 0 ? <div className="text-silver-500">No actions yet.</div> : <div className="space-y-2">{decisions.map(e => (
            <div key={e.id} className="rounded-lg border hairline p-2"><div className="font-mono text-[10px]" style={{ color: TYPE_META[e.type].color }}>R{e.round} · {TYPE_META[e.type].label}{e.result?.decided_by === 'llm' ? ' · LLM-decided' : ''}</div><div className="mt-0.5 text-silver-300">{e.reason}</div></div>))}</div>}
        </section>
        <section>
          <div className="label mb-1.5">Conversation history</div>
          {history.length === 0 ? <div className="text-silver-500">No interactions yet.</div> : <div className="space-y-2">{history.map(e => (
            <div key={e.id}><div className="font-mono text-[10px] text-silver-700">R{e.round} · {headline(e, agents)}</div><div className="text-silver-300">{e.content}</div></div>))}</div>}
        </section>
        <section>
          <div className="label mb-1.5">Recent memory <span className="normal-case tracking-normal text-silver-700">(what they have heard, derived from recorded events)</span></div>
          {memory.length === 0 ? <div className="text-silver-500">Nothing heard yet.</div> : <ul className="space-y-1.5">{memory.map(e => <li key={e.id} className="text-silver-300"><span className="text-silver-500">{agents[e.source_agent ?? 0]?.name}:</span> {e.content}</li>)}</ul>}
        </section>
        <section>
          <div className="label mb-1.5">Interview this agent</div>
          {interview ? (
            <div className="space-y-2">
              {chat.map((c, i) => <div key={i} className="space-y-1"><div className="text-silver-500">You: {c.q}</div><div className="rounded-lg bg-ink-800 p-2 text-silver-300">{c.a}<div className="mt-1 font-mono text-[9.5px] text-violet-soft">simulated answer{c.model ? ` · ${c.model}` : ''}</div></div></div>)}
              <div className="flex gap-2"><input className="input !py-1.5" value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && ask()} placeholder="Ask about their view…" /><button className="btn !px-2.5" onClick={ask} disabled={busy}><MessageSquare size={14} /></button></div>
            </div>
          ) : <div className="rounded-lg border hairline p-2.5 text-[12px] leading-relaxed text-silver-500">{synthetic ? 'Interviews call the live language model with this agent’s persona and recorded memory, so they are disabled in the static DEMO. Run a live simulation to enable them.' : 'Interviews need the live backend.'}</div>}
        </section>
      </div>
    </aside>
  )
}

function Box({ k, v, c, sub }: { k: string; v: string; c?: string; sub?: string }) {
  return <div className="rounded-lg border hairline bg-ink-900/60 p-2"><div className="label !text-[9px]">{k}</div><div className="mt-0.5 text-sm" style={c ? { color: c } : {}}>{v}</div>{sub && <div className="text-[9px] text-silver-700">{sub}</div>}</div>
}
function Traj({ values }: { values: number[] }) {
  if (values.length < 2) return <div className="mt-2 text-[11px] text-silver-700">Opinion unchanged so far.</div>
  const W = 290, H = 38
  const d = values.map((v, i) => `${i ? 'L' : 'M'}${(i / (values.length - 1)) * W},${H / 2 - v * (H / 2 - 3)}`).join('')
  return <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="mt-2" aria-label="Opinion trajectory"><line x1="0" x2={W} y1={H / 2} y2={H / 2} stroke="#262b37" strokeDasharray="2 3" /><path d={d} fill="none" stroke="#8B5CF6" strokeWidth="1.6" /></svg>
}
