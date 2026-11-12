import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, Page, Spinner } from '../components/ui'
import { RecCard } from './tabs/Insights'
import { ReportView, reportToMarkdown, saveText } from './tabs/Reports'
import { useAuth } from '../lib/api'

export function ReportsPage() {
  const [d, setD] = useState<any>(null); const token = useAuth(s => s.token)
  useEffect(() => { fetch(`${import.meta.env.BASE_URL}demo/report.json`).then(r => r.json()).then(setD) }, [])
  return (
    <Page wide title="Reports" kicker="DEMO report · generated offline from the DEMO run"
      actions={<Link className="btn btn-primary" to={token ? '/projects' : '/new'}>Generate a report for your project</Link>}>
      <p className="mb-5 max-w-3xl text-sm text-silver-500">Every statement is classified FACT, ANALYSIS, ESTIMATE, SIMULATION or RECOMMENDATION and carries its source. Live projects export PDF, Markdown and CSV; the DEMO offers Markdown. Live reports use your documents as FACT sources and, when a model is configured, an LLM-written executive summary grounded only in the computed results.</p>
      {!d ? <Spinner /> : (<div className="space-y-5">
        <ReportView report={d.report} onExport={{ md: () => saveText('anvaya-demo-report.md', reportToMarkdown(d.report)) }} />
        <Card><div className="label mb-3">Decision intelligence · ranked recommendations (rule-based in the DEMO)</div><div className="space-y-4">{d.recommendations.map((r: any, i: number) => <RecCard key={i} r={r} i={i} />)}</div></Card></div>)}
    </Page>
  )
}
