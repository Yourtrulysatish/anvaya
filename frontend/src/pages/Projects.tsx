import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Trash2 } from 'lucide-react'
import { api } from '../lib/api'
import { BackendGate, Card, ErrorNote, Page, Spinner, useAsync } from '../components/ui'

function Inner() {
  const nav = useNavigate()
  const { data, loading, error, reload } = useAsync<any[]>(() => api('/projects'), [])
  const [name, setName] = useState(''); const [err, setErr] = useState<unknown>(null)
  const create = async () => { try { const p = await api('/projects', { body: { name: name.trim() || 'Untitled analysis' } }); nav(`/projects/${p.id}`) } catch (e) { setErr(e) } }
  return (
    <Page title="Projects" kicker="Workspace" actions={<Link to="/new" className="btn btn-primary">New analysis</Link>}>
      {loading && <Spinner />}<ErrorNote error={error || err} />
      <div className="grid gap-3 md:grid-cols-2">
        {data?.map(p => (
          <Card key={p.id} className="group relative transition hover:border-violet/40">
            <Link to={`/projects/${p.id}`} className="block"><div className="font-medium">{p.name}</div>
              <p className="mt-1 line-clamp-2 min-h-[2.5rem] text-[13px] text-silver-500">{p.situation || 'No situation text'}</p>
              <div className="mt-3 flex gap-2 font-mono text-[11px] text-silver-500"><span className="chip">{p.documents} sources</span><span className="chip">{p.simulations} runs</span></div></Link>
            <button aria-label={`Delete ${p.name}`} className="absolute right-3 top-3 rounded p-1.5 text-silver-700 opacity-0 hover:text-rose group-hover:opacity-100"
              onClick={async () => { if (confirm(`Delete “${p.name}” and all its data? This cannot be undone.`)) { await api(`/projects/${p.id}`, { method: 'DELETE' }); reload() } }}><Trash2 size={15} /></button>
          </Card>))}
        {data && data.length === 0 && <Card className="text-sm text-silver-500">No projects yet. Start with <Link className="text-violet-soft underline" to="/new">a new analysis</Link>.</Card>}
      </div>
      <Card className="mt-5 flex gap-2"><input className="input" placeholder="Project name" value={name} onChange={e => setName(e.target.value)} onKeyDown={e => e.key === 'Enter' && create()} /><button className="btn" onClick={create}>Create empty project</button></Card>
    </Page>
  )
}
export const ProjectsPage = () => <BackendGate><Inner /></BackendGate>
