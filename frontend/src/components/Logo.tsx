export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden>
      <g stroke="#C9CED6" strokeWidth="3" fill="none" strokeLinecap="round">
        <path d="M50 20 L24 78 M50 20 L76 78" />
        <path d="M33 62 Q50 50 67 62" stroke="#8B5CF6" />
      </g>
      <circle cx="50" cy="20" r="7" fill="#8B5CF6" />
      <circle cx="24" cy="78" r="5.5" fill="#E8EAEE" />
      <circle cx="76" cy="78" r="5.5" fill="#E8EAEE" />
      <circle cx="50" cy="55" r="3.5" fill="#3DDCFF" />
    </svg>
  )
}

export function Wordmark({ size = 15 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <LogoMark size={size + 12} />
      <span className="leading-none">
        <span className="block font-semibold tracking-[0.34em] text-silver-100" style={{ fontSize: size }}>ANVAYA</span>
        <span className="block font-serif text-silver-500" style={{ fontSize: size - 3, marginTop: 3 }}>अन्वय</span>
      </span>
    </span>
  )
}
