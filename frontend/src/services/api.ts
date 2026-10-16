import type {
  Algorithm,
  BenchmarkResponse,
  CellInfo,
  CompareResponse,
  CustomConfig,
  EventType,
  LabMap,
  Meta,
  OnlineResponse,
  Pos,
  Snapshot,
} from '../types/api'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the AI engine. Is the backend running on port 8000?')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) })

/** What the client did to a simulation, in order - enough to rebuild it exactly. */
export type JournalEntry =
  | { kind: 'steps'; n: number }
  | { kind: 'event'; type: EventType; target: Pos | null; params: Record<string, unknown> }
  | { kind: 'algorithm'; algorithm: Algorithm }

export interface LabSource {
  scenario: string
  session_id?: string | null
}

export const api = {
  meta: () => request<Meta>('/api/meta'),

  createSimulation: (scenario: string, algorithm: Algorithm, custom?: CustomConfig) =>
    post<Snapshot>('/api/simulations', { scenario, algorithm, custom: custom ?? null }),
  replay: (scenario: string, algorithm: Algorithm, custom: CustomConfig | undefined, journal: JournalEntry[]) =>
    post<Snapshot>('/api/simulations/replay', { scenario, algorithm, custom: custom ?? null, journal }),
  getSimulation: (id: string, since: number) => request<Snapshot>(`/api/simulations/${id}?since=${since}`),
  step: (id: string, since: number, steps = 1) => post<Snapshot>(`/api/simulations/${id}/step`, { steps, since }),
  reset: (id: string) => post<Snapshot>(`/api/simulations/${id}/reset`, {}),
  setAlgorithm: (id: string, algorithm: Algorithm, since: number) =>
    post<Snapshot>(`/api/simulations/${id}/algorithm`, { algorithm, since }),
  triggerEvent: (id: string, type: EventType, since: number, target?: Pos | null, params: Record<string, unknown> = {}) =>
    post<Snapshot>(`/api/simulations/${id}/events`, { type, target: target ?? null, params, since }),
  cell: (id: string, pos: Pos) => request<CellInfo>(`/api/simulations/${id}/cells/${pos[0]}/${pos[1]}`),

  labMap: (src: LabSource) => {
    const q = new URLSearchParams({ scenario: src.scenario })
    if (src.session_id) q.set('session_id', src.session_id)
    return request<LabMap>(`/api/lab/map?${q}`)
  },
  compare: (src: LabSource, start: Pos, goal: Pos, profile: string, dangerAware: boolean, heuristic: string) =>
    post<CompareResponse>('/api/lab/compare', {
      ...src,
      start,
      goal,
      profile,
      danger_aware: dangerAware,
      heuristic,
    }),
  benchmark: (src: LabSource, trials: number, profile: string, dangerAware: boolean, heuristic: string) =>
    post<BenchmarkResponse>('/api/lab/benchmark', {
      ...src,
      trials,
      bench_seed: 1,
      profile,
      danger_aware: dangerAware,
      heuristic,
    }),
  online: (src: LabSource, start: Pos, goal: Pos, profile: string, sensorRadius: number) =>
    post<OnlineResponse>('/api/lab/online', { ...src, start, goal, profile, sensor_radius: sensorRadius }),
}
