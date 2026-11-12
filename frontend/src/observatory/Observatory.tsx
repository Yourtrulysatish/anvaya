import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Pause, Play, RotateCcw, Square, Maximize2 } from 'lucide-react'
import type { Dataset, SimEvent } from '../lib/types'
import { Playback } from '../lib/simState'
import { UniverseRenderer, COLORS, opinionColor, type Mode } from './renderer'
import { feedTypes, fmtTime, headline, TYPE_META, who } from './format'
import { Inspector } from './Inspector'

export interface LiveControls {
  status: string // created | running | paused | stopped | completed | failed
  round?: number
  onPause?: () => void
  onResume?: () => void
  onStop?: () => void
  interview?: (agentId: number, question: string) => Promise<{ answer: string; model?: string }>
}

interface Props {
  dataset: Dataset
  playback?: Playback
  compact?: boolean
  autoplay?: boolean
  live?: LiveControls
  initialMode?: Mode
}

const SPEEDS = [0.5, 1, 2, 4]
const MODES: { id: Mode; label: string; hint: string }[] = [
  { id: 'social', label: 'Social', hint: 'Conversations, communities and relationships' },
  { id: 'influence', label: 'Influence', hint: 'Who moves whom — nodes sized by opinion change caused' },
  { id: 'network', label: 'Network', hint: 'The whole interconnected ecosystem, coloured by community' },
]

