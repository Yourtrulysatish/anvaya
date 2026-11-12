import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { ArrowRight, FileUp, Link2, Database, Target } from 'lucide-react'
import { loadDemo } from '../lib/demo'
import type { Dataset } from '../lib/types'
import { Observatory } from '../observatory/Observatory'

const STEPS = [
  ['Describe', 'Tell ANVAYA the situation in plain language.'], ['Understand', 'Sources become entities, facts and stakeholders.'],
  ['Simulate', 'An artificial society forms and starts talking.'], ['Observe', 'Watch information travel and opinions move.'],
  ['Analyse', 'Metrics, scenarios and uncertainty — not vibes.'], ['Decide', 'Ranked actions with evidence and risks.'],
]

export function HomePage() {
  const [text, setText] = useState('')
  const nav = useNavigate()
  const [ds, setDs] = useState<Dataset | null>(null)
  useEffect(() => { loadDemo().then(setDs).catch(() => {}) }, [])
  const go = () => nav('/new', { state: { situation: text } })
  return (
    <div>
      <section className="relative mx-auto max-w-5xl px-6 pb-10 pt-16 md:pt-24">
        <div className="reveal">
          <div className="label mb-5">Anvaya · अन्वय — everything is connected</div>
          <h1 className="font-serif text-5xl leading-[1.02] tracking-tight md:text-7xl">Understand the world.<br /><span className="italic text-silver-300">Simulate what comes next.</span></h1>
          <p className="mt-6 max-w-xl text-[15px] leading-relaxed text-silver-500">Describe a situation. ANVAYA reads your sources, builds an artificial society, lets hundreds of autonomous agents interact, and shows you how collective behaviour could unfold — with the evidence and the uncertainty attached.</p>
        </div>
        <div className="reveal mt-9 rounded-2xl panel p-3 shadow-[0_0_80px_-30px_#8b5cf6]" style={{ animationDelay: '.15s' }}>
          <label htmlFor="situation" className="sr-only">What situation would you like to explore?</label>
          <textarea id="situation" value={text} onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) go() }} rows={3}
            placeholder="What situation would you like to explore?  e.g. “How will 300 Indian smartphone consumers react if a competitor cuts its flagship price by 20%?”"
            className="w-full resize-none bg-transparent p-3 text-[16px] leading-relaxed text-silver-100 outline-none placeholder:text-silver-700" />
          <div className="flex flex-wrap items-center gap-2 border-t hairline px-1 pt-3">
            {[[FileUp, 'Upload research'], [Database, 'Add datasets'], [Link2, 'Add URLs'], [Target, 'Define objectives']].map(([I, l]: any) => (
              <Link key={l} to="/new" state={{ situation: text }} className="chip hover:border-violet/50 hover:text-white"><I size={13} />{l}</Link>))}
            <button className="btn btn-primary ml-auto" onClick={go}>Begin analysis <ArrowRight size={15} /></button>
          </div>
        </div>
        <ol className="mt-10 grid grid-cols-2 gap-px overflow-hidden rounded-xl border hairline bg-line md:grid-cols-6">
          {STEPS.map(([t, d], i) => (<li key={t} className="bg-ink-900 p-3.5"><div className="font-mono text-[10px] text-violet-soft">0{i + 1}</div><div className="mt-1 text-sm font-medium">{t}</div><div className="mt-1 text-[11.5px] leading-snug text-silver-500">{d}</div></li>))}
        </ol>
      </section>

      <section className="mx-auto max-w-6xl px-6 pb-20">
        <div className="mb-3 flex items-end justify-between">
          <div><div className="label">Live preview · DEMO</div><h2 className="mt-1 text-xl font-medium">A synthetic society, evolving</h2></div>
          <Link to="/universe" className="btn">Open the full universe <ArrowRight size={14} /></Link>
        </div>
        <div className="relative h-[460px] overflow-hidden rounded-2xl border hairline">
          {ds ? <Observatory dataset={ds} compact autoplay /> : <div className="grid h-full place-items-center text-sm text-silver-500">Loading demo…</div>}
          <div className="pointer-events-none absolute bottom-3 right-4 max-w-sm text-right font-mono text-[10px] leading-relaxed text-silver-700">140 synthetic agents · seeded model, template text, no LLM · replayed from recorded events</div>
        </div>
      </section>
    </div>
  )
}
