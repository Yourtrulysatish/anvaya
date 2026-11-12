import { useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { FileUp, Link2, Plus, X } from 'lucide-react'
import { api } from '../lib/api'
import { BackendGate, Card, ErrorNote, Page, Spinner } from '../components/ui'

function Inner() {
  const nav = useNavigate()
  const loc = useLocation() as { state?: { situation?: string } }
  const [situation, setSituation] = useState(loc.state?.situation ?? '')
  const [objectives, setObjectives] = useState('')
  const [urls, setUrls] = useState<string[]>([]); const [urlIn, setUrlIn] = useState('')
  const [files, setFiles] = useState<File[]>([]); const [pasted, setPasted] = useState(''); const [showPaste, setShowPaste] = useState(false)
  const [busy, setBusy] = useState(''); const [err, setErr] = useState<unknown>(null); const [warn, setWarn] = useState<string[]>([])
  const [plan, setPlan] = useState<any>(null); const [pid, setPid] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const short = situation.trim().length > 0 && situation.trim().length < 25

  const interpret = async () => {
    setErr(null); setWarn([]); setBusy('Creating project and reading your sources…')
    try {
      const name = situation.trim().replace(/\s+/g, ' ').slice(0, 56) || 'Untitled analysis'
      const p = pid ? { id: pid } : await api('/projects', { body: { name, situation, objectives } })
      setPid(p.id)
      const problems: string[] = []
      for (const f of files) { const fd = new FormData(); fd.append('file', f); try { await api(`/projects/${p.id}/documents`, { form: fd }) } catch (e: any) { problems.push(`${f.name}: ${e.message}`) } }
      for (const u of urls) { try { await api(`/projects/${p.id}/documents/url`, { body: { url: u } }) } catch (e: any) { problems.push(`${u}: ${e.message}`) } }
      if (pasted.trim()) await api(`/projects/${p.id}/documents/text`, { body: { name: 'Pasted text', text: pasted } })
      setWarn(problems); setFiles([]); setUrls([]); setPasted('')
      setPlan(await api(`/projects/${p.id}/methodology`, { body: { question: `${situation} ${objectives}` } }))
    } catch (e) { setErr(e) } finally { setBusy('') }
  }

  return (
    <Page title="New analysis" kicker="Describe → Understand → Simulate">
      <div className="space-y-5">
        <Card className="space-y-3">
          <label className="label" htmlFor="sit">What situation would you like to explore?</label>
          <textarea id="sit" className="input min-h-28" value={situation} onChange={e => setSituation(e.target.value)} placeholder="Describe the situation, the people involved and what you want to understand." />
          {short && <p className="text-xs text-gold">A little more detail (who is involved, what changes) will give a much better population.</p>}
          <label className="label" htmlFor="obj">Your objectives <span className="normal-case tracking-normal text-silver-700">(optional)</span></label>
          <textarea id="obj" className="input min-h-16" value={objectives} onChange={e => setObjectives(e.target.value)} placeholder="e.g. Decide whether to launch in Q1; identify which segment to target first." />
        </Card>
        <Card className="space-y-3">
          <div className="label">Evidence <span className="normal-case tracking-normal text-silver-700">PDF · DOCX · XLSX · CSV · JSON · TXT · MD · URLs</span></div>
          <div onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); setFiles(f => [...f, ...Array.from(e.dataTransfer.files)]) }}
            className="flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-line p-3">
            <button className="btn" onClick={() => fileRef.current?.click()}><FileUp size={14} />Upload files</button>
            <input ref={fileRef} hidden multiple type="file" accept=".pdf,.docx,.xlsx,.csv,.json,.txt,.md,.markdown" onChange={e => setFiles(f => [...f, ...Array.from(e.target.files ?? [])])} />
            <button className="btn" onClick={() => setShowPaste(s => !s)}><Plus size={14} />Paste text</button>
            <span className="text-xs text-silver-500">or drop files here</span>
            {files.map((f, i) => <span key={i} className="chip">{f.name}<button aria-label="Remove" onClick={() => setFiles(fs => fs.filter((_, j) => j !== i))}><X size={11} /></button></span>)}
          </div>
          {showPaste && <textarea className="input min-h-24" placeholder="Paste notes, an article, or data…" value={pasted} onChange={e => setPasted(e.target.value)} />}
          <div className="flex gap-2"><input className="input" placeholder="https://… add a relevant URL" value={urlIn} onChange={e => setUrlIn(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && urlIn.trim()) { setUrls(u => [...u, urlIn.trim()]); setUrlIn('') } }} />
            <button className="btn" onClick={() => { if (urlIn.trim()) { setUrls(u => [...u, urlIn.trim()]); setUrlIn('') } }}><Link2 size={14} />Add</button></div>
          <div className="flex flex-wrap gap-2">{urls.map((u, i) => <span key={i} className="chip">{u}<button aria-label="Remove" onClick={() => setUrls(x => x.filter((_, j) => j !== i))}><X size={11} /></button></span>)}</div>
        </Card>
        <ErrorNote error={err} />
        {warn.map(w => <div key={w} className="rounded-lg border border-gold/30 bg-gold/10 px-3 py-2 text-[13px] text-gold">Skipped — {w}</div>)}
        {!plan && <div className="flex items-center gap-3"><button className="btn btn-primary" disabled={!situation.trim() || !!busy} onClick={interpret}>Interpret & propose a workflow</button>{busy && <Spinner label={busy} />}</div>}
        {plan && (
          <Card className="space-y-3 reveal">
            <div className="label">Proposed analytical workflow</div>
            <div className="flex flex-wrap gap-2">{plan.methods.map((m: any) => <span key={m.id} className="chip chip-on">{m.name}</span>)}</div>
            <ul className="list-disc space-y-1 pl-5 text-sm text-silver-300">{plan.rationale.map((r: string) => <li key={r}>{r}</li>)}</ul>
            {plan.note && <p className="rounded-lg border border-gold/30 bg-gold/10 p-3 text-sm text-gold">{plan.note}</p>}
            <div className="flex flex-wrap gap-2 pt-1">
              <button className="btn btn-primary" onClick={() => nav(`/projects/${pid}/research`)}>{plan.simulation_recommended ? 'Continue: research & population' : 'Continue: analyse the sources'}</button>
              <button className="btn" onClick={() => nav(`/projects/${pid}`)}>Open project</button></div>
          </Card>)}
      </div>
    </Page>
  )
}
export const NewAnalysisPage = () => <BackendGate><Inner /></BackendGate>
