// Types mirroring the JSON produced by backend/app/services/serializers.py.

export type Pos = [number, number]

export type CellCode = '.' | '#' | 'X' | 'F' | '~' | 'H' | 'V' | 'B' | 'S'
export type CellType =
  | 'ROAD'
  | 'BUILDING'
  | 'OBSTACLE'
  | 'FIRE'
  | 'WATER'
  | 'HOSPITAL'
  | 'VICTIM'
  | 'RESCUE_BASE'
  | 'SAFE_ZONE'

export type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
export type VictimStatus = 'UNREPORTED' | 'WAITING' | 'ASSIGNED' | 'BEING_RESCUED' | 'IN_TRANSIT' | 'RESCUED' | 'DECEASED'
export type UnitStatus = 'IDLE' | 'EN_ROUTE' | 'ON_SCENE' | 'TRANSPORTING' | 'WAITING' | 'OUT_OF_SERVICE'
export type Algorithm = 'BFS' | 'GREEDY' | 'ASTAR'
export type SimStatus = 'READY' | 'RUNNING' | 'COMPLETE' | 'STALLED'

export interface PriorityFactor {
  factor: string
  points: number
  detail: string
}

export interface Victim {
  id: string
  pos: Pos
  severity: Severity
  health: number
  health_status: string
  status: VictimStatus
  priority: number
  priority_breakdown: PriorityFactor[]
  trapped: boolean
  extracted: boolean
  needs_icu: boolean
  rescue_time: number
  rescue_progress: number
  required_resources: string[]
  carrier_id: string | null
  destination_id: string | null
  assigned_units: string[]
  reported: boolean
  reported_tick: number
  rescued_tick: number | null
  deceased_tick: number | null
}

export interface Unit {
  id: string
  kind: 'AMBULANCE' | 'TEAM'
  pos: Pos
  capacity: number
  medical: 'ALS' | 'BLS' | null
  capability: string
  available: boolean
  status: UnitStatus
  carrying: string[]
  distance: number
}

export interface Hospital {
  id: string
  name: string
  pos: Pos
  er_capacity: number
  er_occupancy: number
  er_free: number
  icu_capacity: number
  icu_occupancy: number
  icu_free: number
  inbound_er: number
  inbound_icu: number
}

export interface SafeZone {
  id: string
  name: string
  pos: Pos
  occupancy: number
  capacity: number
}

export interface PlanLeg {
  task_id: string
  kind: 'NAVIGATE' | 'TRANSPORT'
  active: boolean
  path: Pos[]
  cost: number
  replans: number
  label: string
}

export interface UnitPlan {
  unit_id: string
  current_task: string | null
  current_kind: string | null
  mission: string | null
  legs: PlanLeg[]
  waiting_for: string[]
  holding: boolean
}

export type TaskStatus = 'PENDING' | 'ACTIVE' | 'DONE' | 'CANCELLED'

export interface PlanTaskNode {
  id: string
  kind: string
  label: string
  status: TaskStatus
  unit_id: string | null
  victim_ids: string[]
  target: Pos | null
  replans: number
  note: string
  shared: boolean
  children: PlanTaskNode[]
  path_cost?: number
  steps?: number
  algorithm?: string | null
  duration?: number
  progress?: number
}

export interface LogEntry {
  seq: number
  tick: number
  time: string
  phase: string
  level: 'INFO' | 'DECISION' | 'ALERT' | 'SUCCESS' | 'SEARCH' | 'CSP' | 'REPLAN' | 'EVENT'
  message: string
  details: string[]
}

export interface PhaseTrace {
  phase: string
  summary: string
}

export interface Alert {
  code: 'ENV_CHANGE' | 'PLAN_INVALID' | 'RESUMED' | string
  title: string
  message: string
  tick: number
}

export interface ReplanEvent {
  unit_id: string
  task_id: string
  reason: string
  blocked_cell: Pos | null
  old_path: Pos[]
  new_path: Pos[]
}

