export function LineChart({ series, height = 150, xLabels, yMin = -1, yMax = 1, zeroLine = true, marks }: {
  series: { label: string; color: string; values: number[] }[]; height?: number; xLabels?: (string | number)[]; yMin?: number; yMax?: number; zeroLine?: boolean; marks?: { x: number; label: string }[]
}) {
  const W = 560, H = height, P = { l: 30, r: 8, t: 8, b: 18 }
  const n = Math.max(...series.map(s => s.values.length), 2)
  const X = (i: number) => P.l + (i / (n - 1)) * (W - P.l - P.r)
  const Y = (v: number) => P.t + (1 - (v - yMin) / (yMax - yMin || 1)) * (H - P.t - P.b)
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={series.map(s => s.label).join(', ')}>
        {[yMin, (yMin + yMax) / 2, yMax].map(v => <g key={v}><line x1={P.l} x2={W - P.r} y1={Y(v)} y2={Y(v)} stroke="#262b37" strokeDasharray={v === 0 && zeroLine ? '' : '2 4'} /><text x={P.l - 5} y={Y(v) + 3} textAnchor="end" fontSize="9" fill="#565e6e" fontFamily="JetBrains Mono">{v.toFixed(1)}</text></g>)}
        {marks?.map(m => <g key={m.label}><line x1={X(m.x)} x2={X(m.x)} y1={P.t} y2={H - P.b} stroke="#f5c26b" strokeDasharray="3 3" opacity=".6" /><text x={X(m.x) + 3} y={P.t + 9} fontSize="9" fill="#f5c26b" fontFamily="JetBrains Mono">{m.label}</text></g>)}
        {series.map(s => <path key={s.label} d={s.values.map((v, i) => `${i ? 'L' : 'M'}${X(i)},${Y(v)}`).join('')} fill="none" stroke={s.color} strokeWidth="1.8" strokeLinejoin="round" />)}
        {xLabels && xLabels.map((l, i) => (i % Math.ceil(n / 8) === 0 ? <text key={i} x={X(i)} y={H - 4} textAnchor="middle" fontSize="9" fill="#565e6e" fontFamily="JetBrains Mono">{l}</text> : null))}
      </svg>
      <div className="mt-1 flex gap-4 font-mono text-[10px] text-silver-500">{series.map(s => <span key={s.label}><i className="mr-1.5 inline-block h-1.5 w-3 rounded-sm align-middle" style={{ background: s.color }} />{s.label}</span>)}</div>
    </div>
  )
}

export function IntervalBar({ mean, lo, hi, min = -1, max = 1, color = '#8B5CF6' }: { mean: number; lo: number; hi: number; min?: number; max?: number; color?: string }) {
  const p = (v: number) => `${((Math.min(max, Math.max(min, v)) - min) / (max - min)) * 100}%`
  return (
    <div className="relative h-3 w-full rounded bg-ink-700">
      <div className="absolute top-1/2 h-px w-full bg-line" /><div className="absolute left-1/2 top-0 h-3 w-px bg-silver-700" />
      <div className="absolute top-1 h-1 rounded" style={{ left: p(lo), width: `calc(${p(hi)} - ${p(lo)})`, background: color, opacity: 0.5 }} />
      <div className="absolute top-0 h-3 w-1 rounded" style={{ left: `calc(${p(mean)} - 2px)`, background: color }} />
    </div>
  )
}
