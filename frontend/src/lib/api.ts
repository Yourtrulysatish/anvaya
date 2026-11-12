import { create } from 'zustand'
import type { SimEvent } from './types'

const LS = { api: 'anvaya_api', token: 'anvaya_token', user: 'anvaya_user' }
const ls = {
  get: (k: string) => { try { return localStorage.getItem(k) } catch { return null } },
  set: (k: string, v: string) => { try { localStorage.setItem(k, v) } catch { /* private mode */ } },
  del: (k: string) => { try { localStorage.removeItem(k) } catch { /* ignore */ } },
}

export function apiBase(): string {
  const configured = ls.get(LS.api) || (import.meta.env.VITE_API_URL as string | undefined) || ''
  if (configured) return configured.replace(/\/+$/, '')
  if (typeof location !== 'undefined' && ['localhost', '127.0.0.1'].includes(location.hostname)) return 'http://127.0.0.1:8000'
  return ''
}
export const setApiBase = (u: string) => (u ? ls.set(LS.api, u.replace(/\/+$/, '')) : ls.del(LS.api))

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail?: unknown) { super(message); this.status = status; this.detail = detail }
}

interface AuthState { token: string | null; email: string | null; isAdmin: boolean; set: (t: string | null, e?: string | null) => void; setAdmin: (v: boolean) => void }
export const useAuth = create<AuthState>(set => ({
  token: ls.get(LS.token), email: ls.get(LS.user), isAdmin: false,
  set: (t, e = null) => { t ? (ls.set(LS.token, t), e && ls.set(LS.user, e)) : (ls.del(LS.token), ls.del(LS.user)); set({ token: t, email: t ? e : null, isAdmin: false }) },
  setAdmin: v => set({ isAdmin: v }),
}))

function msgOf(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') { const d = detail as any; return d.message ?? d.detail?.message ?? JSON.stringify(d).slice(0, 300) }
  return fallback
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; form?: FormData; signal?: AbortSignal } = {}): Promise<T> {
  const base = apiBase()
  if (!base) throw new ApiError(0, 'No backend configured')
  const headers: Record<string, string> = {}
  const tok = useAuth.getState().token
  if (tok) headers.Authorization = `Bearer ${tok}`
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.body) }
  let res: Response
  try { res = await fetch(base + '/api' + path, { method: opts.method ?? (body ? 'POST' : 'GET'), headers, body, signal: opts.signal }) }
  catch { throw new ApiError(0, `Cannot reach the backend at ${base}`) }
  if (res.status === 401 && tok) useAuth.getState().set(null)
  const text = await res.text()
  let data: any = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) throw new ApiError(res.status, msgOf(data?.detail ?? data, `HTTP ${res.status}`), data?.detail)
  return data as T
}

export async function download(path: string, filename: string) {
  const tok = useAuth.getState().token
  const res = await fetch(apiBase() + '/api' + path, { headers: tok ? { Authorization: `Bearer ${tok}` } : {} })
  if (!res.ok) throw new ApiError(res.status, `Download failed (HTTP ${res.status})`)
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url)
}

export async function waitJob(id: string, onProgress?: (j: any) => void): Promise<any> {
  for (;;) {
    const j = await api(`/jobs/${id}`)
    onProgress?.(j)
    if (j.status !== 'running') { if (j.status === 'failed') throw new ApiError(500, msgOf(j.error, j.message)); return j }
    await new Promise(r => setTimeout(r, 1500))
  }
}

/** Fetch-based SSE (EventSource cannot send Authorization). Reconnects with the last seen seq; the Playback dedupes by id. */
export async function streamSimulation(sid: string, handlers: { onEvents: (e: SimEvent[]) => void; onStatus: (s: any) => void; onEnd: (s: any) => void }, signal: AbortSignal) {
  let last = -1, retry = 0
  while (!signal.aborted) {
    try {
      const tok = useAuth.getState().token
      const res = await fetch(`${apiBase()}/api/simulations/${sid}/stream?after=${last}`, { headers: { Authorization: `Bearer ${tok}`, 'Last-Event-ID': String(last) }, signal })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
      retry = 0
      const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        let i: number
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const frame = buf.slice(0, i); buf = buf.slice(i + 2)
          let name = 'message', data = ''
          for (const line of frame.split('\n')) { if (line.startsWith('event: ')) name = line.slice(7); else if (line.startsWith('data: ')) data += line.slice(6) }
          if (!data) continue
          const parsed = JSON.parse(data)
          if (name === 'events') { handlers.onEvents(parsed); last = Math.max(last, parsed[parsed.length - 1].seq) }
          else if (name === 'status') handlers.onStatus(parsed)
          else if (name === 'end') { handlers.onEnd(parsed); return }
        }
      }
    } catch (e) {
      if (signal.aborted) return
      retry++
      if (retry > 8) { handlers.onEnd({ status: 'disconnected' }); return }
      await new Promise(r => setTimeout(r, Math.min(8000, 800 * retry)))
    }
  }
}
