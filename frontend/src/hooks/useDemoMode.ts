import { useCallback, useEffect, useRef, useState } from 'react'
import type { Snapshot } from '../types/api'
import type { SimController } from './useSimulation'

export type CenterTab = 'log' | 'plan' | 'csp' | 'search' | 'state'

export interface Caption {
  step: number
  total: number
  title: string
  body: string
  holdMs: number
  shownAt: number
}

interface DemoStep {
  id: string
  title: string
  body: (s: Snapshot) => string
  when: (s: Snapshot, seen: Set<string>) => boolean
  holdMs: number
  tab?: CenterTab
  focusTopVictim?: boolean
  speed?: number
}

const LOOKAHEAD_MS = 250

const hasLog = (s: Snapshot, text: string) => s.log.some((e) => e.message.includes(text))
const hasEvent = (s: Snapshot, type: string) => s.events.some((e) => e.event_type === type && e.tick === s.tick)

const STEPS: DemoStep[] = [
  {
    id: 'intro',
    title: 'Magnitude 7.1 earthquake',
    body: (s) =>
      `${s.victims.filter((v) => v.reported).length} victims reported, ${s.ambulances.length} ambulances, ${s.teams.length} rescue teams and ${s.hospitals.length} hospitals. ` +
      'The AI Commander is a goal-based rational agent: every tick it runs PERCEIVE → UPDATE STATE → IDENTIFY GOALS → CHECK CONSTRAINTS → PLAN → SELECT ACTION → EXECUTE → OBSERVE.',
    when: (s) => s.tick === 0,
    holdMs: 6000,
    tab: 'log',
  },
  {
    id: 'goals',
    title: 'Identify goals: rational prioritisation',
    body: (s) => {
      const top = [...s.victims].filter((v) => v.reported).sort((a, b) => b.priority - a.priority)[0]
      return `The agent scores every victim on severity, health, survival window, hazard exposure, waiting time and entrapment. ${top ? `${top.id} (${top.severity}) ranks first with priority ${top.priority.toFixed(1)} - its breakdown is open on the right.` : ''}`
    },
    when: (s) => s.tick >= 1,
    holdMs: 6500,
    tab: 'log',
    focusTopVictim: true,
  },
  {
    id: 'csp',
    title: 'Check constraints: resource allocation as a CSP',
    body: (s) => {
      const c = s.last_csp
      if (!c) return 'Resources are assigned by a constraint satisfaction solver.'
      return `${c.variables.length} victim variables, ${c.constraints.total} constraints. Node consistency removed ${c.stats.node_consistency_removals} infeasible values, AC-3 checked ${c.stats.ac3_revisions} arcs, and backtracking with forward checking ${c.optimal ? 'proved the optimal' : 'found the best'} assignment in ${c.stats.nodes} nodes.`
    },
    when: (s) => s.tick >= 1 && s.last_csp !== null,
    holdMs: 8000,
    tab: 'csp',
  },
  {
    id: 'plan',
    title: 'Plan: A* routes + hierarchical mission plan',
    body: (s) => {
      const r = s.last_search
      return `Each rescue goal is decomposed (HTN) into Assign → Navigate → Rescue → Transport → Deliver → Update. Routes come from A*, f(n) = g(n) + h(n) with danger-aware costs${r ? ` - e.g. ${r.purpose}: ${r.steps} steps, ${r.nodes_expanded} nodes explored` : ''}.`
    },
    when: (s) => s.tick >= 1,
    holdMs: 7000,
    tab: 'plan',
  },
  {
    id: 'move',
    title: 'Execute: resources move out',
    body: () =>
      'Dashed lines are the planned routes. Amber “?” cells are road damage the agent does not know about yet - its sensors must find it. (Advanced view also shows each search’s explored cells and frontier.)',
    when: (s) => s.tick >= 2,
    holdMs: 4500,
    tab: 'log',
    speed: 0.6,
  },
  {
    id: 'sensor',
    title: 'Online search: unknown terrain discovered',
    body: () =>
      'A unit’s sensors found road damage that was missing from the situation report. The belief map is updated, the plan re-checked, and any affected route repaired - search in a partially known environment.',
    when: (s) => hasLog(s, 'revealed by sensors'),
    holdMs: 6000,
    tab: 'log',
  },
  {
    id: 'aftershock',
    title: 'AFTERSHOCK - road blocked on an active route',
    body: () =>
      'Watch the agent react autonomously: ENVIRONMENT CHANGE DETECTED → previous plan invalid → stop → A* search → constraint check → new path → mission resumed. The old route flashes red; the new one glows.',
    when: (s) => hasEvent(s, 'BLOCK_ROAD'),
    holdMs: 9000,
    tab: 'log',
  },
  {
    id: 'fire',
    title: 'Gas main rupture: fire spreads',
    body: () => 'Fire raises the danger of nearby cells. Danger-aware path costs steer A* away from the flames, and burning roads become impassable.',
    when: (s) => hasEvent(s, 'START_FIRE'),
    holdMs: 5500,
    tab: 'log',
  },
  {
    id: 'victim',
    title: 'New critical victim: the goal set changes',
    body: (s) => {
      const vid = s.events.find((e) => e.event_type === 'ADD_VICTIM')?.victim_ids[0]
      const row = s.last_csp?.variables.find((v) => v.var === vid)
      const base = `A building collapse adds a trapped CRITICAL victim${vid ? ` (${vid})` : ''}. The goal set is re-formulated and the CSP runs again.`
      if (!row?.assigned) return base
      if (row.method === 'EXTRACT_ONLY')
        return `${base} No ALS ambulance is free, so a complete plan is impossible right now: the CSP picks a partial plan - ${row.assigned} - and transport follows in a later round.`
      return `${base} Decision: ${row.assigned}.`
    },
    when: (s) => hasEvent(s, 'ADD_VICTIM'),
    holdMs: 6500,
    tab: 'plan',
  },
  {
    id: 'hospital',
    title: 'Power failure at a hospital',
    body: (s) =>
      hasLog(s, 'Destination re-allocation CSP')
        ? 'Capacity dropped below the patients already inbound: the hospital-capacity constraint is violated, so a second CSP re-allocates destinations and A* re-routes the transports.'
        : 'Hospital capacity dropped. The agent re-checked every inbound patient against the new ER/ICU limits; all assignments still fit.',
    when: (s) => hasEvent(s, 'REDUCE_HOSPITAL_CAPACITY'),
    holdMs: 8000,
    tab: 'log',
  },
  {
    id: 'autonomy',
    title: 'Autonomous completion',
    body: () => 'The remaining rescues run without intervention. Every decision stays traceable in the decision log and the HTN mission tree.',
    when: (s) => s.tick >= 56,
    holdMs: 3500,
    tab: 'plan',
    speed: 1.6,
  },
]

