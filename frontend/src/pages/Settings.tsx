import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, apiBase, setApiBase, useAuth } from '../lib/api'
import { BackendGate, Card, ErrorNote, Page, Spinner, useAsync } from '../components/ui'

const TASK_LABELS: Record<string, string> = { reasoning: 'Main reasoning — analysis & orchestration', agent: 'Agents — individual reasoning & dialogue', extraction: 'Extraction — documents & entities', summarisation: 'Summarisation — compressing memories', report: 'Report — final analytical reports' }

function SettingsInner() {
  const { data, error, loading, reload } = useAsync(() => api('/settings'), [])
  const [test, setTest] = useState<any>(null); const [testing, setTesting] = useState(false); const [err, setErr] = useState<unknown>(null)
  const [url, setUrl] = useState(apiBase())
  const signOut = useAuth(s => s.set); const email = useAuth(s => s.email)
  const runTest = async () => { setTesting(true); setTest(null); try { setTest(await api('/settings/test', { method: 'POST' })) } catch (e) { setErr(e) } finally { setTesting(false) } }
  const assign = async (task: string, model: string) => { setErr(null); try { await api('/settings/models', { method: 'PUT', body: { task, model } }); reload() } catch (e) { setErr(e) } }
  const u = data?.usage
  return (
    <Page title="Settings" kicker="Model provider · FreeModel.in">
      {loading && <Spinner />}<ErrorNote error={error || err} />
      {data && (
        <div className="space-y-5">
          <Card className="space-y-3">
            <div className="flex flex-wrap items-center gap-3"><div className="label">Connection</div>
              <span className={`chip ${data.llm_configured ? 'chip-on' : ''}`}>{data.llm_configured ? 'API key configured on the backend' : 'No FREEMODEL_API_KEY on the backend'}</span>
              <span className="chip">{data.base_url}</span><span className="chip">{data.models?.length ?? 0} models</span></div>
            <p className="text-xs leading-relaxed text-silver-500">The API key lives only in the backend environment (<code className="font-mono">FREEMODEL_API_KEY</code>). It is never sent to this browser and never logged.</p>
            <div className="flex items-center gap-3"><button className="btn" onClick={runTest} disabled={testing || !data.llm_configured}>Test connection (1 live call)</button>{testing && <Spinner />}</div>
            {test && <div className={`rounded-lg border p-3 font-mono text-xs ${test.ok ? 'border-emerald-400/30 text-emerald-300' : 'border-rose/30 text-rose'}`}>
              {test.ok ? `OK · ${test.models} models · test model ${test.test_model} replied “${test.test_reply}” in ${test.latency_ms} ms` : `Failed · ${JSON.stringify(test.error)}`}
              {test.rate_limit && <div className="mt-1 text-silver-500">rate limit {test.rate_limit['x-ratelimit-limit']}/min · tokens remaining {test.rate_limit['x-ratelimit-remaining-tokens']}</div>}</div>}
          </Card>

          <Card>
            <div className="label mb-3">Model per task {data.is_admin ? '' : <span className="normal-case tracking-normal text-silver-700">(read-only — only the deployment admin can change assignments)</span>}</div>
            <div className="space-y-3">{data.tasks.map((t: string) => { const a = data.assignments?.[t]; return (
              <div key={t} className="grid items-center gap-2 md:grid-cols-[1fr_16rem]">
                <div><div className="text-sm">{TASK_LABELS[t]}</div><div className="font-mono text-[11px] text-silver-500">{a?.error ? `⚠ ${a.error.message}` : `${a?.model}${a?.explicit ? ' · explicit' : ' · auto-selected from live catalogue'}`}</div></div>
                <select className="input" disabled={!data.is_admin} value={a?.explicit ? a.model : ''} onChange={e => assign(t, e.target.value)}>
                  <option value="">Auto (recommended)</option>
                  {data.models?.filter((m: any) => m.capabilities?.includes('json_mode')).map((m: any) => <option key={m.id} value={m.id}>{m.id} · ${(m.pricing?.output_per_1k ?? 0).toFixed(4)}/1k out</option>)}
                </select></div>) })}</div>
          </Card>

          <Card>
            <div className="label mb-3">Usage (all projects, this backend)</div>
            <div className="mb-3 grid grid-cols-3 gap-3 font-mono"><div><div className="label">Tokens</div><div className="text-xl">{(u?.total_tokens ?? 0).toLocaleString()}</div></div><div><div className="label">Calls</div><div className="text-xl">{u?.calls ?? 0}</div></div><div><div className="label">Est. cost</div><div className="text-xl">${(u?.total_cost_usd ?? 0).toFixed(3)}</div></div></div>
            <table className="w-full text-left text-xs"><thead className="label"><tr><th className="py-1">Task</th><th>Model</th><th className="text-right">Calls</th><th className="text-right">Tokens</th><th className="text-right">Cost</th></tr></thead>
              <tbody className="font-mono text-silver-300">{u?.by_task_model.map((r: any) => <tr key={r.task + r.model} className="border-t hairline"><td className="py-1">{r.task}</td><td>{r.model}</td><td className="text-right">{r.calls}</td><td className="text-right">{(r.pt + r.ct).toLocaleString()}</td><td className="text-right">${r.cost.toFixed(4)}</td></tr>)}</tbody></table>
            <p className="mt-2 text-[11px] text-silver-700">Cost is estimated from the provider’s listed per-1k prices; the provider’s own invoice is authoritative. Free plan: 1M tokens/month, 60 requests/min (observed headers).</p>
          </Card>

          <Card><div className="label mb-2">Limits</div><div className="flex flex-wrap gap-2 text-xs">{Object.entries(data.limits).map(([k, v]) => <span key={k} className="chip">{k.replace(/_/g, ' ')}: {String(v)}</span>)}</div></Card>
        </div>
      )}
      <Card className="mt-5 space-y-3"><div className="label">Account & backend</div>
        <div className="text-sm text-silver-300">Signed in as {email}</div>
        <div className="flex gap-2"><input className="input" value={url} onChange={e => setUrl(e.target.value)} /><button className="btn" onClick={() => { setApiBase(url); location.reload() }}>Change backend</button><button className="btn" onClick={() => { api('/auth/logout', { method: 'POST' }).catch(() => {}); signOut(null) }}>Sign out</button></div>
        <Link to="/universe" className="text-xs text-silver-500 underline">Back to the DEMO universe</Link></Card>
    </Page>
  )
}
export const SettingsPage = () => <BackendGate><SettingsInner /></BackendGate>
