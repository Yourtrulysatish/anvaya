import { useRef, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { api, waitJob } from '../../lib/api'
import { Card, ErrorNote, Spinner, useAsync } from '../../components/ui'
import { GraphExplorer } from '../../components/GraphExplorer'
import { useProject } from '../Project'

const TEMPORAL: Record<string, string> = { historical: 'text-silver-300 border-line', current: 'text-cyan border-cyan/30', assumption: 'text-gold border-gold/30' }

export function ResearchTab() {
  const { id, project, reload } = useProject()
  const health = useAsync(() => api('/health'), [])
  const kb = useAsync(() => (project.has_knowledge ? api(`/projects/${id}/graph`) : Promise.resolve(null)), [id, project.has_knowledge])
  const [url, setUrl] = useState(''); const [text, setText] = useState(''); const [busy, setBusy] = useState(''); const [err, setErr] = useState<unknown>(null)
  const [useLlm, setUseLlm] = useState(true); const fileRef = useRef<HTMLInputElement>(null)
  const llm = health.data?.llm_configured
  const run = async (label: string, fn: () => Promise<any>) => { setBusy(label); setErr(null); try { await fn(); reload() } catch (e) { setErr(e) } finally { setBusy('') } }
  const analyse = () => run('Extracting entities, relations and facts…', async () => { const j = await api(`/projects/${id}/analyse`, { body: { use_llm: useLlm && !!llm } }); await waitJob(j.id, p => setBusy(p.message)); kb.reload() })
  const d = kb.data
  return (
    <div className="space-y-5">
      <Card className="space-y-3">
        <div className="flex items-center justify-between"><div className="label">Sources ({project.documents.length})</div>
          <div className="flex gap-2"><button className="btn" onClick={() => fileRef.current?.click()}>Upload</button><input ref={fileRef} hidden type="file" accept=".pdf,.docx,.xlsx,.csv,.json,.txt,.md,.markdown" onChange={e => { const f = e.target.files?.[0]; if (f) run(`Uploading ${f.name}…`, () => { const fd = new FormData(); fd.append('file', f); return api(`/projects/${id}/documents`, { form: fd }) }); e.target.value = '' }} /></div></div>
        {project.documents.map((x: any) => <div key={x.id} className="flex items-center justify-between rounded-lg border hairline px-3 py-2 text-sm"><span>{x.name} <span className="font-mono text-[11px] text-silver-500">· {x.kind} · {x.chars.toLocaleString()} chars{x.url ? ` · ${x.url}` : ''}</span></span>
          <button aria-label="Remove source" className="text-silver-700 hover:text-rose" onClick={() => run('Removing…', () => api(`/projects/${id}/documents/${x.id}`, { method: 'DELETE' }))}><Trash2 size={14} /></button></div>)}
        <div className="flex gap-2"><input className="input" placeholder="https://… add a URL" value={url} onChange={e => setUrl(e.target.value)} /><button className="btn" disabled={!url} onClick={() => run('Fetching URL…', async () => { await api(`/projects/${id}/documents/url`, { body: { url } }); setUrl('') })}>Add URL</button></div>
        <div className="flex gap-2"><input className="input" placeholder="Paste a note or excerpt…" value={text} onChange={e => setText(e.target.value)} /><button className="btn" disabled={!text} onClick={() => run('Saving…', async () => { await api(`/projects/${id}/documents/text`, { body: { text } }); setText('') })}>Add text</button></div>
        <ErrorNote error={err} />
        <div className="flex flex-wrap items-center gap-3 border-t hairline pt-3">
          <button className="btn btn-primary" disabled={!project.documents.length || !!busy} onClick={analyse}>{project.has_knowledge ? 'Re-analyse sources' : 'Analyse sources'}</button>
          {llm && <label className="flex items-center gap-2 text-xs text-silver-500"><input type="checkbox" checked={useLlm} onChange={e => setUseLlm(e.target.checked)} />Use language model for extraction</label>}
          {!llm && health.data && <span className="text-xs text-gold">No LLM key on this backend: only the labelled heuristic extractor is available.</span>}
          {busy && <Spinner label={busy} />}
        </div>
        <p className="text-[11px] leading-relaxed text-silver-700">External web research is not assumed to come from the model provider. Add URLs yourself, or configure a research provider on the backend (<code className="font-mono">ANVAYA_RESEARCH_PROVIDER</code>).</p>
      </Card>

      {d && (<>
        <Card className="space-y-3"><div className="flex items-center justify-between"><div className="label">Knowledge graph</div><span className="font-mono text-[10px] text-silver-500">{d.chunks_processed}/{d.chunks_total} chunks · {d.method}</span></div>
          {d.errors?.length > 0 && <div className="text-xs text-gold">Some chunks fell back to the heuristic extractor: {d.errors.slice(0, 2).join('; ')}</div>}
          {d.nodes.length ? <GraphExplorer kg={d} height={520} /> : <p className="text-sm text-silver-500">No entities found.</p>}</Card>
        {d.contradictions?.length > 0 && <Card className="space-y-2"><div className="label text-rose">Contradictions between sources</div>{d.contradictions.map((c: any, i: number) => <div key={i} className="rounded-lg border border-rose/30 p-3 text-sm"><div>“{c.a.text}” <span className="text-silver-500">— {c.a.source.doc}</span></div><div className="mt-1">“{c.b.text}” <span className="text-silver-500">— {c.b.source.doc}</span></div><div className="mt-1 text-xs text-silver-500">{c.explanation}</div></div>)}</Card>}
        <Card><div className="label mb-3">Facts · classified by time</div><div className="space-y-2">{d.facts.map((f: any, i: number) => <div key={i} className="text-sm"><span className={`mr-2 rounded border px-1.5 py-px font-mono text-[9.5px] ${TEMPORAL[f.temporal]}`}>{f.temporal.toUpperCase()}</span>{f.text}<div className="ml-1 mt-0.5 text-[11.5px] text-silver-500">{f.quote ? `“${f.quote}” — ` : ''}{f.source_ref.doc}</div></div>)}{!d.facts.length && <p className="text-sm text-silver-500">None extracted.</p>}</div></Card>
        {(d.risks?.length > 0 || d.opinions?.length > 0 || d.variables?.length > 0) && <Card className="grid gap-5 md:grid-cols-3">
          <div><div className="label mb-2">Risks</div>{d.risks.map((r: any, i: number) => <p key={i} className="mb-1 text-[13px] text-silver-300">{r.text}</p>)}</div>
          <div><div className="label mb-2">Opinions</div>{d.opinions.map((o: any, i: number) => <p key={i} className="mb-1 text-[13px] text-silver-300"><b>{o.holder}</b>: {o.stance}</p>)}</div>
          <div><div className="label mb-2">Variables</div>{d.variables.map((v: any, i: number) => <p key={i} className="mb-1 font-mono text-[12px] text-silver-300">{v.name} = {v.value} {v.unit}</p>)}</div></Card>}
        {Object.entries(d.dataset_analysis ?? {}).map(([name, a]: any) => <Card key={name}><div className="label mb-2">Dataset · {name} · {a.rows} rows</div>
          <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead className="label"><tr><th className="py-1">Column</th><th>Type</th><th>Summary</th></tr></thead><tbody className="font-mono text-silver-300">{a.columns.map((c: any) => <tr key={c.name} className="border-t hairline"><td className="py-1">{c.name}</td><td>{c.type}</td><td>{c.type === 'numeric' ? `mean ${c.mean} · sd ${c.std} · min ${c.min} · median ${c.median} · max ${c.max}` : `${c.unique} unique · top: ${c.top.map((t: any) => `${t.value} (${t.count})`).join(', ')}`}{c.missing ? ` · ${c.missing} missing` : ''}</td></tr>)}</tbody></table></div>
          {Object.entries(a.trends ?? {}).map(([c, t]: any) => <p key={c} className="mt-2 text-xs text-silver-300"><span className="mr-1.5 rounded border border-gold/30 px-1 font-mono text-[9px] text-gold">ESTIMATE</span>{c}: slope {t.slope_per_step} per row (95% CI {t.ci95[0]} to {t.ci95[1]}), R² {t.r2}, {t.significant ? 'distinguishable from flat' : 'not distinguishable from flat'}.</p>)}
          {a.correlations?.slice(0, 4).map((c: any, i: number) => <p key={i} className="mt-1 text-xs text-silver-500">correlation {c.a} ↔ {c.b}: r = {c.r} (association, not causation)</p>)}</Card>)}
      </>)}
    </div>
  )
}
