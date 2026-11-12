import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api'
import { Card, ErrorNote, Spinner, useAsync } from '../../components/ui'
import { opinionColor } from '../../observatory/renderer'
import { useProject } from '../Project'

export function AgentsTab() {
  const { id, project } = useProject()
  const done = project.simulations.filter((s: any) => ['completed', 'stopped'].includes(s.status))
  const [sim, setSim] = useState(done[0]?.id ?? '')
  const data = useAsync(async () => {
    if (!sim) return null
    const [info, ev] = await Promise.all([api(`/simulations/${sim}`), api(`/simulations/${sim}/events?limit=20000`)])
    return { info, events: ev.events as any[] }
  }, [sim])
  const [sort, setSort] = useState<{ k: string; d: 1 | -1 }>({ k: 'influence', d: -1 }); const [seg, setSeg] = useState(''); const [q, setQ] = useState('')
  const rows = useMemo(() => {
    if (!data.data) return []
    const { info, events } = data.data; const end = events.find((e: any) => e.type === 'sim_end')?.result ?? {}
    const acts: Record<number, number> = {}; for (const e of events) if (e.source_agent != null && ['post', 'reply', 'agree', 'disagree', 'share'].includes(e.type)) acts[e.source_agent] = (acts[e.source_agent] ?? 0) + 1
    return info.agents.map((a: any) => { const s = a.opinions[info.topic] ?? 0, f = end.final_opinions?.[String(a.id)] ?? s
      return { id: a.id, name: a.name, segment: a.segment, start: s, end: f, shift: f - s, influence: end.influence?.[String(a.id)] ?? 0, acts: acts[a.id] ?? 0, group: end.group_names?.[String(end.agent_groups?.[String(a.id)])] ?? '—' } })
  }, [data.data])
  const segs = [...new Set(rows.map((r: any) => r.segment))] as string[]
  const view = rows.filter((r: any) => (!seg || r.segment === seg) && (!q || r.name.toLowerCase().includes(q.toLowerCase()))).sort((a: any, b: any) => (a[sort.k] > b[sort.k] ? 1 : -1) * sort.d)
  const th = (k: string, l: string) => <th className="cursor-pointer py-1.5 pr-3 hover:text-white" onClick={() => setSort(s => ({ k, d: s.k === k ? (-s.d as 1 | -1) : -1 }))}>{l}{sort.k === k ? (sort.d === -1 ? ' ↓' : ' ↑') : ''}</th>
  if (!done.length) return <Card className="text-sm text-silver-500">Complete a simulation first, then explore every agent here.</Card>
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center gap-2"><select className="input !w-auto" value={sim} onChange={e => setSim(e.target.value)}>{done.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
        <select className="input !w-auto" value={seg} onChange={e => setSeg(e.target.value)}><option value="">All segments</option>{segs.map(s => <option key={s}>{s}</option>)}</select>
        <input className="input !w-48" placeholder="Search name" value={q} onChange={e => setQ(e.target.value)} /><Link className="btn ml-auto" to={`/projects/${id}/simulation?sim=${sim}`}>Open in the universe</Link></div>
      {data.loading && <Spinner />}<ErrorNote error={data.error} />
      <div className="max-h-[70vh] overflow-auto"><table className="w-full text-left text-xs"><thead className="label sticky top-0 bg-ink-900"><tr>{th('name', 'Agent')}{th('segment', 'Segment')}{th('start', 'Start')}{th('end', 'End')}{th('shift', 'Shift')}{th('influence', 'Influence')}{th('acts', 'Actions')}<th>Community</th></tr></thead>
        <tbody className="font-mono text-silver-300">{view.map((r: any) => <tr key={r.id} className="border-t hairline"><td className="py-1.5 pr-3 font-sans text-silver-100">{r.name}</td><td className="pr-3 font-sans">{r.segment}</td><td className="pr-3">{r.start.toFixed(2)}</td>
          <td className="pr-3"><i className="mr-1.5 inline-block h-2 w-2 rounded-full" style={{ background: opinionColor(r.end) }} />{r.end.toFixed(2)}</td><td className="pr-3">{r.shift >= 0 ? '+' : ''}{r.shift.toFixed(2)}</td><td className="pr-3">{r.influence.toFixed(2)}</td><td className="pr-3">{r.acts}</td><td className="font-sans text-silver-500">{r.group}</td></tr>)}</tbody></table></div>
    </Card>
  )
}
