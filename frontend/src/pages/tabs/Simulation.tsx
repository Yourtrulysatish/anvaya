import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../../lib/api'
import { ErrorNote, useAsync } from '../../components/ui'
import { LiveSim } from '../../observatory/LiveSim'
import { useProject } from '../Project'

export function SimulationTab({ network }: { network?: boolean }) {
  const { id, project, reload } = useProject()
  const [sp, setSp] = useSearchParams()
  const sim = sp.get('sim') ?? project.simulations.find((s: any) => s.status === 'running')?.id ?? project.simulations[0]?.id ?? null
  const health = useAsync(() => api('/health'), [])
  const [pop, setPop] = useState(project.populations[0]?.id ?? ''); const [rounds, setRounds] = useState(20); const [useLlm, setUseLlm] = useState(false)
  const [delib, setDelib] = useState(4); const [calls, setCalls] = useState(0); const [seed, setSeed] = useState(7); const [adv, setAdv] = useState(false); const [err, setErr] = useState<unknown>(null); const [busy, setBusy] = useState(false)
  const [panel, setPanel] = useState(project.simulations.length === 0)
  const llm = health.data?.llm_configured
  const start = async () => {
    setBusy(true); setErr(null)
    try { const r = await api(`/projects/${id}/simulations`, { body: { population_id: pop, rounds, seed, use_llm: useLlm && !!llm, llm_agents_per_round: useLlm ? delib : 0, budget_calls: calls, name: `Run ${project.simulations.length + 1}` } }); reload(); setSp({ sim: r.id }); setPanel(false) }
    catch (e) { setErr(e) } finally { setBusy(false) }
  }
  return (
    <div className="relative h-full min-h-[600px]">
      <div className="absolute left-0 right-0 top-0 z-30 flex flex-wrap items-center gap-2 border-b hairline bg-ink-950/90 px-4 py-2 backdrop-blur">
        <button className="btn !py-1.5" onClick={() => setPanel(p => !p)}>{panel ? 'Close' : 'New run'}</button>
        {project.simulations.map((s: any) => <button key={s.id} onClick={() => setSp({ sim: s.id })} className={`chip ${sim === s.id ? 'chip-on' : ''}`}><i className={`h-1.5 w-1.5 rounded-full ${s.status === 'running' ? 'animate-pulse bg-cyan' : s.status === 'failed' ? 'bg-rose' : 'bg-silver-500'}`} />{s.name} · {s.status}</button>)}
      </div>
      {panel && (
        <div className="absolute left-4 top-14 z-40 w-[22rem] space-y-3 rounded-2xl panel p-4">
          {!project.populations.length ? <p className="text-sm text-silver-300">Generate a population first (Population tab).</p> : (<>
            <label className="label block">Population<select className="input mt-1" value={pop} onChange={e => setPop(e.target.value)}>{project.populations.map((p: any) => <option key={p.id} value={p.id}>{p.title} · {p.n} agents · {p.basis}</option>)}</select></label>
            <label className="label block">Rounds: <span className="font-mono text-silver-100">{rounds}</span><input type="range" min={4} max={60} value={rounds} className="w-full" onChange={e => setRounds(+e.target.value)} /></label>
            {llm ? <label className="flex items-start gap-2 text-[13px] text-silver-300"><input type="checkbox" className="mt-1" checked={useLlm} onChange={e => setUseLlm(e.target.checked)} /><span>Use the language model for message text and key-agent decisions<br /><span className="text-[11px] text-silver-500">Slower and uses tokens (budgeted). Off = fast offline engine with template text, clearly labelled.</span></span></label>
              : <p className="text-[11px] text-gold">No LLM key on this backend — runs use the labelled offline engine.</p>}
            <button className="text-xs text-silver-500 underline" onClick={() => setAdv(a => !a)}>{adv ? 'Hide' : 'Show'} advanced</button>
            {adv && <div className="space-y-2 rounded-lg border hairline p-3"><label className="label block">Seed<input className="input mt-1" type="number" value={seed} onChange={e => setSeed(+e.target.value)} /></label>
              {useLlm && <><label className="label block">LLM-decided agents per round: {delib}<input type="range" min={0} max={12} value={delib} className="w-full" onChange={e => setDelib(+e.target.value)} /></label>
                <label className="label block">Max LLM calls (0 = default budget)<input className="input mt-1" type="number" min={0} value={calls} onChange={e => setCalls(+e.target.value)} /></label></>}</div>}
            <ErrorNote error={err} />
            <button className="btn btn-primary w-full justify-center" disabled={busy || !pop} onClick={start}>Start simulation</button>
          </>)}
        </div>)}
      <div className="h-full pt-[2.9rem]">{sim ? <LiveSim simId={sim} initialMode={network ? 'network' : undefined} /> : <div className="grid h-full place-items-center p-10 text-center text-sm text-silver-500">No runs yet. Use “New run” to launch your first simulation.</div>}</div>
    </div>
  )
}
export const NetworkTab = () => <SimulationTab network />
