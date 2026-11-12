import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, waitJob } from '../../lib/api'
import { Card, ErrorNote, Spinner } from '../../components/ui'
import { IntervalBar, LineChart } from '../../components/Charts'
import { useProject } from '../Project'

const KIND_COLOR: Record<string, string> = { baseline: '#8A93A3', optimistic: '#3DDCFF', pessimistic: '#FF7A59', alternative: '#A78BFA' }

export function ScenarioCompare({ scenarios }: { scenarios: any[] }) {
  const done = scenarios.filter(s => s.results)
  if (!done.length) return null
  const base = done[0].results.baseline_summary
  const rows = [{ name: 'Baseline', kind: 'baseline', s: base }, ...done.filter(s => s.shocks.length).map(s => ({ name: s.name, kind: s.kind, s: s.results.summary }))]
  const metric = (k: string, label: string, lo = -1, hi = 1, fmt = (v: number) => v.toFixed(2)) => (
    <div><div className="label mb-2">{label}</div><div className="space-y-2">{rows.map(r => <div key={r.name} className="grid grid-cols-[8rem_1fr_9rem] items-center gap-3 text-xs"><span className="truncate" style={{ color: KIND_COLOR[r.kind] }}>{r.name}</span>
      <IntervalBar mean={r.s[k].mean} lo={r.s[k].p05} hi={r.s[k].p95} min={lo} max={hi} color={KIND_COLOR[r.kind]} /><span className="font-mono text-silver-500">{fmt(r.s[k].mean)} <span className="text-silver-700">[{fmt(r.s[k].p05)}, {fmt(r.s[k].p95)}]</span></span></div>)}</div></div>)
  return (
    <Card className="space-y-5"><div className="label">Side-by-side comparison · Monte Carlo ({base.mean_opinion.n} replicates each, bars show 5–95% range)</div>
      {metric('mean_opinion', 'Mean opinion (−1 against … +1 in favour)')}{metric('support_share', 'Share of agents in support', 0, 1, v => `${(v * 100).toFixed(0)}%`)}{metric('oppose_share', 'Share of agents opposed', 0, 1, v => `${(v * 100).toFixed(0)}%`)}{metric('polarisation', 'Polarisation (0 consensus … 1 split)', 0, 1)}
      <p className="text-[11px] leading-relaxed text-silver-700">These intervals describe randomness inside the simulation model, not uncertainty about the real world. Effects depend on the unverified assumptions listed on each scenario.</p></Card>
  )
}

