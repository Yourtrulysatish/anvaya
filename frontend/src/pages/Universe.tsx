import { useEffect, useState } from 'react'
import { loadDemo } from '../lib/demo'
import type { Dataset } from '../lib/types'
import { Observatory } from '../observatory/Observatory'

export function UniversePage() {
  const [ds, setDs] = useState<Dataset | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => { loadDemo().then(setDs).catch(e => setErr(String(e.message ?? e))) }, [])
  return (
    <div className="h-full min-h-[560px] md:h-screen">
      {ds ? <Observatory dataset={ds} /> : <div className="grid h-full place-items-center text-sm text-silver-500">{err ? `Could not load demo data: ${err}` : 'Loading the DEMO universe…'}</div>}
    </div>
  )
}
