import { NavLink, Outlet } from 'react-router-dom'
import { Compass, FileText, FlaskConical, FolderKanban, Globe, Network, Orbit, Plus, Settings } from 'lucide-react'
import { Wordmark } from './Logo'

const NAV = [
  { to: '/', label: 'Overview', icon: Compass, end: true },
  { to: '/new', label: 'New Analysis', icon: Plus },
  { to: '/projects', label: 'Projects', icon: FolderKanban },
  { to: '/universe', label: 'Simulation Universe', icon: Orbit },
  { to: '/vegeta', label: 'Vegeta × Nederland', icon: Globe },
  { to: '/graph', label: 'Knowledge Graph', icon: Network },
  { to: '/lab', label: 'Scenario Lab', icon: FlaskConical },
  { to: '/reports', label: 'Reports', icon: FileText },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Shell() {
  return (
    <div className="flex h-full">
      <nav className="hidden w-60 shrink-0 flex-col border-r hairline bg-ink-900/70 p-4 md:flex" aria-label="Main">
        <NavLink to="/" className="mb-8 mt-1 px-2"><Wordmark /></NavLink>
        <ul className="space-y-0.5">
          {NAV.map(n => (
            <li key={n.to}>
              <NavLink to={n.to} end={n.end} className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] transition ${isActive ? 'bg-violet/15 text-white' : 'text-silver-500 hover:bg-ink-800 hover:text-silver-100'}`}>
                <n.icon size={16} strokeWidth={1.6} />{n.label}
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="mt-auto space-y-2 px-2 pb-1 text-[11px] leading-relaxed text-silver-700">
          <div className="label !text-[9.5px]">Collective intelligence.<br />Simulated futures.</div>
          <a className="block text-silver-500 hover:text-white" href="https://github.com/Yourtrulysatish/anvaya" target="_blank" rel="noreferrer">Source (AGPL-3.0) ↗</a>
        </div>
      </nav>
      <main className="min-w-0 flex-1 overflow-y-auto pb-16 md:pb-0">
        <Outlet />
      </main>
      <nav className="fixed inset-x-0 bottom-0 z-30 flex justify-around border-t hairline bg-ink-900/95 p-2 backdrop-blur md:hidden" aria-label="Mobile">
        {NAV.filter(n => ['/', '/new', '/universe', '/projects', '/settings'].includes(n.to)).map(n => (
          <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `flex flex-col items-center gap-0.5 rounded-lg px-3 py-1 text-[10px] ${isActive ? 'text-white' : 'text-silver-500'}`}><n.icon size={18} strokeWidth={1.6} />{n.label.split(' ')[0]}</NavLink>
        ))}
      </nav>
    </div>
  )
}
