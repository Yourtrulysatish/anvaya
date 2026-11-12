import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type Simulation } from 'd3-force'
import type { AgentInfo, SimEvent } from '../lib/types'
import type { SimState } from '../lib/simState'

export type Mode = 'social' | 'influence' | 'network'

interface Node { id: number; x: number; y: number; vx: number; vy: number; r: number }
interface Link { source: number | Node; target: number | Node; w: number }
interface Particle { a: number; b: number; t: number; dur: number; color: string; kind: 'msg' | 'zig' | 'cascade'; delay: number; onArrive?: () => void }
interface Pulse { id: number; t: number; dur: number; color: string; maxR: number; width: number }
interface Bubble { id: number; text: string; t: number; dur: number; color: string }
interface Shock { t: number; dur: number }

export const COLORS = {
  support: [61, 220, 255], neutral: [138, 147, 163], oppose: [255, 122, 89],
  agree: '#5EE6FF', disagree: '#FF5C7A', reply: '#C9CED6', share: '#A78BFA', post: '#E8EAEE', cascade: '#F5C26B', accent: '#8B5CF6',
} as const

export function opinionColor(x: number, alpha = 1): string {
  const t = Math.max(-1, Math.min(1, x))
  const [a, b] = t >= 0 ? [COLORS.neutral, COLORS.support] : [COLORS.neutral, COLORS.oppose]
  const k = Math.min(1, Math.abs(t) * 1.25)
  const c = [0, 1, 2].map(i => Math.round(a[i] + (b[i] - a[i]) * k))
  return `rgba(${c[0]},${c[1]},${c[2]},${alpha})`
}

const GROUP_HUES = [265, 190, 330, 45, 150, 15, 215, 295]

export class UniverseRenderer {
  private ctx: CanvasRenderingContext2D
  private nodes: Node[] = []
  private sim: Simulation<Node, Link>
  private links: Link[] = []
  private edgesVersion = -1
  private w = 800
  private h = 600
  private dpr = 1
  cam = { x: 0, y: 0, k: 1 }
  private camT = { x: 0, y: 0, k: 1 }
  private particles: Particle[] = []
  private pulses: Pulse[] = []
  private bubbles: Bubble[] = []
  private shocks: Shock[] = []
  private heat = new Map<number, { h: number; color: string }>()
  mode: Mode = 'social'
  highlight: Set<number> | null = null
  selected: number | null = null
  hovered: number | null = null
  speed = 1
  state!: SimState
  onSelect?: (id: number | null) => void
  onHover?: (id: number | null, x: number, y: number) => void
  private dragging: null | { x: number; y: number; moved: boolean } = null
  private raf = 0
  private last = 0
  private infl: Float32Array
  private groupCentroids = new Map<number, [number, number]>()
  private userMovedCam = false
  private ro: ResizeObserver
  private stopped = false

  private canvas: HTMLCanvasElement
  private agents: AgentInfo[]
  constructor(canvas: HTMLCanvasElement, agents: AgentInfo[]) {
    this.canvas = canvas; this.agents = agents
    this.ctx = canvas.getContext('2d')!
    this.infl = new Float32Array(agents.length)
    const n = agents.length
    this.nodes = agents.map((a, i) => {
      const ang = i * 2.399963, rad = Math.sqrt(i + 1) * 15
      return { id: i, x: Math.cos(ang) * rad, y: Math.sin(ang) * rad, vx: 0, vy: 0, r: 3.5 + 4 * Math.sqrt(a.influence) }
    })
    this.sim = forceSimulation<Node, Link>(this.nodes)
      .force('charge', forceManyBody<Node>().strength(-30).distanceMax(220))
      .force('collide', forceCollide<Node>().radius(d => d.r + 1.5))
      .force('x', forceX<Node>(0).strength(0.02))
      .force('y', forceY<Node>(0).strength(0.02))
      .force('link', forceLink<Node, Link>([]).id(d => d.id).distance(l => 46 - 24 * (l as Link).w).strength(l => 0.03 + 0.25 * (l as Link).w))
      .force('cluster', () => {})
      .stop()
    this.sim.alpha(1).alphaDecay(0.02).velocityDecay(0.35)
    this.setMode('social', false)
    void n
    this.ro = new ResizeObserver(() => this.resize())
    this.ro.observe(canvas)
    this.resize()
    this.bind()
    this.raf = requestAnimationFrame(t => this.loop(t))
  }