export interface SearchSummary {
  algorithm: Algorithm
  start: Pos
  goal: Pos
  found: boolean
  path: Pos[]
  cost: number
  steps: number
  nodes_expanded: number
  nodes_generated: number
  max_frontier: number
  time_ms: number
  heuristic: string | null
  heuristic_start: number | null
  purpose?: string
  tick?: number
}

export interface SearchTrace extends SearchSummary {
  explored: Pos[]
  frontier: Pos[]
  unit_id?: string | null
  profile?: string
}

export interface CspVariable {
  var: string
  severity: Severity
  priority: number
  domain_initial: number | null
  domain_after_node: number | null
  domain_after_ac3: number | null
  assigned: string | null
  method: string | null
  utility: number | null
  prunings: Record<string, number>
  coverage_required: boolean
}

export interface CspStats {
  nodes: number
  backtracks: number
  consistency_checks: number
  fc_prunings: number
  bound_prunings: number
  ac3_revisions: number
  ac3_removals: number
  node_consistency_removals: number
  solutions_found: number
  time_ms: number
  truncated: boolean
}

export interface CspReport {
  run: number
  tick: number
  kind: 'RESOURCE_ALLOCATION' | 'DESTINATION_REALLOCATION'
  result: 'SATISFIED' | 'UNSATISFIABLE'
  optimal: boolean
  score: number | null
  failure_reason: string | null
  relaxed: boolean
  phase1: { result: string; reason: string | null; stats: CspStats } | null
  variables: CspVariable[]
  constraints: {
    total: number
    unary: string[]
    binary: number
    global: { name: string; description: string; capacity: number; scope: number }[]
  }
  removal_counts: Record<'NODE' | 'AC3' | 'FC', Record<string, number>>
  stats: CspStats
  removals_sample: { var: string; value: string; constraint: string; stage: string }[]
}

export interface Stats {
  tick: number
  active_victims: number
  rescued_victims: number
  deceased_victims: number
  critical_victims: number
  unreported_victims: number
  total_victims: number
  active_ambulances: number
  available_ambulances: number
  total_ambulances: number
  active_teams: number
  available_teams: number
  total_teams: number
  hospital_capacity: { er_free: number; er_total: number; icu_free: number; icu_total: number }
  current_mission: string | null
  ai_state: string
  replanning_count: number
  total_distance: number
  total_rescue_time: number
  avg_rescue_time: number | null
  missions_active: number
  agent: {
    replans: number
    route_replans: number
    reassignments: number
    destination_changes: number
    searches: number
    nodes_expanded: number
    search_time_ms: number
    csp_runs: number
    csp_nodes: number
    csp_time_ms: number
    missions_created: number
    missions_completed: number
    missions_aborted: number
    hazards_discovered: number
    victims_discovered: number
    actions_executed: number
    failed_actions: number
  }
}

export interface WorldStateView {
  tick: number
  resource_positions: Record<string, Pos>
  available_resources: string[]
  remaining_victims: Record<string, string>
  blocked_roads: Pos[]
  hazard_cells: number
  hospital_capacity: Record<string, { er_free: number; icu_free: number }>
  rescue_tasks: Record<string, string>
  is_goal: boolean
}

export interface EnvReport {
  tick: number
  event_type: string
  source: string
  title: string
  description: string
  cells: Pos[]
  victim_ids: string[]
  unit_ids: string[]
  hospital_ids: string[]
}

export interface ScenarioInfo {
  id: string
  name: string
  description: string
  challenges: string[]
  recommended_algorithm: string
  seed: number
  demo: boolean
}