export function useDemoMode(sim: SimController, ui: { setTab: (t: CenterTab) => void; selectVictim: (id: string | null) => void }) {
  const [active, setActive] = useState(false)
  const [caption, setCaption] = useState<Caption | null>(null)
  const fired = useRef(new Set<string>())
  const busyUntil = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const snapRef = useRef<Snapshot | null>(null)
  snapRef.current = sim.snap
  const activeRef = useRef(false)

  const evaluate = useCallback(() => {
    const s = snapRef.current
    if (!activeRef.current || !s || Date.now() < busyUntil.current) return
    const idx = STEPS.findIndex((st) => !fired.current.has(st.id) && st.when(s, fired.current))
    if (idx < 0) return
    const st = STEPS[idx]
    fired.current.add(st.id)
    setCaption({ step: idx + 1, total: STEPS.length, title: st.title, body: st.body(s), holdMs: st.holdMs, shownAt: Date.now() })
    sim.hold(st.holdMs)
    // Re-evaluate just before the hold expires so consecutive captions about the
    // same tick chain without the simulation advancing in between.
    busyUntil.current = Date.now() + st.holdMs - LOOKAHEAD_MS
    if (st.tab) ui.setTab(st.tab)
    if (st.speed) sim.setSpeed(st.speed)
    if (st.focusTopVictim) {
      const top = [...s.victims].filter((v) => v.reported).sort((a, b) => b.priority - a.priority)[0]
      ui.selectVictim(top?.id ?? null)
    }
    if (timer.current) clearTimeout(timer.current)
    // When the hold ends, the same snapshot may already satisfy the next step.
    timer.current = setTimeout(evaluate, st.holdMs - LOOKAHEAD_MS + 20)
  }, [sim, ui])

  useEffect(() => {
    evaluate()
  }, [sim.snap, evaluate])

  const start = useCallback(async () => {
    fired.current = new Set()
    busyUntil.current = 0
    activeRef.current = true
    setActive(true)
    sim.setSpeed(0.6)
    const snap = await sim.create('DEMO', 'ASTAR')
    if (!snap) {
      activeRef.current = false
      setActive(false)
      return
    }
    snapRef.current = snap
    evaluate()
    sim.play()
  }, [sim, evaluate])

  const stop = useCallback(() => {
    activeRef.current = false
    setActive(false)
    setCaption(null)
    if (timer.current) clearTimeout(timer.current)
    sim.hold(0)
    sim.pause()
    sim.setSpeed(1)
  }, [sim])

  useEffect(() => {
    if (active && sim.snap && (sim.snap.status === 'COMPLETE' || sim.snap.status === 'STALLED')) {
      setCaption({
        step: STEPS.length,
        total: STEPS.length,
        title: 'Demo complete',
        body: 'All reported victims were resolved. The mission report summarises what the agent did.',
        holdMs: 0,
        shownAt: Date.now(),
      })
      activeRef.current = false
      setActive(false)
      sim.setSpeed(1)
    }
  }, [active, sim])

  return { active, caption, start, stop, dismissCaption: () => setCaption(null) }
}

export type DemoController = ReturnType<typeof useDemoMode>
