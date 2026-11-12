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

let vegeta: Promise<Dataset> | null = null
/** Vegeta x Nederland market-entry simulation (hypothetical). Resolves to a rejected promise if the file is not published. */
export function loadVegeta(): Promise<Dataset> {
  if (!vegeta) {
    vegeta = fetch(`${import.meta.env.BASE_URL}demo/vegeta_nl.json`).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() }).then(d => ({ meta: d.meta, agents: d.agents, events: d.events }))
    vegeta.catch(() => { vegeta = null })
  }
  return vegeta
}
