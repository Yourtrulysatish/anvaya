import { useEffect, useMemo, useRef, useState } from 'react'
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from 'd3-force'
import { Search } from 'lucide-react'

export interface KGNode { id: string; label: string; type: string; description: string; degree: number; mentions: number; cluster: number; sources: any[] }
export interface KGEdge { source: string; target: string; type: string; weight: number; evidence: any[] }
export interface KG { nodes: KGNode[]; edges: KGEdge[]; method?: string; synthetic?: boolean }

const TYPE_COLOR: Record<string, string> = { person: '#5EE6FF', organisation: '#A78BFA', product: '#F5C26B', event: '#FF7A59', topic: '#8A93A3', location: '#6EE7B7', stakeholder: '#F472B6', risk: '#FF5C7A', market: '#60A5FA', segment: '#A78BFA', agent: '#5EE6FF' }
const CLUSTER_HUES = [265, 190, 330, 45, 150, 15, 215, 295]

export function GraphExplorer({ kg, height = 560 }: { kg: KG; height?: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const [q, setQ] = useState(''); const [types, setTypes] = useState<Set<string>>(new Set())
  const [visible, setVisible] = useState<Set<string>>(new Set())
  const [sel, setSel] = useState<string | null>(null); const [colorBy, setColorBy] = useState<'type' | 'cluster'>('type')
  const stateRef = useRef({ q: '', types: new Set<string>(), sel: null as string | null, colorBy: 'type' as 'type' | 'cluster', visible: new Set<string>() })
  stateRef.current = { q, types, sel, colorBy, visible }

  const byId = useMemo(() => new Map(kg.nodes.map(n => [n.id, n])), [kg])
  const adj = useMemo(() => { const m = new Map<string, KGEdge[]>(); for (const e of kg.edges) { for (const k of [e.source, e.target]) { const l = m.get(k) ?? []; l.push(e); m.set(k, l) } } return m }, [kg])
  const allTypes = useMemo(() => [...new Set(kg.nodes.map(n => n.type))], [kg])

  useEffect(() => { // start with the most connected nodes; users expand from there
    const top = [...kg.nodes].sort((a, b) => b.degree - a.degree).slice(0, 45).map(n => n.id)
    setVisible(new Set(top)); setSel(null)
  }, [kg])

  const simRef = useRef<{ nodes: any[]; links: any[] }>({ nodes: [], links: [] })
  const cam = useRef({ x: 0, y: 0, k: 1 })
  const moved = useRef(false)

  useEffect(() => {
    const prev = new Map(simRef.current.nodes.map(n => [n.id, n]))
    const nodes = [...visible].map(id => prev.get(id) ?? { id, x: (Math.random() - 0.5) * 200, y: (Math.random() - 0.5) * 200 })
    const links = kg.edges.filter(e => visible.has(e.source) && visible.has(e.target)).map(e => ({ source: e.source, target: e.target, w: e.weight }))
    simRef.current = { nodes, links }
    const sim = forceSimulation(nodes as any).force('link', forceLink(links as any).id((d: any) => d.id).distance(95).strength(0.2))
      .force('charge', forceManyBody().strength(-280)).force('center', forceCenter(0, 0)).force('collide', forceCollide(18)).alpha(0.9)
    let raf = 0
    const draw = () => {
      const c = ref.current; if (!c) return
      const dpr = Math.min(2, devicePixelRatio || 1), r = c.getBoundingClientRect()
      if (c.width !== Math.round(r.width * dpr)) { c.width = Math.round(r.width * dpr); c.height = Math.round(r.height * dpr) }
      const g = c.getContext('2d')!; g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, r.width, r.height)
      if (!moved.current && nodes.length) { // auto-fit until the user pans/zooms
        let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9
        for (const n of nodes as any[]) { x0 = Math.min(x0, n.x); x1 = Math.max(x1, n.x); y0 = Math.min(y0, n.y); y1 = Math.max(y1, n.y) }
        const k = Math.min((r.width - 120) / Math.max(80, x1 - x0), (r.height - 100) / Math.max(80, y1 - y0), 3.2)
        const c2 = cam.current; c2.k += (k - c2.k) * 0.08; c2.x += (-((x0 + x1) / 2) * k - c2.x) * 0.08; c2.y += (-((y0 + y1) / 2) * k - c2.y) * 0.08
      }
      g.save(); g.translate(r.width / 2 + cam.current.x, r.height / 2 + cam.current.y); g.scale(cam.current.k, cam.current.k)
      const S = stateRef.current, ql = S.q.trim().toLowerCase()
      const match = (n: KGNode) => (!ql || n.label.toLowerCase().includes(ql)) && (S.types.size === 0 || S.types.has(n.type))
      const neigh = new Set<string>(); if (S.sel) { neigh.add(S.sel); (adj.get(S.sel) ?? []).forEach(e => { neigh.add(e.source); neigh.add(e.target) }) }
      for (const l of links as any[]) {
        const a = l.source, b = l.target; if (typeof a === 'string') continue
        const hot = S.sel && (a.id === S.sel || b.id === S.sel)
        g.strokeStyle = hot ? 'rgba(167,139,250,.85)' : 'rgba(190,200,220,.14)'; g.lineWidth = (hot ? 1.8 : 0.6 + Math.min(2, l.w * 0.3)) / Math.sqrt(cam.current.k)
        g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke()
      }
      for (const n of nodes as any[]) {
        const meta = byId.get(n.id)!; const ok = match(meta); const dim = (S.sel && !neigh.has(n.id)) || !ok
        const rad = 5 + Math.sqrt(meta.degree + 1) * 2.2
        g.globalAlpha = dim ? 0.18 : 1
        g.fillStyle = S.colorBy === 'type' ? (TYPE_COLOR[meta.type] ?? '#8A93A3') : `hsl(${CLUSTER_HUES[meta.cluster % CLUSTER_HUES.length]},65%,62%)`
        g.beginPath(); g.arc(n.x, n.y, rad, 0, Math.PI * 2); g.fill()
        if (n.id === S.sel) { g.strokeStyle = '#fff'; g.lineWidth = 2 / Math.sqrt(cam.current.k); g.stroke() }
        if ((!dim && (rad > 9 || cam.current.k > 1.3 || n.id === S.sel || (ql && ok))) ) { g.globalAlpha = dim ? 0.3 : 0.95; g.fillStyle = '#E8EAEE'; g.font = `${11 / Math.sqrt(cam.current.k)}px "Inter Tight", sans-serif`; g.fillText(meta.label.length > 30 ? meta.label.slice(0, 28) + '…' : meta.label, n.x + rad + 3, n.y + 3) }
        g.globalAlpha = 1
      }
      g.restore(); raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    return () => { cancelAnimationFrame(raf); sim.stop() }
  }, [visible, kg, byId, adj])

  // pan / zoom / select
  useEffect(() => {
    const c = ref.current!; let drag: { x: number; y: number; moved: boolean } | null = null
    const world = (px: number, py: number) => { const r = c.getBoundingClientRect(); return { x: (px - r.left - r.width / 2 - cam.current.x) / cam.current.k, y: (py - r.top - r.height / 2 - cam.current.y) / cam.current.k } }
    const down = (e: PointerEvent) => { drag = { x: e.clientX, y: e.clientY, moved: false }; c.setPointerCapture(e.pointerId) }
    const move = (e: PointerEvent) => { if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true; if (drag.moved) { moved.current = true; cam.current.x += dx; cam.current.y += dy; drag.x = e.clientX; drag.y = e.clientY } }
    const up = (e: PointerEvent) => {
      if (drag && !drag.moved) { const p = world(e.clientX, e.clientY); let best: string | null = null, bd = 1e9; for (const n of simRef.current.nodes) { const m = byId.get(n.id)!; const rad = 5 + Math.sqrt(m.degree + 1) * 2.2 + 3; const d = Math.hypot(n.x - p.x, n.y - p.y); if (d < rad && d < bd) { bd = d; best = n.id } } setSel(best) }
      drag = null
    }
    const wheel = (e: WheelEvent) => { e.preventDefault(); moved.current = true; const f = Math.exp(-e.deltaY * 0.0015); cam.current.k = Math.max(0.25, Math.min(6, cam.current.k * f)) }
    c.addEventListener('pointerdown', down); c.addEventListener('pointermove', move); c.addEventListener('pointerup', up); c.addEventListener('wheel', wheel, { passive: false })
    return () => { c.removeEventListener('pointerdown', down); c.removeEventListener('pointermove', move); c.removeEventListener('pointerup', up); c.removeEventListener('wheel', wheel) }
  }, [byId])

  const node = sel ? byId.get(sel) : null
  const rels = sel ? (adj.get(sel) ?? []) : []
  const hidden = rels.filter(e => !visible.has(e.source === sel ? e.target : e.source)).length
  const toggleType = (t: string) => setTypes(s => { const n = new Set(s); n.has(t) ? n.delete(t) : n.add(t); return n })

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
      <div>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <div className="relative"><Search size={13} className="absolute left-2.5 top-2.5 text-silver-500" /><input className="input !w-52 !py-1.5 !pl-8" placeholder="Search entities" value={q} onChange={e => setQ(e.target.value)} aria-label="Search entities" /></div>
          {allTypes.map(t => <button key={t} onClick={() => toggleType(t)} className={`chip ${types.has(t) ? 'chip-on' : ''}`}><i className="h-1.5 w-1.5 rounded-full" style={{ background: TYPE_COLOR[t] ?? '#8A93A3' }} />{t}</button>)}
          <button className="chip ml-auto" onClick={() => setColorBy(c => (c === 'type' ? 'cluster' : 'type'))}>colour: {colorBy}</button>
          <button className="chip" onClick={() => setVisible(new Set(kg.nodes.map(n => n.id)))}>show all ({kg.nodes.length})</button>
        </div>
        <canvas ref={ref} style={{ height }} className="w-full cursor-grab rounded-2xl border hairline bg-ink-900" aria-label="Knowledge graph" />
        <div className="mt-1.5 font-mono text-[10px] text-silver-700">{visible.size} of {kg.nodes.length} entities shown · {kg.edges.length} relationships · drag to pan, scroll to zoom, click a node{kg.method ? ` · extraction: ${kg.method}` : ''}</div>
      </div>
      <aside className="rounded-2xl border hairline bg-ink-900/70 p-4 text-[13px]">
        {!node ? <p className="text-silver-500">Select an entity to see its description, relationships and the evidence behind them.</p> : (
          <div className="space-y-3">
            <div><div className="flex items-center gap-2"><i className="h-2.5 w-2.5 rounded-full" style={{ background: TYPE_COLOR[node.type] ?? '#8A93A3' }} /><h3 className="text-base font-semibold">{node.label}</h3></div>
              <div className="label mt-1">{node.type} · {node.degree} connections · cluster {node.cluster + 1}</div></div>
            {node.description && <p className="text-silver-300">{node.description}</p>}
            {hidden > 0 && <button className="btn w-full justify-center" onClick={() => setVisible(v => { const n = new Set(v); rels.forEach(e => { n.add(e.source); n.add(e.target) }); return n })}>Expand · reveal {hidden} neighbour{hidden > 1 ? 's' : ''}</button>}
            <div><div className="label mb-1">Relationships</div><div className="max-h-64 space-y-2 overflow-y-auto">{rels.map((e, i) => { const other = byId.get(e.source === sel ? e.target : e.source)!; return (
              <div key={i}><button className="text-left text-silver-100 hover:text-violet-soft" onClick={() => { setSel(other.id); setVisible(v => new Set(v).add(other.id)) }}>{e.source === sel ? '→' : '←'} {other.label} <span className="text-silver-500">· {e.type}</span></button>
                {e.evidence?.[0] && <div className="mt-0.5 border-l border-line pl-2 text-[11.5px] italic text-silver-500">“{e.evidence[0].quote}” <span className="not-italic text-silver-700">— {e.evidence[0].doc}</span></div>}</div>) })}</div></div>
            {node.sources?.length > 0 && <div><div className="label mb-1">Sources</div>{[...new Set(node.sources.map((s: any) => s.doc))].map(d => <div key={d as string} className="text-silver-500">{d as string}</div>)}</div>}
          </div>)}
      </aside>
    </div>
  )
}