export function Observatory({ dataset, playback, compact, autoplay, live, initialMode }: Props) {
  const topic = dataset.events.find(e => e.type === 'sim_start')?.result.topics?.[0]?.id ?? Object.keys(dataset.agents[0]?.opinions ?? { t1: 0 })[0]
  const pb = useMemo(() => {
    if (playback) return playback
    const p = new Playback(dataset.agents, topic)
    p.setEvents(dataset.events)
    return p
  }, [dataset, playback, topic])

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rendRef = useRef<UniverseRenderer | null>(null)
  const elapsed = useRef(0)
  const [ui, setUi] = useState({ cursor: 0, total: 0, playing: false, speed: 1, version: 0 })
  const [mode, setMode] = useState<Mode>(initialMode ?? 'social')
  const [selected, setSelected] = useState<number | null>(null)
  const [selEvent, setSelEvent] = useState<SimEvent | null>(null)
  const [filter, setFilter] = useState<Set<string>>(new Set(feedTypes))
  const [feedOpen, setFeedOpen] = useState(!compact && typeof window !== 'undefined' && window.innerWidth >= 1024)
  const [hover, setHover] = useState<{ id: number; x: number; y: number } | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current!
    const r = new UniverseRenderer(canvas, dataset.agents)
    r.state = pb.state
    r.onSelect = id => setSelected(id)
    r.onHover = (id, x, y) => setHover(id == null ? null : { id, x, y })
    rendRef.current = r
    pb.onEvent = ev => r.handleEvent(ev)
    let raf = 0, last = performance.now()
    const loop = (t: number) => {
      const dt = Math.min(0.05, (t - last) / 1000); last = t
      pb.tick(dt); if (pb.playing) elapsed.current += dt
      r.state = pb.state; r.speed = pb.speed
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    const iv = setInterval(() => setUi(u => (u.cursor === pb.cursor && u.playing === pb.playing && u.speed === pb.speed && u.total === pb.total && pb.state.round === u.version ? u : { cursor: pb.cursor, total: pb.total, playing: pb.playing, speed: pb.speed, version: pb.state.round })), 110)
    if (autoplay) pb.playing = true
    return () => { cancelAnimationFrame(raf); clearInterval(iv); r.destroy(); pb.onEvent = undefined; pb.playing = false }
  }, [dataset, pb, autoplay])

  useEffect(() => { rendRef.current?.setMode(mode) }, [mode])
  useEffect(() => {
    const r = rendRef.current; if (!r) return
    r.selected = selected
    if (selEvent) {
      const ids = new Set<number>([...selEvent.agents]); if (selEvent.source_agent != null) ids.add(selEvent.source_agent); if (selEvent.target_agent != null) ids.add(selEvent.target_agent)
      r.highlight = ids.size ? ids : null
    } else r.highlight = null
  }, [selected, selEvent])

  const seek = (i: number) => { pb.seek(i); rendRef.current?.clearEffects(); setUi(u => ({ ...u, cursor: pb.cursor })) }
  const toggle = () => {
    if (live && live.status === 'running' && pb.atEnd) { live.onPause?.(); return }
    if (pb.atEnd && !live && pb.total) { pb.restart(true); rendRef.current?.clearEffects(); return }
    pb.playing = !pb.playing
    if (live) { if (!pb.playing) live.onPause?.(); else live.onResume?.() }
  }
  const stop = () => { pb.restart(false); elapsed.current = 0; rendRef.current?.clearEffects(); live?.onStop?.() }
  const restart = () => { pb.restart(true); elapsed.current = 0; rendRef.current?.clearEffects() }
  const setSpeed = (s: number) => { pb.speed = s; setUi(u => ({ ...u, speed: s })) }

  const st = pb.state
  const rounds = dataset.meta.rounds
  const roundEnds = useMemo(() => pb.events.filter(e => e.type === 'round_end'), [pb, ui.total])
  const visibleEnds = roundEnds.filter(e => e.round <= st.round)
  const m = st.metrics
  const shown = useMemo(() => {
    const out: SimEvent[] = []
    for (let i = Math.max(0, ui.cursor - 900); i < ui.cursor; i++) {
      const e = pb.events[i]
      if (!(e.type === 'round_start' || filter.has(e.type))) continue
      const prev = out[out.length - 1]
      if (e.type === 'join_group' && prev && prev.type === 'join_group' && prev.round === e.round) {
        // coalesce bursts of group joins into one line (the individual events remain in the record)
        const ids = [...prev.agents, ...e.agents]
        out[out.length - 1] = { ...prev, agents: ids, source_agent: null, content: `${ids.length} agents joined communities`, reason: 'label propagation re-clustering (see individual join_group events)' }
      } else out.push(e.type === 'join_group' ? { ...e, content: e.content } : e)
    }
    return out.slice(-160)
  }, [pb, ui.cursor, filter])

  const feedRef = useRef<HTMLDivElement>(null)
  useEffect(() => { const el = feedRef.current; if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 140) el.scrollTop = el.scrollHeight }, [shown])

  const paused = !ui.playing
  const statusText = live
    ? live.status === 'running' ? (ui.playing ? 'LIVE · simulation running' : 'PLAYBACK paused · simulation still computing') : live.status === 'paused' ? 'SIMULATION paused on server' : live.status.toUpperCase()
    : ui.cursor >= ui.total && ui.total ? 'REPLAY finished' : ui.playing ? 'REPLAY playing' : ui.cursor <= pb.base ? 'REPLAY ready' : 'REPLAY paused'
  const canBack = ui.cursor > pb.base

  return (
    <div className="relative h-full w-full overflow-hidden bg-ink-950">
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />

      {/* top-left: title + mode switch */}
      <div className="pointer-events-none absolute left-4 top-4 flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <span className={`rounded px-2 py-0.5 font-mono text-[10px] tracking-[0.18em] ${dataset.meta.label === 'DEMO' ? 'bg-gold/15 text-gold' : 'bg-cyan/15 text-cyan'}`}>{dataset.meta.label}</span>
          {!compact && <span className="text-sm text-silver-300">{dataset.meta.title}</span>}
        </div>
        {!compact && (
          <div className="pointer-events-auto flex w-fit gap-1 rounded-xl border border-line bg-ink-900/80 p-1 backdrop-blur">
            {MODES.map(md => (
              <button key={md.id} title={md.hint} onClick={() => setMode(md.id)}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium tracking-wide transition ${mode === md.id ? 'bg-violet/25 text-white' : 'text-silver-500 hover:text-silver-100'}`}>{md.label}</button>
            ))}
          </div>
        )}
      </div>

      {/* HUD */}
      {!compact && (
        <div className="pointer-events-none absolute left-4 top-[7.4rem] hidden w-64 flex-col gap-2 lg:flex">
          <div className="panel rounded-xl p-3">
            <div className="grid grid-cols-2 gap-x-4 gap-y-2.5">
              <Stat k="Round" v={`${st.round}${rounds ? ` / ${rounds}` : ''}`} />
              <Stat k="Active agents" v={String(st.activeThisRound.size)} />
              <Stat k="Interactions" v={st.interactions.toLocaleString()} />
              <Stat k="Playback" v={fmtTime(elapsed.current)} />
            </div>
          </div>
          <div className="panel rounded-xl p-3">
            <div className="label mb-2">Opinion · computed</div>
            {m ? (<>
              <div className="mb-2 flex h-2 overflow-hidden rounded-full bg-ink-700">
                <div style={{ width: `${(m.support / dataset.agents.length) * 100}%`, background: `rgb(${COLORS.support})` }} />
                <div style={{ width: `${(m.neutral / dataset.agents.length) * 100}%`, background: `rgb(${COLORS.neutral})`, opacity: 0.6 }} />
                <div style={{ width: `${(m.oppose / dataset.agents.length) * 100}%`, background: `rgb(${COLORS.oppose})` }} />
              </div>
              <div className="mb-2 flex justify-between font-mono text-[10px] text-silver-500"><span>{m.support} support</span><span>{m.neutral} neutral</span><span>{m.oppose} oppose</span></div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
                <Stat k="Mean" v={m.mean_opinion.toFixed(2)} small /><Stat k="Polarisation" v={m.polarisation.toFixed(2)} small />
                <Stat k="Communities" v={String(m.groups)} small /><Stat k="Largest cascade" v={String(m.max_cascade)} small />
              </div>
              <Spark ends={visibleEnds} />
            </>) : <div className="text-xs text-silver-500">Metrics appear at the end of round 1.</div>}
          </div>
          {m?.market && <MarketPanel mk={m.market} />}
          {dataset.meta.synthetic && (
            <div className="rounded-lg border border-gold/25 bg-gold/5 px-3 py-2 text-[11px] leading-relaxed text-silver-300">
              Synthetic demonstration. Agents, text and the round-9 price cut come from a seeded model: no LLM, no real people, not a forecast.
            </div>
          )}
        </div>
      )}

      {/* legend */}
      {!compact && (
        <div className="pointer-events-none absolute bottom-24 left-4 hidden gap-4 font-mono text-[10px] text-silver-500 md:flex">
          <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: opinionColor(1) }} />support</span>
          <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: opinionColor(0) }} />neutral</span>
          <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: opinionColor(-1) }} />oppose</span>
          <span style={{ color: COLORS.agree }}>● agree</span><span style={{ color: COLORS.disagree }}>● disagree</span><span style={{ color: COLORS.share }}>● share</span><span style={{ color: COLORS.cascade }}>● cascade</span>
        </div>
      )}

      {hover && !compact && selected !== hover.id && (
        <div className="pointer-events-none absolute z-10 rounded-lg border border-line bg-ink-900/95 px-3 py-2 text-xs" style={{ left: hover.x + 14, top: hover.y + 14 }}>
          <div className="font-medium">{who(dataset.agents, hover.id)}</div>
          <div className="text-silver-500">{dataset.agents[hover.id].segment} · opinion {st.opinion[hover.id].toFixed(2)}</div>
        </div>
      )}

      {/* feed */}
      {!compact && (
        <aside className={`absolute bottom-24 right-4 top-4 flex w-[22rem] max-w-[calc(100%-2rem)] flex-col rounded-2xl panel transition-transform duration-300 ${feedOpen ? '' : 'translate-x-[calc(100%+1.5rem)]'}`}>
          <button onClick={() => setFeedOpen(o => !o)} aria-label="Toggle feed" className="absolute -left-9 top-3 grid h-8 w-8 place-items-center rounded-lg border border-line bg-ink-900/90 text-silver-300">{feedOpen ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}</button>
          <div className="flex items-center justify-between border-b hairline px-4 py-3"><span className="label">Activity feed</span><span className="font-mono text-[10px] text-silver-500">{ui.cursor} / {ui.total} events</span></div>
          <div className="flex flex-wrap gap-1 border-b hairline px-3 py-2">
            {['post', 'reply', 'agree', 'disagree', 'share', 'opinion_change', 'join_group', ...(m?.market ? ['funnel_change', 'listing_decision', 'competitor_action'] : [])].map(t => {
              const on = filter.has(t)
              return <button key={t} onClick={() => setFilter(f => { const n = new Set(f); on ? n.delete(t) : n.add(t); if (t === 'join_group') on ? n.delete('leave_group') : n.add('leave_group'); return n })}
                className={`chip ${on ? 'chip-on' : ''}`} style={on ? { borderColor: TYPE_META[t].color + '88' } : {}}><i className="h-1.5 w-1.5 rounded-full" style={{ background: TYPE_META[t].color }} />{TYPE_META[t].label.toLowerCase()}</button>
            })}
          </div>
          <div ref={feedRef} className="flex-1 space-y-px overflow-y-auto px-2 py-2">
            {shown.length === 0 && <div className="p-4 text-xs text-silver-500">Press play. Events appear here as the recorded simulation unfolds.</div>}
            {shown.map(ev => ev.type === 'round_start' ? (
              <div key={ev.id} className="label flex items-center gap-2 px-2 pb-1 pt-3"><span>Round {String(ev.round).padStart(2, '0')}</span><i className="h-px flex-1 bg-line" /></div>
            ) : (
              <button key={ev.id} onClick={() => { setSelEvent(s => (s?.id === ev.id ? null : ev)); const ids = [...ev.agents, ...(ev.source_agent != null ? [ev.source_agent] : []), ...(ev.target_agent != null ? [ev.target_agent] : [])]; if (ev.type !== 'external_event') rendRef.current?.focus(ids.slice(0, 12)) }}
                className={`block w-full rounded-lg px-2 py-1.5 text-left transition hover:bg-ink-800 ${selEvent?.id === ev.id ? 'bg-violet/15 ring-1 ring-violet/40' : ''}`}>
                <div className="flex items-baseline gap-2 text-[12.5px]">
                  <span className="font-mono text-[10px] text-silver-700">[R{String(ev.round).padStart(2, '0')}]</span>
                  <i className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: TYPE_META[ev.type]?.color }} />
                  <span className="text-silver-100">{headline(ev, dataset.agents)}</span>
                </div>
                {['post', 'reply', 'agree', 'disagree', 'share'].includes(ev.type) && ev.content && <p className="ml-[3.2rem] mt-0.5 line-clamp-3 text-[12px] leading-snug text-silver-500">{ev.content}</p>}
                {selEvent?.id === ev.id && (
                  <div className="ml-[3.2rem] mt-1.5 space-y-1 font-mono text-[10.5px] leading-snug text-silver-500">
                    <div><span className="text-silver-300">why</span> {ev.reason}</div>
                    <div><span className="text-silver-300">text</span> {ev.content_source || 'n/a'} · <span className="text-silver-300">decided</span> {ev.result?.decided_by ?? 'engine'} · <span className="text-silver-300">id</span> {ev.id}</div>
                  </div>
                )}
              </button>
            ))}
          </div>
        </aside>
      )}

      {/* inspector */}
      {!compact && selected != null && (
        <Inspector pb={pb} agentId={selected} agents={dataset.agents} topic={topic} tick={ui.cursor} interview={live?.interview} synthetic={!!dataset.meta.synthetic}
          onClose={() => { setSelected(null); rendRef.current && (rendRef.current.selected = null) }}
          onSelectAgent={id => { setSelected(id); rendRef.current?.focus([id]) }} />
      )}

      {/* controls */}
      {!compact && (
        <div className="absolute inset-x-4 bottom-4 rounded-2xl panel px-4 py-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <div className="flex items-center gap-1.5">
              <IconBtn label="Step back" onClick={() => pb.stepBack()} disabled={!canBack}><ChevronLeft size={16} /></IconBtn>
              <button className="btn btn-primary min-w-[6.2rem] justify-center" onClick={toggle} disabled={!ui.total}>
                {ui.playing ? <><Pause size={15} />Pause</> : ui.cursor > pb.base && ui.cursor < ui.total ? <><Play size={15} />Resume</> : <><Play size={15} />Play</>}
              </button>
              <IconBtn label="Step forward" onClick={() => pb.stepForward()} disabled={pb.atEnd}><ChevronRight size={16} /></IconBtn>
              <IconBtn label="Stop (rewind)" onClick={stop}><Square size={14} /></IconBtn>
              <IconBtn label="Restart" onClick={restart}><RotateCcw size={14} /></IconBtn>
              <IconBtn label="Fit view" onClick={() => rendRef.current?.fit()}><Maximize2 size={14} /></IconBtn>
            </div>
            <div className="flex items-center gap-1" role="group" aria-label="Speed">
              {SPEEDS.map(s => <button key={s} onClick={() => setSpeed(s)} className={`rounded-md px-2 py-1 font-mono text-[11px] ${ui.speed === s ? 'bg-violet/25 text-white' : 'text-silver-500 hover:text-silver-100'}`}>{s}×</button>)}
            </div>
            <div className="ml-auto flex items-center gap-2 font-mono text-[11px] text-silver-500">
              <span className={`h-1.5 w-1.5 rounded-full ${ui.playing ? 'animate-pulse bg-cyan' : 'bg-silver-700'}`} />{statusText}
              {live && live.status === 'running' && <button className="btn btn-ghost !px-2 !py-1 text-[11px]" onClick={() => live.onStop?.()}>Stop run</button>}
            </div>
          </div>
          <div className="relative mt-2.5">
            <input type="range" min={0} max={Math.max(1, ui.total)} value={ui.cursor} onChange={e => seek(+e.target.value)} className="w-full" aria-label="Timeline" />
            <div className="pointer-events-none relative h-2">
              {pb.events.filter(e => e.type === 'round_start' && (e.round % 4 === 1 || e.round === 1)).map(e => (
                <span key={e.id} className="absolute top-0 font-mono text-[9px] text-silver-700" style={{ left: `${(pb.events.indexOf(e) / Math.max(1, ui.total)) * 100}%` }}>R{e.round}</span>
              ))}
            </div>
          </div>
          {paused && ui.cursor > pb.base && !live && <div className="sr-only">Playback paused</div>}
        </div>
      )}
    </div>
  )
}

const FUNNEL_COLORS: Record<string, string> = { unaware: '#3a4152', aware: '#8A93A3', considering: '#A78BFA', trial: '#3DDCFF', repeat: '#6EE7B7', advocate: '#F5C26B', rejecter: '#FF5C7A' }
function MarketPanel({ mk }: { mk: any }) {
  const total = Object.values(mk.funnel).reduce((a: number, b: any) => a + b, 0) as number || 1
  const shares = Object.entries(mk.share_cumulative as Record<string, number>).sort((a, b) => b[1] - a[1]).slice(0, 5)
  return (
    <div className="panel rounded-xl p-3">
      <div className="label mb-2">Market funnel · computed</div>
      <div className="mb-2 flex h-2 overflow-hidden rounded-full bg-ink-700">{Object.entries(mk.funnel).map(([k, v]: any) => <div key={k} title={`${k}: ${v}`} style={{ width: `${(v / total) * 100}%`, background: FUNNEL_COLORS[k] }} />)}</div>
      <div className="mb-2 flex flex-wrap gap-x-2 font-mono text-[9.5px] text-silver-500">{Object.entries(mk.funnel).filter(([, v]: any) => v > 0).map(([k, v]: any) => <span key={k}><i className="mr-1 inline-block h-1.5 w-1.5 rounded-full" style={{ background: FUNNEL_COLORS[k] }} />{k} {v}</span>)}</div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
        <Stat k="Awareness" v={`${(mk.awareness * 100).toFixed(0)}%`} small /><Stat k="Ever tried" v={`${(mk.ever_tried * 100).toFixed(0)}%`} small />
        <Stat k="Repeat+advocate" v={`${(mk.repeat_or_advocate * 100).toFixed(0)}%`} small /><Stat k="Listed at" v={`${mk.listed_count} retailers`} small />
      </div>
      <div className="label mb-1 mt-2.5">Share of purchases (cumulative)</div>
      {shares.map(([b, v]) => <div key={b} className="flex items-center gap-2 text-[11px]"><span className="w-20 truncate text-silver-300">{b}</span><div className="h-1 flex-1 rounded bg-ink-700"><div className="h-1 rounded bg-violet" style={{ width: `${v * 100}%` }} /></div><span className="w-9 text-right font-mono text-silver-500">{(v * 100).toFixed(0)}%</span></div>)}
      {mk.promotions_active?.length > 0 && <div className="mt-1.5 font-mono text-[10px] text-coral">promo: {mk.promotions_active.join(', ')}</div>}
    </div>
  )
}
function Stat({ k, v, small }: { k: string; v: string; small?: boolean }) {
  return <div><div className="label !text-[9.5px]">{k}</div><div className={`font-mono ${small ? 'text-[13px]' : 'text-lg'} text-silver-100`}>{v}</div></div>
}
function IconBtn({ children, label, onClick, disabled }: { children: React.ReactNode; label: string; onClick: () => void; disabled?: boolean }) {
  return <button className="btn !p-2" title={label} aria-label={label} onClick={onClick} disabled={disabled}>{children}</button>
}
function Spark({ ends }: { ends: SimEvent[] }) {
  if (ends.length < 2) return null
  const pts = ends.map(e => e.result.mean_opinion as number), pol = ends.map(e => e.result.polarisation as number)
  const W = 216, H = 34
  const path = (vs: number[], lo: number, hi: number) => vs.map((v, i) => `${i ? 'L' : 'M'}${(i / (vs.length - 1)) * W},${H - ((v - lo) / (hi - lo || 1)) * H}`).join('')
  return (
    <svg width={W} height={H} className="mt-3 overflow-visible" aria-label="Mean opinion and polarisation by round">
      <line x1="0" x2={W} y1={H / 2} y2={H / 2} stroke="#262b37" strokeDasharray="2 3" />
      <path d={path(pts, -1, 1)} fill="none" stroke="#3DDCFF" strokeWidth="1.5" />
      <path d={path(pol, 0, 1)} fill="none" stroke="#A78BFA" strokeWidth="1.5" />
    </svg>
  )
}
