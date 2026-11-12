import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { loadDemo, loadVegeta } from '../lib/demo'
import type { Dataset } from '../lib/types'
import { Observatory } from '../observatory/Observatory'

const SETS = [{ id: 'vegeta', label: 'Vegeta × Nederland', load: loadVegeta }, { id: 'demo', label: 'DEMO · India smartphones', load: loadDemo }]

export function UniversePage({ initial = 'demo' }: { initial?: 'demo' | 'vegeta' }) {
  const [sp, setSp] = useSearchParams()
  const which = (sp.get('set') as 'demo' | 'vegeta') ?? initial
  const [ds, setDs] = useState<Dataset | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    setDs(null); setErr('')
    SETS.find(s => s.id === which)!.load().then(setDs).catch(e => setErr(String(e.message ?? e)))
  }, [which])
  return (
    <div className="relative h-full min-h-[560px] md:h-screen">
      <div className="absolute left-1/2 top-4 z-30 flex -translate-x-1/2 gap-1 rounded-xl border border-line bg-ink-900/85 p-1 backdrop-blur" role="tablist" aria-label="Simulation">
        {SETS.map(s => <button key={s.id} role="tab" aria-selected={which === s.id} onClick={() => setSp({ set: s.id })} className={`rounded-lg px-3 py-1.5 text-xs font-medium ${which === s.id ? 'bg-violet/25 text-white' : 'text-silver-500 hover:text-silver-100'}`}>{s.label}</button>)}
      </div>
      {ds ? <Observatory key={which} dataset={ds} /> : <div className="grid h-full place-items-center text-sm text-silver-500">{err ? `Could not load this simulation: ${err}` : 'Loading the simulation…'}</div>}
    </div>
  )
}