  destroy() { this.stopped = true; cancelAnimationFrame(this.raf); this.ro.disconnect(); this.unbind?.() }

  // ------------------------------------------------------------------ setup
  private unbind?: () => void
  private resize() {
    const r = this.canvas.getBoundingClientRect()
    this.dpr = Math.min(2, window.devicePixelRatio || 1)
    this.w = Math.max(200, r.width); this.h = Math.max(200, r.height)
    this.canvas.width = this.w * this.dpr; this.canvas.height = this.h * this.dpr
    if (!this.userMovedCam) this.fit(false)
  }

  setMode(mode: Mode, reheat = true) {
    this.mode = mode
    const charge = this.sim.force('charge') as ReturnType<typeof forceManyBody<Node>>
    charge.strength(mode === 'network' ? -22 : mode === 'influence' ? -16 : -34)
    const link = this.sim.force('link') as ReturnType<typeof forceLink<Node, Link>>
    link.strength(l => (mode === 'network' ? 0.06 : mode === 'social' ? 0.03 : 0.0) + (mode === 'influence' ? 0 : 0.22 * (l as Link).w))
    ;(this.sim.force('x') as ReturnType<typeof forceX<Node>>).strength(mode === 'influence' ? 0 : 0.02)
    ;(this.sim.force('y') as ReturnType<typeof forceY<Node>>).strength(mode === 'influence' ? 0 : 0.02)
    if (mode === 'social') {
      this.sim.force('cluster', (alpha: number) => {
        this.computeCentroids()
        for (const nd of this.nodes) {
          const g = this.state?.group[nd.id]
          if (g == null || g < 0) continue
          const c = this.groupCentroids.get(g); if (!c) continue
          nd.vx += (c[0] - nd.x) * 0.09 * alpha; nd.vy += (c[1] - nd.y) * 0.09 * alpha
        }
      })
    } else if (mode === 'influence') {
      const R = Math.sqrt(this.nodes.length) * 22
      this.sim.force('cluster', (alpha: number) => {
        for (const nd of this.nodes) {
          const target = R * (1 - Math.pow(this.infl[nd.id], 0.7)) * 0.95 + 14
          const d = Math.hypot(nd.x, nd.y) || 1
          const k = ((target - d) / d) * 0.45 * alpha
          nd.vx += nd.x * k; nd.vy += nd.y * k
        }
      })
    } else {
      this.sim.force('cluster', () => {})
    }
    if (reheat) this.sim.alpha(0.9)
  }

  private computeCentroids() {
    const acc = new Map<number, [number, number, number]>()
    for (const nd of this.nodes) {
      const g = this.state?.group[nd.id]
      if (g == null || g < 0) continue
      const a = acc.get(g) ?? [0, 0, 0]; a[0] += nd.x; a[1] += nd.y; a[2]++; acc.set(g, a)
    }
    this.groupCentroids.clear()
    for (const [g, a] of acc) this.groupCentroids.set(g, [a[0] / a[2], a[1] / a[2]])
  }

  private syncEdges() {
    if (this.edgesVersion === this.state.edgesVersion) return
    this.edgesVersion = this.state.edgesVersion
    this.links = this.state.edgeList(0.12).map(([a, b, w]) => ({ source: a, target: b, w }))
    const link = this.sim.force('link') as ReturnType<typeof forceLink<Node, Link>>
    link.links(this.links)
    this.sim.alpha(Math.max(this.sim.alpha(), 0.25))
  }