export function ScenariosTab() {
  const { id, project, reload } = useProject()
  const [pop, setPop] = useState(project.populations[0]?.id ?? ''); const [prompt, setPrompt] = useState(''); const name = ''; const [kind, setKind] = useState('alternative')
  const [busy, setBusy] = useState(''); const [err, setErr] = useState<unknown>(null); const [edits, setEdits] = useState<Record<string, any[]>>({})
  const sc: any[] = project.scenarios
  const run = async (label: string, fn: () => Promise<any>) => { setBusy(label); setErr(null); try { await fn(); reload() } catch (e) { setErr(e) } finally { setBusy('') } }
  const create = (p: string, n: string, k: string) => api(`/projects/${id}/scenarios`, { body: { population_id: pop, name: n || p.slice(0, 50), kind: k, prompt: p, rounds: 20 } })
  const hasBaseline = sc.some(s => s.kind === 'baseline')
  if (!project.populations.length) return <Card className="text-sm text-silver-500">Generate a population first — scenarios are tested against it.</Card>
  return (
    <div className="space-y-5">
      <Card className="space-y-3"><div className="label">Scenario Lab</div>
        <div className="flex flex-wrap gap-2"><select className="input !w-auto" value={pop} onChange={e => setPop(e.target.value)}>{project.populations.map((p: any) => <option key={p.id} value={p.id}>{p.title} · {p.n}</option>)}</select>
          {!hasBaseline && <button className="btn" disabled={!!busy} onClick={() => run('Creating baseline…', () => create('No external change.', 'Baseline', 'baseline'))}>Add baseline</button>}
          <button className="btn" disabled={!!busy} onClick={() => run('Proposing scenarios…', async () => { const r = await api(`/projects/${id}/scenarios/propose`, { body: { population_id: pop, rounds: 20 } }); for (const s of r.scenarios) if (!(s.kind === 'baseline' && hasBaseline)) await create(s.prompt, s.name, s.kind) })}>Propose optimistic / pessimistic / alternative</button></div>
        <div className="grid gap-2 md:grid-cols-[1fr_9rem_8rem]"><input className="input" placeholder="What if the competitor reduces its smartphone price by 20%?" value={prompt} onChange={e => setPrompt(e.target.value)} /><select className="input" value={kind} onChange={e => setKind(e.target.value)}>{['optimistic', 'pessimistic', 'alternative'].map(k => <option key={k}>{k}</option>)}</select>
          <button className="btn btn-primary" disabled={!prompt.trim() || !!busy} onClick={() => run('Interpreting assumption…', async () => { await create(prompt, name, kind); setPrompt('') })}>Add scenario</button></div>
        {busy && <Spinner label={busy} />}<ErrorNote error={err} />
      </Card>
      {sc.map(s => {
        const shocks = edits[s.id] ?? s.shocks
        return (
          <Card key={s.id} className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2"><div><span className="chip mr-2" style={{ color: KIND_COLOR[s.kind] }}>{s.kind}</span><b>{s.name}</b></div>
              <div className="flex gap-2">{s.results?.simulation_id && <Link className="btn !py-1" to={`/projects/${id}/simulation?sim=${s.results.simulation_id}`}>Watch replay</Link>}
                <button className="btn btn-primary !py-1" disabled={!!busy} onClick={() => run(`Running ${s.name} (paired replicates)…`, async () => { if (edits[s.id]) { await api(`/scenarios/${s.id}`, { method: 'PUT', body: { shocks: edits[s.id] } }); setEdits(e => { const n = { ...e }; delete n[s.id]; return n }) } const j = await api(`/scenarios/${s.id}/run`, { body: { replicates: 8 } }); await waitJob(j.id, p => setBusy(`${s.name}: ${p.message}`)) })}>{s.results ? 'Re-run' : 'Run'}</button>
                <button className="btn !py-1 text-silver-500" onClick={() => run('Deleting…', () => api(`/scenarios/${s.id}`, { method: 'DELETE' }))}>Delete</button></div></div>
            <p className="text-sm text-silver-300">{s.prompt}</p>
            {shocks.length > 0 && <div className="rounded-lg border hairline p-3"><div className="label mb-2">Changed assumptions <span className="normal-case tracking-normal text-silver-700">· interpreted by {s.interpretation} · editable</span></div>
              {shocks.map((k: any, i: number) => <div key={i} className="mb-2 text-[13px]"><div>Round {k.round}: {k.label}</div>{k.effects.map((e: any, j: number) => <div key={j} className="mt-1 flex items-center gap-2 text-xs text-silver-500"><span className="w-40 truncate">{e.segment === '*' ? 'all segments' : e.segment}{e.sensitivity ? ` × ${e.sensitivity}` : ''}</span>
                <input type="range" min={-0.6} max={0.6} step={0.05} className="flex-1" value={e.delta} onChange={ev => setEdits(ed => ({ ...ed, [s.id]: shocks.map((kk: any, ii: number) => (ii === i ? { ...kk, effects: kk.effects.map((ee: any, jj: number) => (jj === j ? { ...ee, delta: +ev.target.value } : ee)) } : kk)) }))} /><span className="w-12 font-mono">{e.delta >= 0 ? '+' : ''}{e.delta.toFixed(2)}</span></div>)}</div>)}
              {s.assumptions?.length > 0 && <ul className="mt-2 list-disc space-y-0.5 pl-5 text-[12px] text-silver-500">{s.assumptions.map((a: string) => <li key={a}>{a}</li>)}</ul>}</div>}
            {s.results?.comparison && (() => { const c = s.results.comparison; return (
              <div className="space-y-3"><div className="label">Differences from baseline · {c.pairs} paired replicates</div>
                <div className="grid gap-2 md:grid-cols-3">{(['mean_opinion', 'support_share', 'polarisation', 'oppose_share', 'groups', 'max_cascade'] as const).map(k => { const d = c.differences[k]; return (
                  <div key={k} className="rounded-lg border hairline p-2.5"><div className="label">{k.replace(/_/g, ' ')}</div><div className="font-mono text-lg">{d.mean_diff >= 0 ? '+' : ''}{d.mean_diff}</div><div className="font-mono text-[10.5px] text-silver-500">95%: {d.ci95[0]} … {d.ci95[1]}</div><div className={`text-[10.5px] ${d.distinguishable_from_zero ? 'text-cyan' : 'text-silver-700'}`}>{d.distinguishable_from_zero ? 'distinguishable from zero' : 'within noise'}</div></div>) })}</div>
                <div><div className="label mb-1">Segment reactions (change in mean opinion vs baseline)</div>{Object.entries(c.segment_differences).map(([seg, d]: any) => <div key={seg} className="grid grid-cols-[10rem_1fr_5rem] items-center gap-3 text-xs"><span className="truncate">{seg}</span><IntervalBar mean={d.mean_diff} lo={d.ci95[0]} hi={d.ci95[1]} min={-0.6} max={0.6} /><span className="font-mono text-silver-500">{d.mean_diff >= 0 ? '+' : ''}{d.mean_diff}</span></div>)}</div>
                {s.results.sensitivity && <div><div className="label mb-1">Sensitivity: effect size × → mean opinion</div><LineChart height={120} yMin={-1} yMax={1} xLabels={s.results.sensitivity.map((x: any) => `${x.scale}×`)} series={[{ label: 'mean opinion', color: '#8B5CF6', values: s.results.sensitivity.map((x: any) => x.mean_opinion) }, { label: 'support share', color: '#3DDCFF', values: s.results.sensitivity.map((x: any) => x.support_share * 2 - 1) }]} /><p className="text-[10.5px] text-silver-700">Support share is rescaled to −1…+1 for display. 0× = scenario effect removed.</p></div>}
                <p className="text-[11.5px] leading-relaxed text-silver-500">{c.method} {c.uncertainty}</p></div>) })()}
          </Card>)
      })}
      <ScenarioCompare scenarios={sc} />
    </div>
  )
}
