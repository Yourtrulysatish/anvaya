import type { AgentInfo, SimEvent } from './types'
import { INTERACTION_TYPES } from './types'

/** Deterministic state reconstructed purely from recorded events (never from anything else). */
export class SimState {
  n: number
  topic: string
  opinion: Float32Array
  sentiment: Float32Array
  group: Int16Array
  lastActiveRound: Int32Array
  influenceTotal: Float32Array
  actions: Uint16Array
  ties = new Map<number, number>() // directed key a*n+b
  groupNames = new Map<number, string>()
  round = 0
  interactions = 0
  activeThisRound = new Set<number>()
  metrics: Record<string, any> | null = null
  edgesVersion = 0
  ended = false

  constructor(agents: AgentInfo[], topic: string) {
    this.n = agents.length
    this.topic = topic
    this.opinion = new Float32Array(this.n)
    this.sentiment = new Float32Array(this.n)
    this.group = new Int16Array(this.n).fill(-1)
    this.lastActiveRound = new Int32Array(this.n).fill(-1)
    this.influenceTotal = new Float32Array(this.n)
    this.actions = new Uint16Array(this.n)
    agents.forEach((a, i) => { this.opinion[i] = a.opinions[topic] ?? 0 })
  }

  clone(): SimState {
    const s = Object.create(SimState.prototype) as SimState
    Object.assign(s, this)
    s.opinion = this.opinion.slice(); s.sentiment = this.sentiment.slice(); s.group = this.group.slice()
    s.lastActiveRound = this.lastActiveRound.slice(); s.influenceTotal = this.influenceTotal.slice(); s.actions = this.actions.slice()
    s.ties = new Map(this.ties); s.groupNames = new Map(this.groupNames); s.activeThisRound = new Set(this.activeThisRound)
    return s
  }

  tieKey(a: number, b: number) { return a * this.n + b }

  apply(ev: SimEvent) {
    switch (ev.type) {
      case 'sim_start':
        for (const [a, b, w] of (ev.result.edges ?? []) as [number, number, number][]) {
          this.ties.set(this.tieKey(a, b), w); this.ties.set(this.tieKey(b, a), w)
        }
        this.edgesVersion++
        break
      case 'round_start': this.round = ev.round; this.activeThisRound.clear(); break
      case 'round_end': this.metrics = ev.result; break
      case 'sim_end': this.metrics = ev.result; this.ended = true; break
    }
    if (INTERACTION_TYPES.includes(ev.type)) {
      this.interactions++
      if (ev.source_agent != null) {
        this.activeThisRound.add(ev.source_agent)
        this.lastActiveRound[ev.source_agent] = ev.round
        this.actions[ev.source_agent]++
      }
    }
    const sc = ev.state_changes
    if (!sc) return
    if (sc.opinion) {
      for (const [k, v] of Object.entries(sc.opinion)) {
        const i = +k
        if (v.topic === this.topic) this.opinion[i] = v.to
        if (ev.source_agent != null && ev.source_agent !== i && INTERACTION_TYPES.includes(ev.type))
          this.influenceTotal[ev.source_agent] += Math.abs(v.to - v.from)
      }
    }
    if (sc.sentiment) for (const [k, v] of Object.entries(sc.sentiment)) this.sentiment[+k] = v
    if (sc.group) for (const [k, v] of Object.entries(sc.group)) this.group[+k] = v == null ? -1 : v
    if (ev.type === 'join_group' && ev.result.group != null) this.groupNames.set(ev.result.group, ev.result.group_name)
    if (sc.relationships?.length) {
      for (const r of sc.relationships) { this.ties.set(this.tieKey(r.a, r.b), r.to) }
      this.edgesVersion++
    }
  }

  influence(i: number): number {
    let mx = 0
    for (let k = 0; k < this.n; k++) if (this.influenceTotal[k] > mx) mx = this.influenceTotal[k]
    return mx ? this.influenceTotal[i] / mx : 0
  }

  /** Undirected edges using the stronger direction. */
  edgeList(minW = 0.12): [number, number, number][] {
    const best = new Map<number, number>()
    for (const [k, w] of this.ties) {
      const a = Math.floor(k / this.n), b = k % this.n
      if (a === b) continue
      const lo = Math.min(a, b), hi = Math.max(a, b), key = lo * this.n + hi
      if (w > (best.get(key) ?? -1)) best.set(key, w)
    }
    const out: [number, number, number][] = []
    for (const [key, w] of best) if (w >= minW) out.push([Math.floor(key / this.n), key % this.n, w])
    return out
  }
}

const COST: Record<string, number> = {
  post: 1, reply: 1, agree: 0.9, disagree: 1, share: 1, round_start: 2.2, round_end: 0.4, external_event: 6,
  opinion_change: 0.7, cascade: 0.8, join_group: 0.12, leave_group: 0.12, relationship_change: 0.5, sim_start: 1, sim_end: 1,
  sim_pause: 0.1, sim_resume: 0.1, error: 0.3,
}
const EV_PER_SEC = 10
const CHECKPOINT_EVERY = 120

