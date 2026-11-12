import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, Page, Spinner } from '../components/ui'
import { IntervalBar, LineChart } from '../components/Charts'
import { ScenarioCompare } from './tabs/Scenarios'
import { useAuth } from '../lib/api'

export function LabPage() {
  const [d, setD] = useState<any>(null); const token = useAuth(s => s.token)
  useEffect(() => { fetch(`${import.meta.env.BASE_URL}demo/scenarios.json`).then(r => r.json()).then(setD) }, [])
  if (!d) return <Page title="Scenario Lab"><Spinner /></Page>
  const sc = d.scenarios
  return (
    <Page wide title="Scenario Lab" kicker="DEMO · 12 paired Monte Carlo replicates per scenario, offline engine"
      actions={<Link className="btn btn-primary" to={token ? '/projects' : '/new'}>Run scenarios on your own project</Link>}>
      <p className="mb-5 max-w-3xl text-sm text-silver-500">Each scenario changes only its stated assumptions; baseline and variant share the same population and random seeds, so differences are paired. Scenario effects here are scripted DEMO assumptions. In a live project you can type “What if the competitor reduces its price by 20%?” and ANVAYA translates it into editable assumptions before running.</p>
      <div className="space-y-5">
        <ScenarioCompare scenarios={sc} />
        {sc.filter((s: any) => s.results.comparison).map((s: any) => { const c = s.results.comparison; return (
          <Card key={s.id} className="space-y-3"><div><span className="chip mr-2">{s.kind}</span><b>{s.name}</b></div><p className="text-sm text-silver-300">{s.prompt}</p>
            <div className="grid gap-2 md:grid-cols-4">{(['mean_opinion', 'support_share', 'oppose_share', 'polarisation'] as const).map(k => { const x = c.differences[k]; return <div key={k} className="rounded-lg border hairline p-2.5"><div className="label">Δ {k.replace(/_/g, ' ')}</div><div className="font-mono text-lg">{x.mean_diff >= 0 ? '+' : ''}{x.mean_diff}</div><div className="font-mono text-[10.5px] text-silver-500">95%: {x.ci95[0]} … {x.ci95[1]}</div><div className={`text-[10.5px] ${x.distinguishable_from_zero ? 'text-cyan' : 'text-silver-700'}`}>{x.distinguishable_from_zero ? 'distinguishable from zero' : 'within noise'}</div></div> })}</div>
            <div><div className="label mb-1">Segment reactions vs baseline</div>{Object.entries(c.segment_differences).map(([seg, x]: any) => <div key={seg} className="grid grid-cols-[11rem_1fr_4rem] items-center gap-3 text-xs"><span className="truncate">{seg}</span><IntervalBar mean={x.mean_diff} lo={x.ci95[0]} hi={x.ci95[1]} min={-0.6} max={0.6} /><span className="font-mono text-silver-500">{x.mean_diff >= 0 ? '+' : ''}{x.mean_diff}</span></div>)}</div>
            {s.results.sensitivity && <div><div className="label mb-1">Sensitivity to effect size</div><LineChart height={120} xLabels={s.results.sensitivity.map((x: any) => `${x.scale}×`)} series={[{ label: 'mean opinion', color: '#8B5CF6', values: s.results.sensitivity.map((x: any) => x.mean_opinion) }]} /></div>}
            <p className="text-[11.5px] text-silver-500">{c.method} {c.uncertainty}</p></Card>) })}
      </div>
    </Page>
  )
}
