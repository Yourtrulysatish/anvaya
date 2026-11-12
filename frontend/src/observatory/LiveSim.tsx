import { useEffect, useMemo, useRef, useState } from 'react'
import { api, streamSimulation } from '../lib/api'
import { Playback } from '../lib/simState'
import type { Dataset } from '../lib/types'
import { Observatory, type LiveControls } from './Observatory'
import type { Mode } from './renderer'
import { Spinner } from '../components/ui'

/** Streams a backend simulation (live or recorded) into the observatory through the normalised event pipeline. */
export function LiveSim({ simId, initialMode }: { simId: string; initialMode?: Mode }) {
  const [info, setInfo] = useState<any>(null)
  const [err, setErr] = useState('')
  const [status, setStatus] = useState('created')
  const [round, setRound] = useState(0)
  const pbRef = useRef<Playback | null>(null)

  useEffect(() => {
    let live = true; setInfo(null); pbRef.current = null
    api(`/simulations/${simId}`).then(i => { if (live) { setInfo(i); setStatus(i.status) } }).catch(e => live && setErr(e.message))
    return () => { live = false }
  }, [simId])

  const dataset: Dataset | null = useMemo(() => info && ({
    meta: { label: info.label ?? 'LIVE', title: info.name, agents: info.agents.length, rounds: info.config?.rounds ?? 0, simulationId: simId, synthetic: false },
    agents: info.agents, events: [],
  }), [info, simId])

  const pb = useMemo(() => {
    if (!info) return null
    const p = new Playback(info.agents, info.topic); p.live = info.status === 'running' || info.status === 'paused' || info.status === 'created'
    pbRef.current = p; return p
  }, [info])

  useEffect(() => {
    if (!pb || !info) return
    const ac = new AbortController()
    streamSimulation(simId, {
      onEvents: evs => { pb.append(evs); const last = evs[evs.length - 1]; if (last) setRound(last.round) },
      onStatus: s => { if (s.status) setStatus(s.status); if (s.round != null) setRound(s.round) },
      onEnd: s => { setStatus(s.status ?? 'completed'); pb.live = false },
    }, ac.signal)
    if (pb.live) pb.playing = true
    return () => ac.abort()
  }, [pb, simId, info])

  const controls: LiveControls | undefined = useMemo(() => (status === 'running' || status === 'paused' ? {
    status, round,
    onPause: () => { api(`/simulations/${simId}/pause`, { method: 'POST' }).then(() => setStatus('paused')).catch(() => {}) },
    onResume: () => { api(`/simulations/${simId}/resume`, { method: 'POST' }).then(() => setStatus('running')).catch(() => {}) },
    onStop: () => { api(`/simulations/${simId}/stop`, { method: 'POST' }).catch(() => {}) },
    interview: info?.config?.use_llm || info?.mode === 'native' ? (aid, question) => api(`/simulations/${simId}/agents/${aid}/interview`, { body: { question } }) : undefined,
  } : { status, round, interview: info?.mode === 'native' ? (aid: number, question: string) => api(`/simulations/${simId}/agents/${aid}/interview`, { body: { question } }) : undefined }), [status, round, simId, info])

  if (err) return <div className="p-6 text-sm text-rose">{err}</div>
  if (!dataset || !pb) return <div className="grid h-full place-items-center"><Spinner label="Loading simulation…" /></div>
  return <Observatory key={simId} dataset={dataset} playback={pb} live={controls} autoplay={pb.live} initialMode={initialMode} />
}
