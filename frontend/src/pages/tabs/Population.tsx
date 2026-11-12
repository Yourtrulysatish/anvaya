import { useState } from 'react'
import { api, waitJob } from '../../lib/api'
import { Card, ErrorNote, Spinner, useAsync } from '../../components/ui'
import { useProject } from '../Project'

export function PopulationTab() {
  const { id, project, reload } = useProject()
  const health = useAsync(() => api('/health'), [])
  const [desc, setDesc] = useState(project.situation ? `Simulate the people affected by this situation: ${project.situation}`.slice(0, 600) : '')
  const [n, setN] = useState(120); const [useLlm, setUseLlm] = useState(true); const [busy, setBusy] = useState(''); const [err, setErr] = useState<unknown>(null)
  const [sel, setSel] = useState<string | null>(project.populations[0]?.id ?? null)
  const pop = useAsync(() => (sel ? api(`/projects/${id}/populations/${sel}`) : Promise.resolve(null)), [sel, id])
  const [edits, setEdits] = useState<Record<number, any>>({}); const [removed, setRemoved] = useState<Set<number>>(new Set()); const [open, setOpen] = useState<number | null>(null)
  const llm = health.data?.llm_configured

  const generate = async () => {
    setBusy('Starting…'); setErr(null)
    try { const j = await api(`/projects/${id}/populations/generate`, { body: { description: desc, n, use_llm: useLlm && !!llm } }); const r = await waitJob(j.id, p => setBusy(p.message)); setSel(r.result.population_id); reload() }
    catch (e) { setErr(e) } finally { setBusy('') }
  }
  const save = async () => {
    setBusy('Saving…'); setErr(null)
    try { await api(`/projects/${id}/populations/${sel}`, { method: 'PUT', body: { agents: Object.values(edits), remove: [...removed] } }); setEdits({}); setRemoved(new Set()); pop.reload(); reload() }
    catch (e) { setErr(e) } finally { setBusy('') }
  }
  const p = pop.data
  const edit = (a: any, patch: any) => setEdits(e => ({ ...e, [a.id]: { id: a.id, name: a.name, persona: a.persona, goals: a.goals, beliefs: a.beliefs, activity: a.activity, influence: a.influence, opinions: a.opinions, traits: a.traits, ...e[a.id], ...patch } }))
  const dirty = Object.keys(edits).length > 0 || removed.size > 0
  const topic = p?.spec.topics[0]?.id
  return (
    <div className="space-y-5">
      <Card className="space-y-3">
        <div className="label">Describe the population in plain English</div>
        <textarea className="input min-h-20" value={desc} onChange={e => setDesc(e.target.value)} placeholder="Simulate 300 Indian smartphone consumers, including students, professionals, technology enthusiasts, price-sensitive customers and brand loyalists." />
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-silver-300">Agents <input type="range" min={20} max={400} step={10} value={n} onChange={e => setN(+e.target.value)} /> <span className="w-10 font-mono">{n}</span></label>
          {llm && <label className="flex items-center gap-2 text-xs text-silver-500"><input type="checkbox" checked={useLlm} onChange={e => setUseLlm(e.target.checked)} />Use language model (richer personas)</label>}
          <button className="btn btn-primary" disabled={desc.trim().length < 3 || !!busy} onClick={generate}>Generate population</button>{busy && <Spinner label={busy} />}
        </div>
        <p className="text-[11px] text-silver-700">Smaller populations cost less. Anything not stated in your evidence is labelled a simulation assumption.</p>
        <ErrorNote error={err} />
      </Card>
      {project.populations.length > 1 && <div className="flex flex-wrap gap-2">{project.populations.map((x: any) => <button key={x.id} onClick={() => { setSel(x.id); setEdits({}); setRemoved(new Set()) }} className={`chip ${sel === x.id ? 'chip-on' : ''}`}>{x.title} · {x.n}</button>)}</div>}
      {p && (<>
        <Card className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2"><div><div className="label">Segments · basis: {p.basis}{p.edited_by_user ? ' · edited by you' : ''}</div><div className="text-lg">{p.spec.title}</div></div>
            <div className="text-xs text-silver-500">Topic: {p.spec.topics.map((t: any) => t.label).join('; ')}</div></div>
          {p.warnings?.map((w: string) => <div key={w} className="rounded-lg border border-gold/30 bg-gold/10 px-3 py-2 text-[13px] text-gold">{w}</div>)}
          <div className="space-y-2">{p.segments.map((s: any) => <div key={s.name}><div className="flex justify-between text-sm"><span>{s.name} <span className="text-silver-500">— {s.description}</span></span><span className="font-mono text-xs">{s.count}</span></div><div className="mt-1 h-1.5 rounded bg-ink-700"><div className="h-1.5 rounded bg-violet" style={{ width: `${(s.count / p.n) * 100}%` }} /></div></div>)}</div>
          <details className="text-sm"><summary className="cursor-pointer text-silver-300">Simulation assumptions ({p.assumptions.length})</summary><ul className="mt-2 list-disc space-y-1 pl-5 text-silver-500">{p.assumptions.map((a: string) => <li key={a}>{a}</li>)}</ul></details>
        </Card>
        <Card className="space-y-2">
          <div className="flex items-center justify-between"><div className="label">Agents ({p.n - removed.size}) · inspect & edit before launching</div>{dirty && <button className="btn btn-primary" onClick={save} disabled={!!busy}>Save changes</button>}</div>
          <div className="divide-y divide-line">{p.agents.map((a: any) => {
            const e = edits[a.id] ?? {}; const gone = removed.has(a.id)
            return (
              <div key={a.id} className={`py-2 text-sm ${gone ? 'opacity-30' : ''}`}>
                <div className="flex items-center gap-3"><button className="flex-1 text-left" onClick={() => setOpen(open === a.id ? null : a.id)}><b>{e.name ?? a.name}</b> <span className="text-silver-500">· {a.segment} · {a.age} · {a.occupation}</span>
                  <span className="ml-2 font-mono text-[11px] text-silver-500">opinion {(e.opinions ?? a.opinions)[topic]?.toFixed(2)} · influence {(e.influence ?? a.influence).toFixed(2)}</span></button>
                  <span className="rounded border border-line px-1.5 font-mono text-[9px] text-silver-500">{e.name ? 'EDITED' : a.attributes_basis.toUpperCase()}</span>
                  <button className="text-xs text-silver-500 hover:text-rose" onClick={() => setRemoved(r => { const n = new Set(r); n.has(a.id) ? n.delete(a.id) : n.add(a.id); return n })}>{gone ? 'restore' : 'remove'}</button></div>
                {open === a.id && !gone && (
                  <div className="mt-2 grid gap-2 rounded-lg bg-ink-850 p-3 md:grid-cols-2">
                    <label className="label">Name<input className="input mt-1" value={e.name ?? a.name} onChange={ev => edit(a, { name: ev.target.value })} /></label>
                    <label className="label">Opinion on topic ({p.spec.topics[0].neg_label} ← → {p.spec.topics[0].pos_label})<input type="range" min={-1} max={1} step={0.05} className="mt-2 w-full" value={(e.opinions ?? a.opinions)[topic]} onChange={ev => edit(a, { opinions: { ...(e.opinions ?? a.opinions), [topic]: +ev.target.value } })} /></label>
                    <label className="label md:col-span-2">Persona<textarea className="input mt-1 min-h-16" value={e.persona ?? a.persona} onChange={ev => edit(a, { persona: ev.target.value })} /></label>
                    <label className="label">Goals (one per line)<textarea className="input mt-1" value={(e.goals ?? a.goals).join('\n')} onChange={ev => edit(a, { goals: ev.target.value.split('\n').filter(Boolean) })} /></label>
                    <label className="label">Beliefs (one per line)<textarea className="input mt-1" value={(e.beliefs ?? a.beliefs).join('\n')} onChange={ev => edit(a, { beliefs: ev.target.value.split('\n').filter(Boolean) })} /></label>
                    <label className="label">Activity<input type="range" min={0.05} max={0.9} step={0.05} className="mt-2 w-full" value={e.activity ?? a.activity} onChange={ev => edit(a, { activity: +ev.target.value })} /></label>
                    <label className="label">Influence<input type="range" min={0} max={1} step={0.05} className="mt-2 w-full" value={e.influence ?? a.influence} onChange={ev => edit(a, { influence: +ev.target.value })} /></label>
                  </div>)}
              </div>)
          })}</div>
        </Card>
      </>)}
    </div>
  )
}
