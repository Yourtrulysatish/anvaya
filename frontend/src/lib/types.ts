export type EventType =
  | 'sim_start' | 'round_start' | 'external_event' | 'post' | 'reply' | 'agree' | 'disagree' | 'share' | 'cascade'
  | 'opinion_change' | 'relationship_change' | 'join_group' | 'leave_group' | 'funnel_change' | 'listing_decision' | 'competitor_action' | 'round_end' | 'sim_pause' | 'sim_resume'
  | 'sim_end' | 'error'

export interface StateChanges {
  opinion?: Record<string, { topic: string; from: number; to: number }>
  relationships?: { a: number; b: number; from: number; to: number }[]
  sentiment?: Record<string, number>
  group?: Record<string, number | null>
}

export interface SimEvent {
  id: string
  seq: number
  simulation_id: string
  round: number
  type: EventType
  source_agent: number | null
  target_agent: number | null
  agents: number[]
  topic: string | null
  content: string
  content_source: string
  reason: string
  result: Record<string, any>
  state_changes: StateChanges
  timestamp: string
  provenance?: Record<string, any>
  cause_event?: string
}

export interface AgentInfo {
  id: number
  name: string
  segment: string
  persona: string
  age: number
  occupation: string
  location: string
  traits: Record<string, number>
  sensitivities: Record<string, number>
  activity: number
  influence: number
  goals: string[]
  beliefs: string[]
  attributes_basis: string
  opinions: Record<string, number>
}

export interface DatasetMeta {
  label: string // DEMO | LIVE | REPLAY
  synthetic?: boolean
  title: string
  agents: number
  rounds: number
  generator?: string
  assumptions?: string[]
  simulationId?: string
  note?: string      // disclaimer shown in the HUD
  barText?: string   // status-bar caption
}

export interface Dataset {
  meta: DatasetMeta
  agents: AgentInfo[]
  events: SimEvent[]
}

export const INTERACTION_TYPES: EventType[] = ['post', 'reply', 'agree', 'disagree', 'share']