export class Playback {
  events: SimEvent[] = []
  state: SimState
  cursor = 0
  playing = false
  speed = 1
  live = false
  private acc = 0
  private checkpoints: { idx: number; state: SimState }[] = []
  onEvent?: (ev: SimEvent) => void
  /** index of events for each agent (indices into events[]) */
  byAgent = new Map<number, number[]>()
  private indexed = 0

  agents: AgentInfo[]
  topic: string
  constructor(agents: AgentInfo[], topic: string) {
    this.agents = agents; this.topic = topic
    this.state = new SimState(agents, topic)
    this.checkpoints.push({ idx: 0, state: this.state.clone() })
  }

  get total() { return this.events.length }
  get atEnd() { return this.cursor >= this.events.length }

  append(evs: SimEvent[]) {
    const have = new Set<string>()
    // duplicate prevention + ordering by seq
    if (this.events.length) for (let i = Math.max(0, this.events.length - 400); i < this.events.length; i++) have.add(this.events[i].id)
    const fresh = evs.filter(e => !have.has(e.id) && (!this.events.length || e.seq > this.events[this.events.length - 1].seq))
    fresh.sort((a, b) => a.seq - b.seq)
    for (const e of fresh) this.events.push(e)
    this.indexNew()
    this.ensureInit()
  }

  setEvents(evs: SimEvent[]) { this.events = evs; this.indexed = 0; this.byAgent.clear(); this.indexNew(); this.ensureInit() }

  /** `sim_start` carries the initial network; apply it immediately so the universe has its topology before play. */
  private ensureInit() {
    if (this.cursor === 0 && this.events[0]?.type === 'sim_start') {
      this.state.apply(this.events[0]); this.cursor = 1
      this.checkpoints = [{ idx: 1, state: this.state.clone() }]
    }
  }
  get base() { return this.checkpoints[0].idx }

  private indexNew() {
    for (; this.indexed < this.events.length; this.indexed++) {
      const ev = this.events[this.indexed]
      if (ev.type === 'round_start' || ev.type === 'round_end' || ev.type === 'sim_start' || ev.type === 'sim_end') continue
      const ids = new Set<number>(ev.agents)
      if (ev.source_agent != null) ids.add(ev.source_agent)
      if (ev.target_agent != null) ids.add(ev.target_agent)
      if (ev.type === 'external_event') continue // too broad to index per agent
      for (const id of ids) { let l = this.byAgent.get(id); if (!l) this.byAgent.set(id, l = []); l.push(this.indexed) }
    }
  }

  private applyOne(silent: boolean) {
    const ev = this.events[this.cursor]
    this.state.apply(ev)
    this.cursor++
    if (this.cursor % CHECKPOINT_EVERY === 0 && !this.checkpoints.find(c => c.idx === this.cursor))
      this.checkpoints.push({ idx: this.cursor, state: this.state.clone() })
    if (!silent) this.onEvent?.(ev)
  }

  tick(dt: number) {
    if (!this.playing) return
    this.acc += dt * this.speed * EV_PER_SEC
    let guard = 0
    while (this.cursor < this.events.length && guard++ < 400) {
      const need = COST[this.events[this.cursor].type] ?? 0.5
      if (this.acc < need) break
      this.acc -= need
      this.applyOne(false)
    }
    if (this.cursor >= this.events.length) { this.acc = 0; if (!this.live) this.playing = false }
  }

  seek(idx: number) {
    idx = Math.max(this.base, Math.min(this.events.length, idx))
    if (idx === this.cursor) return
    let cp = this.checkpoints[0]
    for (const c of this.checkpoints) if (c.idx <= idx) cp = c
    if (idx >= this.cursor && this.cursor >= cp.idx) { /* forward: continue from live state */ } else { this.state = cp.state.clone(); this.cursor = cp.idx }
    while (this.cursor < idx) this.applyOne(true)
    this.acc = 0
  }

  stepForward() { this.playing = false; if (this.cursor < this.events.length) this.applyOne(false) }
  /** Step back to the previous *meaningful* event (skips bookkeeping events). */
  stepBack() {
    this.playing = false
    let i = this.cursor - 1
    while (i > this.base && ['round_start', 'round_end', 'join_group'].includes(this.events[i - 1]?.type)) i--
    this.seek(Math.max(this.base, i))
  }
  seekRound(r: number) {
    const i = this.events.findIndex(e => e.type === 'round_start' && e.round >= r)
    this.seek(i < 0 ? this.events.length : i)
  }
  restart(play = true) { this.state = this.checkpoints[0].state.clone(); this.cursor = this.checkpoints[0].idx; this.acc = 0; this.playing = play }
}
