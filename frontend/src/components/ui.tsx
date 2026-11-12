import { useEffect, useState, type ReactNode } from 'react'
import { api, apiBase, ApiError, setApiBase, useAuth } from '../lib/api'
import { Loader2 } from 'lucide-react'

export function Page({ title, kicker, children, actions, wide }: { title: string; kicker?: string; children: ReactNode; actions?: ReactNode; wide?: boolean }) {
  return (
    <div className={`mx-auto px-6 py-8 md:py-10 ${wide ? 'max-w-7xl' : 'max-w-5xl'}`}>
      <div className="mb-7 flex flex-wrap items-end justify-between gap-3">
        <div>{kicker && <div className="label mb-1.5">{kicker}</div>}<h1 className="font-serif text-4xl tracking-tight">{title}</h1></div>
        {actions}
      </div>
      {children}
    </div>
  )
}
export const Card = ({ children, className = '' }: { children: ReactNode; className?: string }) => <div className={`rounded-2xl border hairline bg-ink-900/70 p-5 ${className}`}>{children}</div>
export const Spinner = ({ label }: { label?: string }) => <span className="inline-flex items-center gap-2 text-sm text-silver-500"><Loader2 size={15} className="animate-spin" />{label}</span>
export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null
  const m = error instanceof Error ? error.message : String(error)
  return <div role="alert" className="rounded-lg border border-rose/30 bg-rose/10 px-3 py-2 text-[13px] text-rose">{m}</div>
}
export const KindTag = ({ kind }: { kind: string }) => {
  const c: Record<string, string> = { FACT: 'text-emerald-300 border-emerald-400/30', ANALYSIS: 'text-sky-300 border-sky-400/30', ESTIMATE: 'text-amber-300 border-amber-400/30', SIMULATION: 'text-violet-soft border-violet/40', RECOMMENDATION: 'text-rose border-rose/40' }
  return <span className={`mr-2 inline-block rounded border px-1.5 py-px font-mono text-[9.5px] tracking-wider ${c[kind] ?? ''}`}>{kind}</span>
}

/** Gate for pages that need the backend: shows connect / sign-in states, otherwise renders children. */
export function BackendGate({ children }: { children: ReactNode }) {
  const token = useAuth(s => s.token)
  const [state, setState] = useState<'checking' | 'none' | 'down' | 'ok'>('checking')
  const [info, setInfo] = useState<any>(null)
  const [url, setUrl] = useState(apiBase())
  const check = () => {
    setState('checking')
    if (!apiBase()) { setState('none'); return }
    api('/health').then(h => { setInfo(h); setState('ok') }).catch(() => setState('down'))
  }
  useEffect(check, [])
  if (state === 'checking') return <div className="p-10"><Spinner label="Connecting to the ANVAYA backend…" /></div>
  if (state !== 'ok') return (
    <Page title="Backend not connected" kicker="Live mode">
      <Card className="max-w-xl space-y-4">
        <p className="text-sm leading-relaxed text-silver-300">{state === 'none' ? 'This site is the static front-end. Live analysis needs the ANVAYA backend (Python) — it runs separately because GitHub Pages cannot execute it.' : `The backend at ${apiBase()} did not respond.`} The <b>DEMO universe</b> works without it.</p>
        <label className="label block">Backend URL</label>
        <input className="input" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://your-backend.example.com" />
        <div className="flex gap-2"><button className="btn btn-primary" onClick={() => { setApiBase(url); check() }}>Connect</button><a className="btn" href="#/universe">Open the DEMO</a></div>
        <p className="text-xs text-silver-500">Run locally: <code className="font-mono">uvicorn anvaya.main:app --port 8000</code> — see the README for deployment.</p>
      </Card>
    </Page>
  )
  if (!token) return <AuthForm registrationOpen={info?.registration_open} llm={info?.llm_configured} />
  return <>{children}</>
}

function AuthForm({ registrationOpen, llm }: { registrationOpen: boolean; llm: boolean }) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState(''); const [pw, setPw] = useState(''); const [err, setErr] = useState<unknown>(null); const [busy, setBusy] = useState(false)
  const set = useAuth(s => s.set)
  const submit = async () => {
    setBusy(true); setErr(null)
    try { const r = await api(`/auth/${mode}`, { body: { email, password: pw } }); set(r.token, r.user.email) }
    catch (e) { setErr(e) } finally { setBusy(false) }
  }
  return (
    <Page title={mode === 'login' ? 'Sign in' : 'Create account'} kicker="Live mode">
      <Card className="max-w-md space-y-3">
        <p className="text-xs text-silver-500">{llm ? 'Language-model features are enabled on this backend.' : 'This backend has no language-model key: live runs use the labelled offline engine.'}</p>
        <input className="input" type="email" autoComplete="email" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} />
        <input className="input" type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} placeholder={mode === 'register' ? 'Password (10+ characters)' : 'Password'} value={pw} onChange={e => setPw(e.target.value)} onKeyDown={e => e.key === 'Enter' && submit()} />
        <ErrorNote error={err} />
        <div className="flex items-center gap-3"><button className="btn btn-primary" disabled={busy} onClick={submit}>{mode === 'login' ? 'Sign in' : 'Create account'}</button>
          {registrationOpen && <button className="text-xs text-silver-500 underline" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>{mode === 'login' ? 'Need an account?' : 'Have an account?'}</button>}</div>
      </Card>
    </Page>
  )
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null); const [error, setError] = useState<unknown>(null); const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let live = true; setLoading(true)
    fn().then(d => { if (live) { setData(d); setError(null) } }).catch(e => { if (live) setError(e instanceof ApiError ? e : e) }).finally(() => live && setLoading(false))
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])
  return { data, error, loading, reload: () => setTick(t => t + 1), setData }
}