  // ------------------------------------------------------------------ camera
  fit(animate = true) {
    let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9
    for (const n of this.nodes) { minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x); minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y) }
    const pad = 70
    const k = Math.min((this.w - pad * 2) / Math.max(50, maxX - minX), (this.h - pad * 2) / Math.max(50, maxY - minY), 2.2)
    this.camT = { k, x: -((minX + maxX) / 2) * k, y: -((minY + maxY) / 2) * k }
    if (!animate) this.cam = { ...this.camT }
  }
  focus(ids: number[]) {
    if (!ids.length) return
    let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9
    for (const i of ids) { const n = this.nodes[i]; if (!n) continue; minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x); minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y) }
    const k = Math.min((this.w * 0.5) / Math.max(120, maxX - minX), (this.h * 0.5) / Math.max(120, maxY - minY), 2.6)
    this.camT = { k, x: -((minX + maxX) / 2) * k, y: -((minY + maxY) / 2) * k }
    this.userMovedCam = true
  }
  private toWorld(px: number, py: number) { return { x: (px - this.w / 2 - this.cam.x) / this.cam.k, y: (py - this.h / 2 - this.cam.y) / this.cam.k } }
  private nodeAt(px: number, py: number): number | null {
    const p = this.toWorld(px, py); let best: number | null = null, bd = 1e9
    for (const n of this.nodes) { const d = Math.hypot(n.x - p.x, n.y - p.y); const rr = this.radius(n) + 5 / this.cam.k; if (d < rr && d < bd) { bd = d; best = n.id } }
    return best
  }
  nodePos(id: number) { const n = this.nodes[id]; return { x: n.x * this.cam.k + this.w / 2 + this.cam.x, y: n.y * this.cam.k + this.h / 2 + this.cam.y } }

  private bind() {
    const c = this.canvas
    const pos = (e: PointerEvent | WheelEvent) => { const r = c.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top } }
    const down = (e: PointerEvent) => { const p = pos(e); this.dragging = { x: p.x, y: p.y, moved: false }; c.setPointerCapture(e.pointerId) }
    const move = (e: PointerEvent) => {
      const p = pos(e)
      if (this.dragging) {
        const dx = p.x - this.dragging.x, dy = p.y - this.dragging.y
        if (Math.abs(dx) + Math.abs(dy) > 3) this.dragging.moved = true
        if (this.dragging.moved) { this.camT.x += dx; this.camT.y += dy; this.cam.x += dx; this.cam.y += dy; this.userMovedCam = true }
        this.dragging.x = p.x; this.dragging.y = p.y
      } else {
        const id = this.nodeAt(p.x, p.y)
        if (id !== this.hovered) { this.hovered = id; this.onHover?.(id, p.x, p.y); c.style.cursor = id != null ? 'pointer' : 'grab' }
      }
    }
    const up = (e: PointerEvent) => {
      const p = pos(e)
      if (this.dragging && !this.dragging.moved) { const id = this.nodeAt(p.x, p.y); this.selected = id; this.onSelect?.(id) }
      this.dragging = null
    }
    const wheel = (e: WheelEvent) => {
      e.preventDefault()
      const p = pos(e); const f = Math.exp(-e.deltaY * 0.0015)
      const k0 = this.camT.k, k1 = Math.max(0.2, Math.min(7, k0 * f))
      const wx = (p.x - this.w / 2 - this.camT.x) / k0, wy = (p.y - this.h / 2 - this.camT.y) / k0
      this.camT = { k: k1, x: p.x - this.w / 2 - wx * k1, y: p.y - this.h / 2 - wy * k1 }
      this.userMovedCam = true
    }
    c.addEventListener('pointerdown', down); c.addEventListener('pointermove', move); c.addEventListener('pointerup', up)
    c.addEventListener('wheel', wheel, { passive: false })
    c.style.cursor = 'grab'; c.style.touchAction = 'none'
    this.unbind = () => { c.removeEventListener('pointerdown', down); c.removeEventListener('pointermove', move); c.removeEventListener('pointerup', up); c.removeEventListener('wheel', wheel) }
  }

  // ------------------------------------------------------------------ effects (only ever triggered from recorded events)
  private dur() { return 0.85 / Math.sqrt(Math.max(0.5, this.speed)) }

  handleEvent(ev: SimEvent) {
    const s = ev.source_agent, t = ev.target_agent
    const base = this.dur()
    const op = (i: number) => this.state.opinion[i]
    switch (ev.type) {
      case 'post': {
        if (s == null) break
        this.pulses.push({ id: s, t: 0, dur: base * 1.1, color: opinionColor(op(s)), maxR: 34, width: 2 })
        const aud: number[] = ev.result.audience ?? (t != null ? [t] : [])
        aud.slice(0, 6).forEach((a, i) => this.particles.push({ a: s, b: a, t: 0, dur: base, delay: i * 0.05, color: COLORS.post, kind: 'msg', onArrive: () => { this.pulses.push({ id: a, t: 0, dur: base * 0.7, color: COLORS.post, maxR: 16, width: 1.2 }); this.bump(s, a, COLORS.post) } }))
        if (ev.content) this.bubbles.push({ id: s, text: ev.content, t: 0, dur: 3.2 / Math.sqrt(this.speed), color: opinionColor(op(s)) })
        break
      }
      case 'reply': case 'agree': case 'disagree': case 'share': {
        if (s == null || t == null) break
        const color = COLORS[ev.type]
        this.pulses.push({ id: s, t: 0, dur: base * 0.8, color, maxR: 22, width: 2 })
        this.particles.push({ a: s, b: t, t: 0, dur: base, delay: 0, color, kind: ev.type === 'disagree' ? 'zig' : 'msg', onArrive: () => {
          this.pulses.push({ id: t, t: 0, dur: base, color, maxR: ev.type === 'disagree' ? 30 : 24, width: ev.type === 'disagree' ? 2.6 : 1.6 })
          this.bump(s, t, color)
          if (ev.content) this.bubbles.push({ id: t, text: ev.content, t: 0, dur: 3 / Math.sqrt(this.speed), color })
        } })
        if (ev.type === 'share') (ev.result.audience ?? []).slice(0, 4).forEach((a: number, i: number) =>
          this.particles.push({ a: s, b: a, t: 0, dur: base * 1.1, delay: 0.25 + i * 0.06, color: COLORS.cascade, kind: 'cascade', onArrive: () => this.bump(s, a, COLORS.cascade) }))
        break
      }
      case 'opinion_change':
        if (t != null) this.pulses.push({ id: t, t: 0, dur: base * 1.5, color: opinionColor(ev.result.to ?? 0), maxR: 42, width: 3.2 })
        break
      case 'join_group': if (s != null) this.pulses.push({ id: s, t: 0, dur: base * 1.2, color: COLORS.accent, maxR: 18, width: 1.4 }); break
      case 'relationship_change': if (s != null && t != null) { this.bump(s, t, COLORS.agree, 1); this.pulses.push({ id: s, t: 0, dur: base, color: COLORS.agree, maxR: 18, width: 1.2 }, { id: t, t: 0, dur: base, color: COLORS.agree, maxR: 18, width: 1.2 }) } break
      case 'cascade': if (s != null) this.pulses.push({ id: s, t: 0, dur: base * 2, color: COLORS.cascade, maxR: 60, width: 3 }); break
      case 'external_event':
        this.shocks.push({ t: 0, dur: 2.4 })
        ev.agents.slice(0, 60).forEach((a, i) => this.pulses.push({ id: a, t: -i * 0.012, dur: base * 1.3, color: COLORS.cascade, maxR: 20, width: 1.4 }))
        this.bubbles.push({ id: -1, text: ev.content, t: 0, dur: 5, color: COLORS.cascade })
        break
    }
    if (this.bubbles.length > 4) this.bubbles.splice(0, this.bubbles.length - 4)
    if (this.particles.length > 260) this.particles.splice(0, this.particles.length - 260)
  }

  private bump(a: number, b: number, color: string, amt = 0.8) {
    const key = Math.min(a, b) * this.nodes.length + Math.max(a, b)
    const h = this.heat.get(key); this.heat.set(key, { h: Math.min(1.5, (h?.h ?? 0) + amt), color })
  }

  clearEffects() { this.particles = []; this.pulses = []; this.bubbles = []; this.shocks = []; this.heat.clear() }

  // ------------------------------------------------------------------ frame
  private loop(ts: number) {
    if (this.stopped) return
    const dt = Math.min(0.05, (ts - (this.last || ts)) / 1000); this.last = ts
    this.step(dt); this.draw()
    this.raf = requestAnimationFrame(t => this.loop(t))
  }

  private step(dt: number) {
    if (!this.state) return
    this.syncEdges()
    let mx = 0
    for (let i = 0; i < this.infl.length; i++) { this.infl[i] = this.state.influenceTotal[i]; if (this.infl[i] > mx) mx = this.infl[i] }
    if (mx) for (let i = 0; i < this.infl.length; i++) this.infl[i] /= mx
    for (const n of this.nodes) {
      n.r = this.mode === 'influence' ? 3 + 11 * Math.sqrt(this.infl[n.id]) : 3.5 + 4 * Math.sqrt(this.agents[n.id].influence) + (this.mode === 'network' ? -0.8 : 0)
    }
    if (this.sim.alpha() > this.sim.alphaMin()) this.sim.tick()
    else if (this.mode !== 'network') this.sim.alpha(0.012) // keep a slow living drift
    const e = 1 - Math.exp(-dt * 6)
    this.cam.k += (this.camT.k - this.cam.k) * e; this.cam.x += (this.camT.x - this.cam.x) * e; this.cam.y += (this.camT.y - this.cam.y) * e
    for (const p of this.particles) { if (p.delay > 0) p.delay -= dt; else p.t += dt / p.dur }
    for (let i = this.particles.length - 1; i >= 0; i--) if (this.particles[i].t >= 1) { this.particles[i].onArrive?.(); this.particles.splice(i, 1) }
    for (const p of this.pulses) p.t += dt / p.dur
    this.pulses = this.pulses.filter(p => p.t < 1)
    for (const b of this.bubbles) b.t += dt / b.dur
    this.bubbles = this.bubbles.filter(b => b.t < 1)
    for (const s of this.shocks) s.t += dt / s.dur
    this.shocks = this.shocks.filter(s => s.t < 1)
    for (const [k, v] of this.heat) { v.h -= dt * 0.18; if (v.h <= 0) this.heat.delete(k) }
    void dt
  }

  private radius(n: Node) { return n.r }

  private draw() {
    const c = this.ctx, st = this.state
    c.setTransform(this.dpr, 0, 0, this.dpr, 0, 0)
    c.clearRect(0, 0, this.w, this.h)
    if (!st) return
    const g = c.createRadialGradient(this.w / 2, this.h / 2, 10, this.w / 2, this.h / 2, Math.max(this.w, this.h) * 0.7)
    g.addColorStop(0, '#0e1016'); g.addColorStop(1, '#06070a'); c.fillStyle = g; c.fillRect(0, 0, this.w, this.h)
    c.save(); c.translate(this.w / 2 + this.cam.x, this.h / 2 + this.cam.y); c.scale(this.cam.k, this.cam.k)
    const k = this.cam.k, hl = this.highlight
    const dim = (id: number) => (hl && !hl.has(id) ? 0.18 : 1)

    // group territories (social + network modes) – only from computed group assignments
    if (this.mode !== 'influence') this.drawGroups(c)

    // edges
    const edgeAlpha = this.mode === 'network' ? 0.22 : this.mode === 'social' ? 0.1 : 0.03
    c.lineCap = 'round'
    for (const bucket of [0, 1, 2]) {
      c.beginPath()
      for (const l of this.links) {
        const w = l.w; if ((w < 0.4 ? 0 : w < 0.65 ? 1 : 2) !== bucket) continue
        const a = l.source as Node, b = l.target as Node
        if (hl && !(hl.has(a.id) && hl.has(b.id))) continue
        c.moveTo(a.x, a.y); c.lineTo(b.x, b.y)
      }
      c.strokeStyle = `rgba(190,200,220,${edgeAlpha * (0.6 + bucket * 0.5)})`; c.lineWidth = (0.5 + bucket * 0.4) / Math.sqrt(k); c.stroke()
    }
    // hot edges (recent interactions)
    for (const [key, v] of this.heat) {
      const n = this.nodes.length, a = this.nodes[Math.floor(key / n)], b = this.nodes[key % n]
      c.beginPath(); c.moveTo(a.x, a.y); c.lineTo(b.x, b.y)
      c.strokeStyle = withAlpha(v.color, Math.min(0.85, v.h * 0.6)); c.lineWidth = (1 + v.h * 1.4) / Math.sqrt(k); c.stroke()
    }

    // shockwave
    for (const s of this.shocks) {
      const R = Math.max(this.w, this.h) / k * 0.9 * easeOut(s.t)
      c.beginPath(); c.arc(0, 0, R, 0, Math.PI * 2); c.strokeStyle = withAlpha(COLORS.cascade, 0.5 * (1 - s.t)); c.lineWidth = 3 / k; c.stroke()
    }

    // nodes
    for (const n of this.nodes) {
      const a = dim(n.id)
      const ag = this.agents[n.id]
      const recent = st.lastActiveRound[n.id] >= 0 && st.round - st.lastActiveRound[n.id] <= 1
      const col = this.mode === 'network' && st.group[n.id] >= 0 ? `hsla(${GROUP_HUES[st.group[n.id] % GROUP_HUES.length]},70%,62%,${a})` : opinionColor(st.opinion[n.id], a)
      if (recent && a === 1) { c.beginPath(); c.arc(n.x, n.y, n.r + 3.2, 0, Math.PI * 2); c.fillStyle = withAlpha('#ffffff', 0.07); c.fill() }
      c.beginPath(); c.arc(n.x, n.y, n.r, 0, Math.PI * 2); c.fillStyle = col; c.fill()
      if (this.mode === 'network' && ag) { /* flat in network mode */ } else { c.strokeStyle = `rgba(255,255,255,${0.14 * a})`; c.lineWidth = 0.6 / k; c.stroke() }
    }

    // pulses
    for (const p of this.pulses) {
      if (p.t < 0) continue
      const n = this.nodes[p.id]; if (!n) continue
      const r = n.r + (p.maxR / Math.sqrt(k)) * easeOut(p.t)
      c.beginPath(); c.arc(n.x, n.y, r, 0, Math.PI * 2); c.strokeStyle = withAlpha(p.color, 0.9 * (1 - p.t)); c.lineWidth = p.width / Math.sqrt(k); c.stroke()
    }

    // particles
    for (const p of this.particles) {
      if (p.delay > 0) continue
      const A = this.nodes[p.a], B = this.nodes[p.b]; if (!A || !B) continue
      const t = easeInOut(p.t)
      let x = A.x + (B.x - A.x) * t, y = A.y + (B.y - A.y) * t
      if (p.kind === 'zig') { const dx = B.x - A.x, dy = B.y - A.y, L = Math.hypot(dx, dy) || 1; const off = Math.sin(p.t * 26) * 5 * (1 - p.t); x += (-dy / L) * off; y += (dx / L) * off }
      const t0 = Math.max(0, t - 0.18)
      c.beginPath(); c.moveTo(A.x + (B.x - A.x) * t0, A.y + (B.y - A.y) * t0); c.lineTo(x, y)
      c.strokeStyle = withAlpha(p.color, 0.55); c.lineWidth = 2 / Math.sqrt(k); c.stroke()
      const grd = c.createRadialGradient(x, y, 0, x, y, 9 / Math.sqrt(k)); grd.addColorStop(0, withAlpha(p.color, 0.95)); grd.addColorStop(1, withAlpha(p.color, 0))
      c.fillStyle = grd; c.beginPath(); c.arc(x, y, 9 / Math.sqrt(k), 0, Math.PI * 2); c.fill()
      c.beginPath(); c.arc(x, y, (p.kind === 'cascade' ? 2.4 : 2.8) / Math.sqrt(k), 0, Math.PI * 2); c.fillStyle = '#fff'; c.fill()
    }

    // selection / hover rings
    for (const id of [this.selected, this.hovered]) {
      if (id == null) continue; const n = this.nodes[id]
      c.beginPath(); c.arc(n.x, n.y, n.r + 4 / Math.sqrt(k), 0, Math.PI * 2)
      c.strokeStyle = id === this.selected ? COLORS.accent : 'rgba(255,255,255,0.6)'; c.lineWidth = (id === this.selected ? 2 : 1) / Math.sqrt(k); c.stroke()
    }
    if (hl) for (const id of hl) { const n = this.nodes[id]; if (!n) continue; c.beginPath(); c.arc(n.x, n.y, n.r + 3.5 / Math.sqrt(k), 0, Math.PI * 2); c.strokeStyle = '#fff'; c.lineWidth = 1.4 / Math.sqrt(k); c.stroke() }
    c.restore()

    // screen-space labels & bubbles
    c.font = '500 11px "JetBrains Mono", ui-monospace, monospace'; c.textBaseline = 'middle'
    const labelIds = new Set<number>()
    if (this.selected != null) labelIds.add(this.selected)
    if (this.hovered != null) labelIds.add(this.hovered)
    if (hl) for (const id of hl) labelIds.add(id)
    if (this.cam.k > 2.6) for (const n of this.nodes) if (n.r > 7) labelIds.add(n.id)
    for (const id of labelIds) {
      const p = this.nodePos(id); const nm = this.agents[id].name
      c.fillStyle = 'rgba(232,234,238,0.92)'; c.fillText(nm, p.x + this.nodes[id].r * this.cam.k + 6, p.y)
    }
    if (this.mode === 'social') this.drawGroupLabels(c)
    this.drawBubbles(c)
  }

  private drawGroups(c: CanvasRenderingContext2D) {
    const st = this.state, groups = new Map<number, Node[]>()
    for (const n of this.nodes) { const g = st.group[n.id]; if (g >= 0) { const l = groups.get(g) ?? []; l.push(n); groups.set(g, l) } }
    for (const [g, ns] of groups) {
      if (ns.length < 4) continue
      const hull = convexHull(ns.map(n => [n.x, n.y] as [number, number]))
      if (hull.length < 3) continue
      const mean = ns.reduce((s, n) => s + st.opinion[n.id], 0) / ns.length
      const hue = GROUP_HUES[g % GROUP_HUES.length]
      c.beginPath(); hull.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y))); c.closePath()
      c.lineJoin = 'round'
      c.fillStyle = this.mode === 'network' ? `hsla(${hue},60%,55%,0.05)` : opinionColor(mean, 0.05)
      c.strokeStyle = this.mode === 'network' ? `hsla(${hue},60%,55%,0.10)` : opinionColor(mean, 0.1)
      c.lineWidth = 34; c.stroke(); c.fill()
    }
  }

  private drawGroupLabels(c: CanvasRenderingContext2D) {
    if (this.cam.k < 0.5) return
    this.computeCentroids()
    c.font = '500 10px "JetBrains Mono", ui-monospace, monospace'; c.textAlign = 'center'
    const sizes = new Map<number, number>()
    for (const n of this.nodes) { const g = this.state.group[n.id]; if (g >= 0) sizes.set(g, (sizes.get(g) ?? 0) + 1) }
    for (const [g, cen] of this.groupCentroids) {
      if ((sizes.get(g) ?? 0) < 6) continue
      const name = this.state.groupNames.get(g); if (!name) continue
      const x = cen[0] * this.cam.k + this.w / 2 + this.cam.x, y = cen[1] * this.cam.k + this.h / 2 + this.cam.y
      c.fillStyle = 'rgba(201,206,214,0.55)'; c.fillText(name.toUpperCase(), x, y - Math.sqrt(sizes.get(g)!) * 9 * this.cam.k * 0.7 - 6)
    }
    c.textAlign = 'start'
  }

  private drawBubbles(c: CanvasRenderingContext2D) {
    c.font = '400 12px "Inter Tight", system-ui, sans-serif'
    for (const b of this.bubbles) {
      const fade = b.t < 0.08 ? b.t / 0.08 : b.t > 0.8 ? (1 - b.t) / 0.2 : 1
      let x: number, y: number
      if (b.id < 0) { x = this.w / 2; y = 70 } else { const p = this.nodePos(b.id); x = p.x; y = p.y - 18 - this.nodes[b.id].r * this.cam.k }
      const text = b.text.length > 92 ? b.text.slice(0, 90) + '…' : b.text
      const words = text.split(' '); const lines: string[] = []; let cur = ''
      for (const wd of words) { if ((cur + ' ' + wd).length > 34) { lines.push(cur); cur = wd } else cur = (cur + ' ' + wd).trim() }
      lines.push(cur)
      const wMax = Math.max(...lines.map(l => c.measureText(l).width)) + 18, hh = lines.length * 15 + 12
      let bx = Math.min(Math.max(x - wMax / 2, 8), this.w - wMax - 8); const by = Math.max(8, y - hh)
      c.globalAlpha = fade * 0.96
      c.fillStyle = 'rgba(14,16,22,0.94)'; c.strokeStyle = withAlpha(b.color, 0.6); c.lineWidth = 1
      roundRect(c, bx, by, wMax, hh, 8); c.fill(); c.stroke()
      c.fillStyle = '#E8EAEE'; c.textBaseline = 'middle'
      lines.forEach((l, i) => c.fillText(l, bx + 9, by + 12 + i * 15))
      c.globalAlpha = 1
      bx = 0
    }
  }
}

function easeOut(t: number) { return 1 - Math.pow(1 - t, 3) }
function easeInOut(t: number) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2 }
function withAlpha(color: string, a: number): string {
  if (color.startsWith('rgba')) return color.replace(/[\d.]+\)$/, `${a})`)
  if (color.startsWith('#')) {
    const h = color.length === 4 ? color.slice(1).split('').map(x => x + x).join('') : color.slice(1)
    return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`
  }
  return color
}
function roundRect(c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath()
}
function convexHull(pts: [number, number][]): [number, number][] {
  const p = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]); if (p.length < 3) return p
  const cross = (o: number[], a: number[], b: number[]) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
  const lo: [number, number][] = []; for (const q of p) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q) }
  const up: [number, number][] = []; for (const q of p.reverse()) { while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q) }
  lo.pop(); up.pop(); return lo.concat(up)
}
