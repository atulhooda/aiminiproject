// Building blocks for the simplified Command Center: fewer panels, plain language.

import { useEffect, useMemo, useRef } from 'react'
import { SPEEDS, type SimController } from '../hooks/useSimulation'
import { PHASES, PHASE_LABEL, PHASE_SHORT } from '../simulation/theme'
import type { Algorithm, EventType, LogEntry, Meta, Snapshot } from '../types/api'

/** One-line view of the agent's perceive → act cycle; hover a step for details. */
export function CompactCycle({ snap }: { snap: Snapshot }) {
  const ran = new Map(snap.phase_trace.map((p) => [p.phase, p.summary]))
  return (
    <div className="panel flex flex-wrap items-center gap-x-1 gap-y-1 px-3 py-1.5 text-[11.5px]">
      <span className="panel-title mr-2">AI decision cycle</span>
      {PHASES.map((p, i) => (
        <span key={p} className="flex items-center gap-1">
          <span
            key={`${p}-${snap.log_seq}`}
            className={`rounded border px-1.5 py-0.5 ${ran.has(p) ? 'phase-active border-cyan-700 text-cyan-100' : 'border-ink-600 text-slate-500'}`}
            style={{ animationDelay: `${i * 70}ms` }}
            title={`${PHASE_LABEL[p]}: ${ran.get(p) ?? 'not run in this cycle'}`}
          >
            {PHASE_SHORT[p]}
          </span>
          {i < PHASES.length - 1 && <span className="text-slate-600">→</span>}
        </span>
      ))}
    </div>
  )
}

// Only the moments a viewer cares about: events, decisions, replanning and results.
function isHighlight(e: LogEntry): boolean {
  const m = e.message
  if (e.phase === 'SYSTEM') return m.startsWith('Scenario loaded') || m.startsWith('Navigation search algorithm')
  if (e.level === 'EVENT' || e.level === 'REPLAN') return true
  if (m === 'ENVIRONMENT CHANGE DETECTED' || m.startsWith('Mission affected')) return true
  if (m.startsWith('New path generated') || m.startsWith('Mission resumed')) return true
  if (m.startsWith('Goal formulation') || m.startsWith('Assign ')) return true
  if (m.startsWith('Victim ') && m.includes('delivered')) return true
  if (m.includes('extracted from debris') || m.includes('discovered by') || m.startsWith('Unknown terrain revealed')) return true
  if (m.startsWith('Sub-goal achieved') || m.startsWith('All known victims resolved')) return true
  if (m.startsWith('No route') || m.startsWith('Phase 1') || m.startsWith('Destination re-allocation')) return true
  return false
}

const STYLE: Record<string, { icon: string; cls: string }> = {
  EVENT: { icon: '◆', cls: 'text-orange-300' },
  ALERT: { icon: '!', cls: 'text-red-300' },
  REPLAN: { icon: '↻', cls: 'text-amber-300' },
  SUCCESS: { icon: '✓', cls: 'text-emerald-300' },
  DECISION: { icon: '→', cls: 'text-sky-300' },
  SEARCH: { icon: '⌕', cls: 'text-cyan-300' },
  CSP: { icon: '▦', cls: 'text-violet-300' },
  INFO: { icon: '·', cls: 'text-slate-300' },
}

export function ActivityFeed({ log }: { log: LogEntry[] }) {
  const items = useMemo(() => log.filter(isHighlight).slice(-200), [log])
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = ref.current
    if (el) el.scrollTop = el.scrollHeight
  }, [items])
  return (
    <section className="panel flex min-h-0 flex-1 flex-col p-3">
      <div className="panel-title mb-1.5" title="Key moments only - the full decision log is in Advanced view">
        What the AI is doing
      </div>
      <div ref={ref} className="scroll-thin min-h-0 flex-1 space-y-1 overflow-y-auto pr-1 text-[12px] leading-snug">
        {items.length === 0 && <div className="py-6 text-center text-slate-500">Press Play to start the rescue.</div>}
        {items.map((e) => {
          const s = e.message === 'ENVIRONMENT CHANGE DETECTED' ? { icon: '⚠', cls: 'font-bold text-red-300' } : STYLE[e.level] ?? STYLE.INFO
          return (
            <div key={e.seq} className="flex gap-2">
              <span className="w-8 shrink-0 text-right font-mono text-[10.5px] text-slate-500">t{e.tick}</span>
              <span className={`w-3 shrink-0 text-center ${s.cls}`}>{s.icon}</span>
              <span className={`min-w-0 ${s.cls}`}>{e.message}</span>
            </div>
          )
        })}
      </div>
    </section>
  )
}

