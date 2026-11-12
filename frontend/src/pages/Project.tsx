import { createContext, useContext } from 'react'
import { Link, NavLink, useParams } from 'react-router-dom'
import { api } from '../lib/api'
import { BackendGate, ErrorNote, Spinner, useAsync, Card } from '../components/ui'
import { ResearchTab } from './tabs/Research'
import { PopulationTab } from './tabs/Population'
import { SimulationTab, NetworkTab } from './tabs/Simulation'
import { AgentsTab } from './tabs/Agents'
import { ScenariosTab } from './tabs/Scenarios'
import { InsightsTab } from './tabs/Insights'
import { ReportsTab } from './tabs/Reports'

export interface ProjectCtx { id: string; project: any; reload: () => void }
const Ctx = createContext<ProjectCtx>(null as any)
export const useProject = () => useContext(Ctx)

const TABS = [['', 'Overview'], ['research', 'Research'], ['population', 'Population'], ['simulation', 'Simulation'], ['agents', 'Agent Explorer'], ['network', 'Network'], ['scenarios', 'Scenarios'], ['insights', 'Insights'], ['reports', 'Reports']]

function Overview() {
  const { project: p, id } = useProject()
  const sims = p.simulations.filter((s: any) => s.status === 'completed' || s.status === 'stopped')
  const next = !p.documents.length ? ['research', 'Add sources (documents, URLs or notes) — or skip straight to a population.']
    : !p.has_knowledge ? ['research', 'Analyse your sources to build the knowledge graph and extract facts.']
    : !p.populations.length ? ['population', 'Describe the population to simulate.']
    : !p.simulations.length ? ['simulation', 'Run your first simulation.']
    : !p.scenarios.length ? ['scenarios', 'Explore alternative futures with the Scenario Lab.']
    : !p.reports.length ? ['insights', 'Review insights, generate recommendations, then produce a report.'] : ['reports', 'Open your report.']
  return (
    <div className="space-y-4">
      <Card><div className="label mb-1">Situation</div><p className="whitespace-pre-wrap text-sm text-silver-300">{p.situation || '—'}</p>{p.objectives && <><div className="label mb-1 mt-4">Objectives</div><p className="whitespace-pre-wrap text-sm text-silver-300">{p.objectives}</p></>}</Card>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">{[['Sources', p.documents.length], ['Populations', p.populations.length], ['Runs', p.simulations.length], ['Scenarios', p.scenarios.length], ['Reports', p.reports.length]].map(([k, v]) => <Card key={k as string}><div className="label">{k}</div><div className="font-mono text-2xl">{v}</div></Card>)}</div>
      <Card className="flex flex-wrap items-center justify-between gap-3 border-violet/30"><div><div className="label mb-1">Suggested next step</div><p className="text-sm">{next[1]}</p></div><Link className="btn btn-primary" to={`/projects/${id}/${next[0]}`}>Go</Link></Card>
      {sims.length > 0 && <Card><div className="label mb-2">Latest completed run</div><Link className="text-violet-soft underline" to={`/projects/${id}/simulation?sim=${sims[0].id}`}>{sims[0].name} · {sims[0].events} events</Link></Card>}
    </div>
  )
}

function Inner() {
  const { id = '', tab = '' } = useParams()
  const { data: project, error, loading, reload } = useAsync(() => api(`/projects/${id}`), [id])
  if (loading && !project) return <div className="p-8"><Spinner /></div>
  if (error || !project) return <div className="p-8"><ErrorNote error={error ?? 'Project not found'} /></div>
  const full = tab === 'simulation' || tab === 'network'
  return (
    <Ctx.Provider value={{ id, project, reload }}>
      <div className={full ? 'flex h-screen flex-col' : ''}>
        <header className="border-b hairline px-6 pt-5">
          <div className="label"><Link to="/projects" className="hover:text-white">Projects</Link> / {project.name}</div>
          <nav className="-mb-px mt-3 flex gap-1 overflow-x-auto" aria-label="Project sections">{TABS.map(([t, l]) => (
            <NavLink key={t} to={`/projects/${id}${t ? '/' + t : ''}`} end className={({ isActive }) => `whitespace-nowrap border-b-2 px-3 py-2 text-[13px] ${isActive ? 'border-violet text-white' : 'border-transparent text-silver-500 hover:text-silver-100'}`}>{l}</NavLink>))}</nav>
        </header>
        <div className={full ? 'min-h-0 flex-1' : 'mx-auto max-w-6xl px-6 py-7'}>
          {tab === '' && <Overview />}{tab === 'research' && <ResearchTab />}{tab === 'population' && <PopulationTab />}
          {tab === 'simulation' && <SimulationTab />}{tab === 'agents' && <AgentsTab />}{tab === 'network' && <NetworkTab />}
          {tab === 'scenarios' && <ScenariosTab />}{tab === 'insights' && <InsightsTab />}{tab === 'reports' && <ReportsTab />}
        </div>
      </div>
    </Ctx.Provider>
  )
}
export const ProjectPage = () => <BackendGate><Inner /></BackendGate>
