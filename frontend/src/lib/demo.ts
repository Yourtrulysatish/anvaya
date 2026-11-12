import type { Dataset } from './types'

let cache: Promise<Dataset> | null = null
export function loadDemo(): Promise<Dataset> {
  if (!cache) {
    cache = fetch(`${import.meta.env.BASE_URL}demo/run.json`).then(r => {
      if (!r.ok) throw new Error(`demo data HTTP ${r.status}`)
      return r.json()
    }).then(d => ({ meta: d.meta, agents: d.agents, events: d.events }))
    cache.catch(() => { cache = null })
  }
  return cache
}
