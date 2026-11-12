import type { AgentInfo, SimEvent } from '../lib/types'
import { COLORS } from './renderer'

export const TYPE_META: Record<string, { label: string; color: string }> = {
  post: { label: 'POST', color: COLORS.post }, reply: { label: 'REPLY', color: COLORS.reply }, agree: { label: 'AGREE', color: COLORS.agree },
  disagree: { label: 'DISAGREE', color: COLORS.disagree }, share: { label: 'SHARE', color: COLORS.share }, cascade: { label: 'CASCADE', color: COLORS.cascade },
  opinion_change: { label: 'OPINION', color: '#FFB86B' }, relationship_change: { label: 'TIE', color: COLORS.agree }, join_group: { label: 'GROUP', color: COLORS.accent },
  leave_group: { label: 'GROUP', color: COLORS.accent }, external_event: { label: 'EXTERNAL', color: COLORS.cascade }, error: { label: 'NOTICE', color: '#FFB86B' },
}

export const feedTypes = ['post', 'reply', 'agree', 'disagree', 'share', 'cascade', 'opinion_change', 'relationship_change', 'join_group', 'leave_group', 'external_event', 'error', 'sim_pause', 'sim_resume']

export function who(agents: AgentInfo[], id: number | null | undefined) { return id == null ? '—' : (agents[id]?.name ?? `Agent ${id}`) }

export function headline(ev: SimEvent, agents: AgentInfo[]): string {
  const s = who(agents, ev.source_agent), t = who(agents, ev.target_agent)
  switch (ev.type) {
    case 'post': return `${s} publishes an opinion`
    case 'reply': return `${s} replies to ${t}`
    case 'agree': return `${s} agrees with ${t}`
    case 'disagree': return `${s} disagrees with ${t}`
    case 'share': return `${s} shares ${t}'s post`
    case 'cascade': case 'opinion_change': case 'relationship_change': case 'join_group': case 'leave_group': case 'external_event': return ev.content
    case 'sim_pause': case 'sim_resume': case 'error': return ev.content
    default: return ev.type
  }
}

export const fmtTime = (s: number) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`
