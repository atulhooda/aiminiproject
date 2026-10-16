import type { Algorithm, CellType, Severity } from '../types/api'

export const CODE_TO_TYPE: Record<string, CellType> = {
  '.': 'ROAD',
  '#': 'BUILDING',
  X: 'OBSTACLE',
  F: 'FIRE',
  '~': 'WATER',
  H: 'HOSPITAL',
  V: 'VICTIM',
  B: 'RESCUE_BASE',
  S: 'SAFE_ZONE',
}

export const SEVERITY_COLOR: Record<Severity, string> = {
  CRITICAL: '#ef4444',
  HIGH: '#f97316',
  MEDIUM: '#eab308',
  LOW: '#22c55e',
}

export const SEVERITY_RANK: Record<Severity, number> = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1 }

// Validated dark-mode categorical slots (dataviz reference palette; checked against
// the #0c121c panel surface). Algorithms take the first three slots in fixed order.
export const CATEGORICAL = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767']

export const ALGO_COLOR: Record<Algorithm, string> = {
  BFS: CATEGORICAL[0],
  GREEDY: CATEGORICAL[1],
  ASTAR: CATEGORICAL[2],
}

export const ALGO_LABEL: Record<Algorithm, string> = {
  BFS: 'BFS',
  GREEDY: 'Greedy Best-First',
  ASTAR: 'A*',
}

// Unit identity colours follow the same validated categorical order (fixed by sorted
// unit id, never cycled by rank). Units are always direct-labelled on the map, so
// identity never relies on colour alone.
export function unitColors(ids: string[]): Record<string, string> {
  const out: Record<string, string> = {}
  ;[...ids].sort().forEach((id, i) => {
    out[id] = CATEGORICAL[i % CATEGORICAL.length]
  })
  return out
}

export const PHASES = [
  'PERCEIVE',
  'UPDATE_STATE',
  'IDENTIFY_GOALS',
  'CHECK_CONSTRAINTS',
  'PLAN',
  'SELECT_ACTION',
  'EXECUTE',
  'OBSERVE',
] as const

export const PHASE_LABEL: Record<string, string> = {
  PERCEIVE: 'Perceive',
  UPDATE_STATE: 'Update state',
  IDENTIFY_GOALS: 'Identify goals',
  CHECK_CONSTRAINTS: 'Check constraints',
  PLAN: 'Plan',
  SELECT_ACTION: 'Select action',
  EXECUTE: 'Execute',
  OBSERVE: 'Observe',
  SYSTEM: 'System',
}

export const PHASE_SHORT: Record<string, string> = {
  PERCEIVE: 'Perceive',
  UPDATE_STATE: 'Update',
  IDENTIFY_GOALS: 'Goals',
  CHECK_CONSTRAINTS: 'Constraints',
  PLAN: 'Plan',
  SELECT_ACTION: 'Select',
  EXECUTE: 'Execute',
  OBSERVE: 'Observe',
}

export const LEVEL_STYLE: Record<string, string> = {
  INFO: 'text-slate-300',
  DECISION: 'text-sky-300',
  ALERT: 'text-red-300',
  SUCCESS: 'text-emerald-300',
  SEARCH: 'text-cyan-300',
  CSP: 'text-violet-300',
  REPLAN: 'text-amber-300',
  EVENT: 'text-orange-300',
}

export const LEVEL_DOT: Record<string, string> = {
  INFO: 'bg-slate-500',
  DECISION: 'bg-sky-400',
  ALERT: 'bg-red-500',
  SUCCESS: 'bg-emerald-400',
  SEARCH: 'bg-cyan-400',
  CSP: 'bg-violet-400',
  REPLAN: 'bg-amber-400',
  EVENT: 'bg-orange-400',
}

export const CAPABILITY_GLYPH: Record<string, string> = {
  URBAN_SAR: 'S',
  FIREFIGHTING: 'F',
  WATER_RESCUE: 'W',
}
