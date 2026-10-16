import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../services/api'
import type { Algorithm, CustomConfig, EventType, LogEntry, Pos, SearchTrace, Snapshot } from '../types/api'
import type { Flash, ReplanAnim } from '../simulation/renderer'
import { unitColors } from '../simulation/theme'

export const SPEEDS = [0.5, 1, 2, 4, 8] as const
const BASE_INTERVAL = 650
const MAX_LOG = 2500

export interface AnimState {
  prevPositions: Map<string, Pos>
  moveStartedAt: number
  moveDuration: number
  flashes: Flash[]
  replans: ReplanAnim[]
  search: { trace: SearchTrace; startedAt: number } | null
}

export interface Reaction {
  id: number
  tick: number
  headline: string
  lines: LogEntry[]
  startedAt: number
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

const EVENT_COLOR: Record<string, string> = {
  BLOCK_ROAD: '#fbbf24',
  START_FIRE: '#f97316',
  FIRE_SPREAD: '#f97316',
  NEW_EMERGENCY: '#ef4444',
  ADD_VICTIM: '#38bdf8',
  FLOOD_RISE: '#38bdf8',
  FLOOD_CELLS: '#38bdf8',
  SET_CELL: '#a78bfa',
  CLEAR_ROAD: '#4ade80',
}

function searchKey(s: SearchTrace | null): string {
  if (!s) return ''
  return `${s.tick}|${s.purpose}|${s.start}|${s.goal}|${s.nodes_expanded}|${s.cost}`
}

/** Log lines that tell the "detect -> invalidate -> replan -> resume" story. */
function isReactionLine(e: LogEntry): boolean {
  if (e.level === 'EVENT' || e.level === 'REPLAN') return true
  if (e.level === 'ALERT') return true
  if (e.level === 'SEARCH' && e.message.includes(' started:')) return true
  if (e.level === 'SUCCESS' && e.message.startsWith('New path generated')) return true
  if (e.message.startsWith('Checking constraints')) return true
  if (e.message.startsWith('Mission resumed')) return true
  if (e.level === 'CSP' && e.message.startsWith('Destination re-allocation')) return true
  if (e.level === 'DECISION' && e.message.startsWith('Assign ')) return true
  return false
}

export function useSimulation() {
  const [snap, setSnap] = useState<Snapshot | null>(null)
  const [log, setLog] = useState<LogEntry[]>([])
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeedState] = useState<number>(1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reaction, setReaction] = useState<Reaction | null>(null)

  const snapRef = useRef<Snapshot | null>(null)
  const seqRef = useRef(0)
  const queueRef = useRef<Promise<unknown>>(Promise.resolve())
  const intervalRef = useRef(BASE_INTERVAL)
  const holdUntilRef = useRef(0)
  const seenEventsRef = useRef(new Set<string>())
  const reactionIdRef = useRef(0)
  const anim = useRef<AnimState>({
    prevPositions: new Map(),
    moveStartedAt: 0,
    moveDuration: 1,
    flashes: [],
    replans: [],
    search: null,
  })

  const colors = useMemo(
    () => (snap ? unitColors([...snap.ambulances, ...snap.teams].map((u) => u.id)) : {}),
    // unit ids only change when a new scenario is loaded
    [snap?.session_id, snap?.ambulances.length, snap?.teams.length],
  )
  const colorsRef = useRef(colors)
  colorsRef.current = colors

  /** Serialise every request so steps and events never interleave. */
  const enqueue = useCallback(<T,>(fn: () => Promise<T>): Promise<T> => {
    const run = queueRef.current.then(fn, fn)
    queueRef.current = run.catch(() => undefined)
    return run
  }, [])

  const apply = useCallback((next: Snapshot, opts: { fresh?: boolean; moved?: boolean }) => {
    const prev = snapRef.current
    const now = performance.now()
    const a = anim.current
    const units = [...next.ambulances, ...next.teams]

    // Movement interpolation: animate from the previous snapshot's positions.
    const prevPos = new Map<string, Pos>()
    if (prev && opts.moved && !opts.fresh) {
      for (const u of [...prev.ambulances, ...prev.teams]) prevPos.set(u.id, u.pos)
    } else {
      for (const u of units) prevPos.set(u.id, u.pos)
    }
    a.prevPositions = prevPos
    a.moveStartedAt = now
    a.moveDuration = Math.max(120, Math.min(intervalRef.current * 0.85, 600))

    if (opts.fresh) {
      seenEventsRef.current = new Set(next.events.map((e) => `${e.tick}|${e.title}`))
      a.flashes = []
      a.replans = []
      a.search = null
    }

    // Flash cells touched by new environment reports.
    for (const e of next.events) {
      const key = `${e.tick}|${e.title}`
      if (seenEventsRef.current.has(key)) continue
      seenEventsRef.current.add(key)
      if (e.cells.length) {
        a.flashes.push({ cells: e.cells, color: EVENT_COLOR[e.event_type] ?? '#f8fafc', startedAt: now, duration: 1800 })
      }
    }
    a.flashes = a.flashes.filter((f) => now - f.startedAt < f.duration)

    for (const r of next.replan_events) {
      a.replans.push({ oldPath: r.old_path, newPath: r.new_path, color: colorsRef.current[r.unit_id] ?? '#22d3ee', startedAt: now })
    }
    a.replans = a.replans.filter((r) => now - r.startedAt < 3500)

    if (next.last_search && searchKey(next.last_search) !== searchKey(a.search?.trace ?? null)) {
      a.search = { trace: next.last_search, startedAt: now }
    } else if (!next.last_search) {
      a.search = null
    }

    // Accumulate the decision log.
    if (opts.fresh) {
      setLog(next.log)
    } else if (next.log.length) {
      setLog((old) => {
        const merged = old.concat(next.log.filter((e) => e.seq > (old.length ? old[old.length - 1].seq : 0)))
        return merged.length > MAX_LOG ? merged.slice(merged.length - MAX_LOG) : merged
      })
    }

    // Pop the replanning banner when a change matters: a user/scenario event,
    // or any change that invalidated a plan. Harmless natural spread only logs.
    const deliberate = next.events.some((e) => e.tick === next.tick && (e.source === 'USER' || e.source === 'SCENARIO') && e.event_type !== 'SITUATION_REPORT')
    const disruptive = next.alerts.some((al) => al.code === 'PLAN_INVALID') || next.replan_events.length > 0
    if (next.alerts.some((al) => al.code === 'ENV_CHANGE') && (deliberate || disruptive)) {
      const lines = next.log.filter(isReactionLine).slice(0, 14)
      if (lines.length) {
        const headline = next.alerts.find((al) => al.code === 'ENV_CHANGE')?.message ?? 'Environment changed'
        setReaction({ id: ++reactionIdRef.current, tick: next.tick, headline, lines, startedAt: Date.now() })
      }
    }

    seqRef.current = next.log_seq
    snapRef.current = next
    setSnap(next)
  }, [])

