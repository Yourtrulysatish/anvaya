import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, apiBase, useAuth } from '../lib/api'
import { Card, ErrorNote, Page, Spinner } from '../components/ui'
import { GraphExplorer, type KG } from '../components/GraphExplorer'

export function GraphPage() {
  const token = useAuth(s => s.token)
  const [demo, setDemo] = useState<KG | null>(null)
  const [projects, setProjects] = useState<any[]>([]); const [sel, setSel] = useState('demo'); const [live, setLive] = useState<KG | null>(null); const [err, setErr] = useState<unknown>(null); const [loading, setLoading] = useState(false)
  useEffect(() => { fetch(`${import.meta.env.BASE_URL}demo/graph.json`).then(r => r.json()).then(setDemo).catch(e => setErr(e)) }, [])
  useEffect(() => { if (token && apiBase()) api('/projects').then(p => setProjects(p.filter((x: any) => x.documents > 0))).catch(() => {}) }, [token])
  useEffect(() => {
    if (sel === 'demo') { setLive(null); return }
    setLoading(true); setErr(null)
    api(`/projects/${sel}/graph`).then(setLive).catch(setErr).finally(() => setLoading(false))
  }, [sel])
  const kg = sel === 'demo' ? demo : live
  return (
    <Page wide title="Knowledge Graph" kicker={sel === 'demo' ? 'DEMO · derived from the demo simulation' : 'Your sources'}
      actions={<select className="input !w-auto" value={sel} onChange={e => setSel(e.target.value)} aria-label="Graph source"><option value="demo">DEMO graph</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}>
      {sel === 'demo' && <p className="mb-4 max-w-3xl text-sm text-silver-500">This graph is computed from the DEMO simulation: segments, the scripted price-cut event and the most influential agents. For your own material, create an analysis — entities, relationships and facts are extracted with their source quotes, and contradictions between sources are flagged. The knowledge graph and the <Link className="text-violet-soft underline" to="/universe">live simulation universe</Link> are different views: this one is about what the sources say, the universe is about how agents behave.</p>}
      {loading && <Spinner />}<ErrorNote error={err} />
      {kg ? (kg.nodes.length ? <GraphExplorer kg={kg} height={600} /> : <Card className="text-sm text-silver-500">No entities were found.</Card>) : !loading && !err && <Spinner />}
      {!token && <p className="mt-4 text-xs text-silver-700">Sign in under Projects to explore graphs of your own sources.</p>}
    </Page>
  )
}