export function KeyStats({ snap }: { snap: Snapshot }) {
  const s = snap.stats
  const tiles: [string, string, string][] = [
    ['Rescued', `${s.rescued_victims} / ${s.total_victims}`, 'text-emerald-300'],
    ['Need help', String(s.active_victims), 'text-slate-100'],
    ['Critical', String(s.critical_victims), s.critical_victims ? 'text-red-300' : 'text-slate-100'],
    ['Replans', String(s.replanning_count), s.replanning_count ? 'text-amber-300' : 'text-slate-100'],
  ]
  return (
    <section className="grid shrink-0 grid-cols-4 gap-2">
      {tiles.map(([label, value, cls]) => (
        <div key={label} className="panel px-2.5 py-2">
          <div className="truncate text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
          <div className={`text-xl font-semibold leading-tight ${cls}`}>{value}</div>
        </div>
      ))}
    </section>
  )
}

const QUICK_EVENTS: { type: EventType; label: string; params?: Record<string, unknown> }[] = [
  { type: 'BLOCK_ROAD', label: 'Block a road' },
  { type: 'START_FIRE', label: 'Start a fire' },
  { type: 'ADD_VICTIM', label: 'Add a victim', params: { severity: 'CRITICAL' } },
  { type: 'REMOVE_AMBULANCE', label: 'Break an ambulance' },
  { type: 'REDUCE_HOSPITAL_CAPACITY', label: 'Cut hospital beds' },
]

interface ControlsProps {
  sim: SimController
  snap: Snapshot
  meta: Meta | null
  scenario: string
  onScenario: (id: string) => void
  onLoad: () => void
  locked: boolean
}

/** Everything needed to run the simulation, in one row. */
export function SimpleControls({ sim, snap, meta, scenario, onScenario, onLoad, locked }: ControlsProps) {
  const done = snap.status === 'COMPLETE'
  const started = snap.status !== 'READY'
  return (
    <section className="panel flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2.5">
      <div className="flex items-center gap-1.5">
        {sim.playing ? (
          <button className="btn btn-active w-20" onClick={sim.pause} disabled={locked}>
            ❚❚ Pause
          </button>
        ) : (
          <button className="btn btn-primary w-20" onClick={sim.play} disabled={done || locked}>
            ▶ Play
          </button>
        )}
        <button className="btn" onClick={() => void sim.step()} disabled={sim.playing || done || locked}>
          Step
        </button>
        <button className="btn" onClick={() => void sim.reset()} disabled={locked}>
          ↺ Reset
        </button>
        <select className="select" value={sim.speed} onChange={(e) => sim.setSpeed(Number(e.target.value))} disabled={locked} aria-label="Speed">
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              {s}× speed
            </option>
          ))}
        </select>
      </div>
      <div className="flex items-center gap-1.5">
        <select className="select" value={scenario} onChange={(e) => onScenario(e.target.value)} disabled={locked} aria-label="Scenario">
          {(meta?.scenarios ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <button className="btn" onClick={onLoad} disabled={locked}>
          {scenario === 'CUSTOM' ? 'Configure…' : 'Load'}
        </button>
        <select
          className="select"
          value={snap.algorithm}
          onChange={(e) => void sim.setAlgorithm(e.target.value as Algorithm)}
          disabled={locked}
          aria-label="Search algorithm"
          title="Search algorithm the agent uses for every route"
        >
          {(meta?.algorithms ?? []).map((a) => (
            <option key={a.id} value={a.id}>
              {a.label}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-red-300">Disaster</span>
        {QUICK_EVENTS.map((ev) => (
          <button
            key={ev.type}
            className="btn btn-danger"
            disabled={locked || !started}
            title={started ? 'The AI picks a target on an active route and must react' : 'Press Play or Step first'}
            onClick={() => void sim.trigger(ev.type, null, ev.params ?? {})}
          >
            {ev.label}
          </button>
        ))}
      </div>
    </section>
  )
}

export function CompactLegend() {
  const items: [string, string][] = [
    ['bg-slate-300 rounded-sm w-3.5', 'Ambulance'],
    ['bg-slate-300 rotate-45', 'Rescue team'],
    ['bg-red-500 rounded-full', 'Victim (colour = severity)'],
    ['bg-blue-700 rounded-sm', 'Hospital'],
    ['bg-green-800 rounded-sm', 'Safe zone'],
    ['bg-orange-600 rounded-sm', 'Fire'],
    ['bg-sky-800 rounded-sm', 'Water'],
    ['bg-[repeating-linear-gradient(45deg,#eab308_0_2px,#1f1a0a_2px_4px)] rounded-sm', 'Blocked road'],
  ]
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 px-1 pt-1.5 text-[11px] text-slate-400">
      {items.map(([cls, label]) => (
        <span key={label} className="flex items-center gap-1.5">
          <span className={`h-2.5 w-2.5 ${cls}`} />
          {label}
        </span>
      ))}
      <span className="text-slate-500">· dashed lines = planned routes</span>
    </div>
  )
}
