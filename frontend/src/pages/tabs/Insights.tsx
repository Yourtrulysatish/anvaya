import { useState } from 'react'
import { api } from '../../lib/api'
import { Card, ErrorNote, KindTag, Spinner, useAsync } from '../../components/ui'
import { LineChart } from '../../components/Charts'
import { useProject } from '../Project'

export function AnalysisView({ a }: { a: any }) {
  const tr = a.trajectory
  const marks = a.shock_responses.map((s: any) => ({ x: s.round - 1, label: 'external event' }))
  return (
    <div className="space-y-4">
      <Card><div className="label mb-2"><KindTag kind="SIMULATION" />Opinion and polarisation by round</div>
        <LineChart series={[{ label: 'mean opinion', color: '#3DDCFF', values: tr.map((t: any) => t.mean_opinion) }, { label: 'polarisation', color: '#A78BFA', values: tr.map((t: any) => t.polarisation) }, { label: 'consensus', color: '#6EE7B7', values: tr.map((t: any) => t.consensus) }]} xLabels={tr.map((t: any) => t.round)} marks={marks} />
        {a.shock_responses.map((s: any) => <p key={s.round} className="mt-2 text-xs text-silver-300">Round {s.round}: “{s.label}” — mean opinion {s.mean_before.toFixed(2)} → {s.mean_after.toFixed(2)} ({s.delta >= 0 ? '+' : ''}{s.delta.toFixed(2)}).{s.assumption ? ' Effect size is an unverified scenario assumption.' : ''}</p>)}</Card>
      <div className="grid gap-4 md:grid-cols-2">
        <Card><div className="label mb-2"><KindTag kind="SIMULATION" />Segments (diagnostic)</div><table className="w-full text-xs"><thead className="label"><tr><th className="text-left">Segment</th><th>Start</th><th>End</th><th>Shift</th></tr></thead><tbody className="font-mono">{a.segments.map((s: any) => <tr key={s.segment} className="border-t hairline"><td className="py-1 font-sans">{s.segment} <span className="text-silver-700">n={s.n}</span></td><td className="text-center">{s.start.toFixed(2)}</td><td className="text-center">{s.end.toFixed(2)}</td><td className={`text-center ${s.shift > 0 ? 'text-cyan' : 'text-coral'}`}>{s.shift >= 0 ? '+' : ''}{s.shift.toFixed(2)}</td></tr>)}</tbody></table></Card>
        <Card><div className="label mb-2"><KindTag kind="SIMULATION" />Most influential agents</div>{a.top_influencers.map((t: any) => <div key={t.agent} className="flex items-center justify-between border-t py-1 text-xs hairline first:border-0"><span>{t.name} <span className="text-silver-500">· {t.segment}</span></span><span className="font-mono">{t.score.toFixed(2)}</span></div>)}<p className="mt-2 text-[10.5px] text-silver-700">PageRank over “who moved whose opinion”. A relative score (1 = most influential in this run).</p></Card>
      </div>
      <Card className="grid gap-4 text-sm md:grid-cols-3">
        <div><div className="label mb-1">Interactions</div>{Object.entries(a.interaction_counts).map(([k, v]: any) => <div key={k} className="flex justify-between font-mono text-xs"><span>{k}</span><span>{v}</span></div>)}<div className="mt-1 text-xs text-silver-500">disagreement rate {(a.disagreement_rate * 100).toFixed(0)}%</div></div>
        <div><div className="label mb-1">Opinion band changes</div>{a.opinion_band_changes.map((c: any) => <div key={c.from + c.to} className="flex justify-between font-mono text-xs"><span>{c.from} → {c.to}</span><span>{c.count}</span></div>)}{!a.opinion_band_changes.length && <span className="text-xs text-silver-500">none</span>}</div>
        <div><div className="label mb-1">Cascades & communities</div><div className="font-mono text-xs">{a.cascade_count} cascades · largest {a.largest_cascades[0]?.size ?? 0}</div>{Object.values(a.groups).slice(0, 6).map((g: any) => <div key={g} className="text-xs text-silver-500">{g}</div>)}</div>
      </Card>
    </div>
  )
}