  const handleError = useCallback((e: unknown) => {
    setError(e instanceof Error ? e.message : String(e))
    setPlaying(false)
  }, [])

  const create = useCallback(
    async (scenario: string, algorithm: Algorithm, custom?: CustomConfig) => {
      setPlaying(false)
      setBusy(true)
      setReaction(null)
      try {
        const next = await enqueue(() => api.createSimulation(scenario, algorithm, custom))
        apply(next, { fresh: true })
        setError(null)
        return next
      } catch (e) {
        handleError(e)
        return null
      } finally {
        setBusy(false)
      }
    },
    [apply, enqueue, handleError],
  )

  const step = useCallback(async (): Promise<Snapshot | null> => {
    const id = snapRef.current?.session_id
    if (!id) return null
    try {
      const next = await enqueue(() => api.step(id, seqRef.current))
      apply(next, { moved: true })
      return next
    } catch (e) {
      handleError(e)
      return null
    }
  }, [apply, enqueue, handleError])

  const reset = useCallback(async () => {
    const id = snapRef.current?.session_id
    if (!id) return
    setPlaying(false)
    setReaction(null)
    try {
      const next = await enqueue(() => api.reset(id))
      apply(next, { fresh: true })
    } catch (e) {
      handleError(e)
    }
  }, [apply, enqueue, handleError])

  const setAlgorithm = useCallback(
    async (algorithm: Algorithm) => {
      const id = snapRef.current?.session_id
      if (!id) return
      try {
        const next = await enqueue(() => api.setAlgorithm(id, algorithm, seqRef.current))
        apply(next, {})
      } catch (e) {
        handleError(e)
      }
    },
    [apply, enqueue, handleError],
  )

  const trigger = useCallback(
    async (type: EventType, target?: Pos | null, params: Record<string, unknown> = {}): Promise<Snapshot | null> => {
      const id = snapRef.current?.session_id
      if (!id) return null
      try {
        const next = await enqueue(() => api.triggerEvent(id, type, seqRef.current, target, params))
        apply(next, {})
        setError(null)
        return next
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        return null
      }
    },
    [apply, enqueue],
  )

  const setSpeed = useCallback((s: number) => {
    intervalRef.current = BASE_INTERVAL / s
    setSpeedState(s)
  }, [])

  /** Keep the play loop paused for `ms` (used by Demo Mode narration). */
  const hold = useCallback((ms: number) => {
    holdUntilRef.current = Date.now() + ms
  }, [])

  // ------------------------------------------------------------- play loop
  const sessionId = snap?.session_id
  useEffect(() => {
    if (!playing || !sessionId) return
    let cancelled = false
    const loop = async () => {
      while (!cancelled) {
        while (!cancelled && Date.now() < holdUntilRef.current) await sleep(100)
        if (cancelled) break
        const t0 = performance.now()
        const next = await step()
        if (cancelled) break
        if (!next || next.status === 'COMPLETE' || next.status === 'STALLED') {
          setPlaying(false)
          break
        }
        const wait = intervalRef.current - (performance.now() - t0)
        if (wait > 0) await sleep(wait)
      }
    }
    void loop()
    return () => {
      cancelled = true
    }
  }, [playing, sessionId, step])

  const dismissReaction = useCallback(() => setReaction(null), [])
  const clearError = useCallback(() => setError(null), [])

  const play = useCallback(() => {
    const s = snapRef.current
    if (s && s.status !== 'COMPLETE') setPlaying(true)
  }, [])
  const pause = useCallback(() => setPlaying(false), [])

  return {
    snap,
    log,
    playing,
    speed,
    busy,
    error,
    reaction,
    anim,
    colors,
    interval: intervalRef,
    create,
    step,
    reset,
    play,
    pause,
    setSpeed,
    setAlgorithm,
    trigger,
    hold,
    dismissReaction,
    clearError,
  }
}

export type SimController = ReturnType<typeof useSimulation>