export interface Snapshot {
  session_id: string
  scenario: ScenarioInfo
  tick: number
  status: SimStatus
  end_reason: string | null
  algorithm: Algorithm
  grid: { rows: number; cols: number; cells: string[]; danger: number[][]; version: number }
  belief_version: number
  belief_diff: { pos: Pos; belief: CellType; truth: CellType }[]
  victims: Victim[]
  ambulances: Unit[]
  teams: Unit[]
  hospitals: Hospital[]
  safe_zones: SafeZone[]
  bases: Pos[]
  plans: UnitPlan[]
  mission_tree: PlanTaskNode
  log: LogEntry[]
  log_seq: number
  phase_trace: PhaseTrace[]
  alerts: Alert[]
  replan_events: ReplanEvent[]
  last_search: SearchTrace | null
  search_history: SearchSummary[]
  last_csp: CspReport | null
  stats: Stats
  state: WorldStateView
  events: EnvReport[]
  last_actions: { type: string; unit_id: string; success: boolean; message: string }[]
  upcoming_events: { tick: number; type: string; label: string | null }[]
  report?: EnvReport
}

export interface Meta {
  algorithms: { id: Algorithm; label: string }[]
  heuristics: string[]
  profiles: { id: string; label: string }[]
  event_types: string[]
  scenarios: ScenarioInfo[]
}

export interface CustomConfig {
  rows: number
  cols: number
  seed: number
  victims: number
  critical_ratio: number
  ambulances: number
  teams: number
  hospitals: number
  obstacle_density: number
  fire_seeds: number
  fire_spread: boolean
  hidden_hazards: number
  flood: boolean
}

export type EventType =
  | 'BLOCK_ROAD'
  | 'CLEAR_ROAD'
  | 'START_FIRE'
  | 'ADD_VICTIM'
  | 'REMOVE_AMBULANCE'
  | 'REDUCE_HOSPITAL_CAPACITY'
  | 'NEW_EMERGENCY'
  | 'SET_CELL'
  | 'FLOOD_CELLS'

export interface CellInfo {
  row: number
  col: number
  type: CellType
  danger: number
  traversal_cost: number | null
  accessible: boolean
  belief_type: CellType
  known_to_agent: boolean
  profiles: Record<string, { accessible: boolean; cost: number | null }>
  occupants: string[]
  facility: string | null
}

// ---- Algorithm Lab
export interface LabMap {
  rows: number
  cols: number
  cells: string[]
  danger: number[][]
  suggested_start: Pos
  suggested_goal: Pos
  victims: { id: string; pos: Pos }[]
  hospitals: { id: string; pos: Pos }[]
  units: { id: string; pos: Pos }[]
}

export interface LabResult extends SearchTrace {
  label: string
  optimal: boolean
  cost_ratio: number | null
  path_danger: number
}

export interface CompareResponse {
  start: Pos
  goal: Pos
  profile: string
  danger_aware: boolean
  heuristic: string
  optimal_cost: number | null
  reference: { algorithm: string; nodes_expanded: number; cost: number }
  results: LabResult[]
  timing_repeats: number
}

export interface BenchmarkRow {
  algorithm: Algorithm
  label: string
  avg_nodes_expanded: number
  avg_cost_ratio: number
  max_cost_ratio: number
  avg_time_ms: number
  avg_steps: number
  avg_max_frontier: number
  optimal_rate: number
}

export interface BenchmarkResponse {
  trials: number
  seed: number
  profile: string
  danger_aware: boolean
  heuristic: string
  summary: BenchmarkRow[]
}

export interface OnlineRun {
  algorithm: string
  found: boolean
  trajectory: Pos[]
  steps: number
  cost: number
  replans: number
  nodes_expanded: number
  heuristic_updates: number
  cells_revealed: Pos[]
  events: { step: number; pos: Pos; message: string }[]
  time_ms: number
}

export interface OnlineResponse {
  start: Pos
  goal: Pos
  sensor_radius: number
  offline: { algorithm: string; found: boolean; trajectory: Pos[]; steps: number; cost: number; nodes_expanded: number }
  repeated_astar: OnlineRun
  lrta_star: OnlineRun
}
