import { useState } from 'react'
import { api, download } from '../../lib/api'
import { Card, ErrorNote, KindTag, Spinner, useAsync } from '../../components/ui'
import { useProject } from '../Project'

export function ReportView({ report, onExport }: { report: any; onExport?: { md: () => void; pdf?: () => void; csv?: (p: string) => void } }) {
  return (
    <Card className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="label">Report</div><h2 className="font-serif text-3xl">{report.title}</h2><p className="mt-1 text-[11px] text-silver-500">Claim classes: <KindTag kind="FACT" /><KindTag kind="ANALYSIS" /><KindTag kind="ESTIMATE" /><KindTag kind="SIMULATION" /><KindTag kind="RECOMMENDATION" /></p></div>
        {onExport && <div className="flex flex-wrap gap-2"><button className="btn" onClick={onExport.md}>Markdown</button>{onExport.pdf && <button className="btn" onClick={onExport.pdf}>PDF</button>}{onExport.csv && ['events', 'metrics', 'agents'].map(p => <button key={p} className="btn" onClick={() => onExport.csv!(p)}>CSV · {p}</button>)}</div>}</div>
      <p className="rounded-lg border border-gold/25 bg-gold/5 p-3 text-xs text-silver-300">Simulation outputs are model results under stated assumptions, not predictions of what will happen.</p>
      {report.sections.map((s: any) => <section key={s.n}><h3 className="mb-2 border-b pb-1 text-lg font-medium hairline">{s.n}. {s.title}</h3><ul className="space-y-1.5 text-[13.5px] leading-relaxed text-silver-300">{s.blocks.map((b: any, i: number) => <li key={i}><KindTag kind={b.kind} />{b.text}{b.sources?.length > 0 && <span className="ml-1 text-[11px] text-silver-700">({b.sources.slice(0, 2).map((x: any) => x.doc).filter(Boolean).join('; ')})</span>}</li>)}</ul></section>)}
    </Card>
  )
}

export function reportToMarkdown(rep: any): string {
  const out = [`# ${rep.title}`, `_Generated ${rep.generated}. Simulation outputs are model results under stated assumptions, not predictions of what will happen._`, '']
  for (const s of rep.sections) { out.push(`## ${s.n}. ${s.title}`, ''); for (const b of s.blocks) out.push(`- **[${b.kind}]** ${b.text.trim()}${b.sources?.length ? ` _(sources: ${b.sources.slice(0, 3).map((x: any) => x.doc).filter(Boolean).join('; ')})_` : ''}`); out.push('') }
  return out.join('\n')
}
export function saveText(name: string, text: string, type = 'text/markdown') { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; a.click() }

export function ReportsTab() {
  const { id, project, reload } = useProject()
  const done = project.simulations.filter((s: any) => ['completed', 'stopped'].includes(s.status))
  const [sim, setSim] = useState(done[0]?.id ?? ''); const [sc, setSc] = useState<Set<string>>(new Set(project.scenarios.filter((s: any) => s.status === 'complete').map((s: any) => s.id)))
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<unknown>(null); const [sel, setSel] = useState<string | null>(project.reports[0]?.id ?? null)
  const rep = useAsync(() => (sel ? api(`/reports/${sel}`) : Promise.resolve(null)), [sel])
  const gen = async () => { setBusy(true); setErr(null); try { const r = await api(`/projects/${id}/reports`, { body: { simulation_id: sim, scenario_ids: [...sc], monte_carlo_replicates: 10 } }); reload(); setSel(r.id); rep.reload() } catch (e) { setErr(e) } finally { setBusy(false) } }
  return (
    <div className="space-y-5">
      <Card className="space-y-3"><div className="label">Generate a report</div>
        {!done.length ? <p className="text-sm text-silver-500">Complete a simulation first.</p> : (<>
          <select className="input !w-auto" value={sim} onChange={e => setSim(e.target.value)}>{done.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
          {project.scenarios.filter((s: any) => s.status === 'complete').length > 0 && <div className="flex flex-wrap gap-2">{project.scenarios.filter((s: any) => s.status === 'complete').map((s: any) => <button key={s.id} className={`chip ${sc.has(s.id) ? 'chip-on' : ''}`} onClick={() => setSc(c => { const n = new Set(c); n.has(s.id) ? n.delete(s.id) : n.add(s.id); return n })}>{s.name}</button>)}</div>}
          <div className="flex items-center gap-3"><button className="btn btn-primary" disabled={busy} onClick={gen}>Generate report</button>{busy && <Spinner label="Running replicates and writing the report…" />}</div></>)}
        <ErrorNote error={err} /></Card>
      {project.reports.length > 0 && <div className="flex flex-wrap gap-2">{project.reports.map((r: any) => <button key={r.id} onClick={() => setSel(r.id)} className={`chip ${sel === r.id ? 'chip-on' : ''}`}>{r.title}</button>)}</div>}
      {rep.loading && <Spinner />}
      {rep.data && <ReportView report={rep.data.report} onExport={{ md: () => download(`/reports/${sel}/export?format=md`, `anvaya-report.md`), pdf: () => download(`/reports/${sel}/export?format=pdf`, `anvaya-report.pdf`), csv: p => download(`/reports/${sel}/export?format=csv&part=${p}`, `anvaya-${p}.csv`) }} />}
    </div>
  )
}