export function RecCard({ r, i }: { r: any; i: number }) {
  const sec = (k: string, l: string) => r[k]?.length ? <div><div className="label mb-1">{l}</div><ul className="list-disc space-y-0.5 pl-4 text-[12.5px] text-silver-300">{r[k].map((x: string) => <li key={x}>{x}</li>)}</ul></div> : null
  return (
    <Card className="space-y-3"><div className="flex items-start justify-between gap-3"><div><KindTag kind="RECOMMENDATION" /><span className="font-medium">{i + 1}. {r.action}</span></div><div className="shrink-0 text-right"><div className="font-mono text-xl text-violet-soft">{r.priority}</div><div className="label !text-[9px]">priority</div></div></div>
      <div className="grid grid-cols-4 gap-2 font-mono text-[11px]">{['impact', 'feasibility', 'urgency', 'risk'].map(k => <div key={k}><div className="flex justify-between text-silver-500"><span>{k}</span><span>{r.scores[k]}/5</span></div><div className="mt-0.5 h-1 rounded bg-ink-700"><div className={`h-1 rounded ${k === 'risk' ? 'bg-coral' : 'bg-violet'}`} style={{ width: `${r.scores[k] * 20}%` }} /></div></div>)}</div>
      <div className="grid gap-3 md:grid-cols-2">{sec('reasoning', 'Reasoning')}{sec('simulation_findings', 'Simulation findings')}{sec('evidence', 'Supporting evidence')}{sec('benefits', 'Potential benefits')}{sec('risks', 'Risks')}{sec('tradeoffs', 'Trade-offs')}{sec('assumptions', 'Assumptions')}{sec('resources', 'Required resources')}{sec('success_indicators', 'Success indicators')}</div></Card>
  )
}

export function InsightsTab() {
  const { id, project } = useProject()
  const done = project.simulations.filter((s: any) => ['completed', 'stopped'].includes(s.status))
  const [sim, setSim] = useState(done[0]?.id ?? '')
  const an = useAsync(() => (sim ? api(`/simulations/${sim}/analysis`) : Promise.resolve(null)), [sim])
  const recs = useAsync(() => api(`/projects/${id}/recommendations`), [id])
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<unknown>(null)
  const scn = project.scenarios.filter((s: any) => s.status === 'complete')
  const gen = async () => { setBusy(true); setErr(null); try { await api(`/projects/${id}/recommendations`, { body: { simulation_id: sim, scenario_ids: scn.map((s: any) => s.id) } }); recs.reload() } catch (e) { setErr(e) } finally { setBusy(false) } }
  if (!done.length) return <Card className="text-sm text-silver-500">Complete a simulation to see insights.</Card>
  const latest = recs.data?.[0]
  return (
    <div className="space-y-5">
      <select className="input !w-auto" value={sim} onChange={e => setSim(e.target.value)}>{done.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
      {an.loading && <Spinner />}<ErrorNote error={an.error} />{an.data && <AnalysisView a={an.data} />}
      <div className="flex flex-wrap items-center gap-3 pt-2"><h2 className="font-serif text-2xl">What to do next</h2><button className="btn btn-primary" disabled={busy} onClick={gen}>{latest ? 'Regenerate recommendations' : 'Generate recommendations'}</button>{busy && <Spinner label="Weighing evidence…" />}</div>
      <ErrorNote error={err} />
      {latest && <><p className="text-xs text-silver-500">Method: {latest.method}. Priority = {latest.priority_formula}. Recommendations follow from the measured results above; they are not guarantees.</p>{latest.recommendations.map((r: any, i: number) => <RecCard key={i} r={r} i={i} />)}</>}
    </div>
  )
}
