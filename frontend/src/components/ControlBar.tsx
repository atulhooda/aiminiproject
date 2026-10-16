import { SPEEDS, type SimController } from '../hooks/useSimulation'
import type { Overlays } from '../simulation/renderer'
import { ALGO_LABEL } from '../simulation/theme'
import type { Algorithm, EventType, Meta, Snapshot } from '../types/api'

export interface ArmedEvent {
  type: EventType
  label: string
  params: Record<string, unknown>
}

interface PlaybackProps {
  sim: SimController
  snap: Snapshot
  meta: Meta | null
  scenario: string
  onScenario: (id: string) => void
  onLoad: () => void
  onCustom: () => void
  overlays: Overlays
  onOverlays: (o: Overlays) => void
  locked?: boolean
}

export function PlaybackControls({ sim, snap, meta, scenario, onScenario, onLoad, onCustom, overlays, onOverlays, locked }: PlaybackProps) {
  const done = snap.status === 'COMPLETE'
  return (
    <section className="panel flex flex-col gap-2 p-3">
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
        <button className="btn" onClick={() => void sim.step()} disabled={sim.playing || done || locked} title="Run exactly one decision cycle">
          Step
        </button>
        <button className="btn" onClick={() => void sim.reset()} disabled={locked} title="Restart this scenario">
          ↺ Reset
        </button>
        <div className="ml-1 flex overflow-hidden rounded-md border border-ink-500" role="group" aria-label="Simulation speed">
          {SPEEDS.map((s) => (
            <button
              key={s}
              className={`px-2 py-1 text-[11px] font-semibold ${sim.speed === s ? 'bg-cyan-800 text-cyan-50' : 'bg-ink-700 text-slate-400 hover:text-slate-100'}`}
              onClick={() => sim.setSpeed(s)}
              disabled={locked}
            >
              {s}×
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <select className="select min-w-0 flex-1" value={scenario} onChange={(e) => onScenario(e.target.value)} disabled={locked} aria-label="Scenario">
          {(meta?.scenarios ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <button className="btn" onClick={scenario === 'CUSTOM' ? onCustom : onLoad} disabled={locked}>
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
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-400">
        {(
          [
            ['paths', 'Planned routes'],
            ['search', 'Search overlay'],
            ['danger', 'Danger heatmap'],
            ['unknown', 'Hidden hazards'],
            ['labels', 'Labels'],
          ] as [keyof Overlays, string][]
        ).map(([k, label]) => (
          <label key={k} className="flex items-center gap-1">
            <input type="checkbox" className="accent-cyan-500" checked={overlays[k]} onChange={(e) => onOverlays({ ...overlays, [k]: e.target.checked })} />
            {label}
          </label>
        ))}
      </div>
    </section>
  )
}

interface EventProps {
  sim: SimController
  snap: Snapshot
  pickMode: boolean
  onPickMode: (v: boolean) => void
  armed: ArmedEvent | null
  onArm: (e: ArmedEvent | null) => void
  brush: string | null
  onBrush: (b: string | null) => void
  severity: string
  onSeverity: (s: string) => void
  ambulance: string
  onAmbulance: (s: string) => void
  hospital: string
  onHospital: (s: string) => void
  locked?: boolean
}

const BRUSHES: [string, string, string][] = [
  ['ROAD', 'Road', 'bg-slate-600'],
  ['BUILDING', 'Building', 'bg-slate-900 border border-slate-600'],
  ['OBSTACLE', 'Debris', 'bg-yellow-500'],
  ['FIRE', 'Fire', 'bg-orange-500'],
  ['WATER', 'Water', 'bg-sky-600'],
]

export function DisasterEvents(p: EventProps) {
  const { sim, snap } = p
  const fire = (type: EventType, label: string, params: Record<string, unknown> = {}, locational = true) => {
    p.onBrush(null)
    if (locational && p.pickMode) {
      p.onArm({ type, label, params })
      return
    }
    p.onArm(null)
    void sim.trigger(type, null, params)
  }
  const available = snap.ambulances.filter((a) => a.available)
  const disabled = p.locked || snap.status === 'READY'
  return (
    <section className="panel flex flex-col gap-1.5 p-2.5">
      <div className="flex items-center gap-2">
        <span className="panel-title text-red-300">⚠ Disaster event</span>
        {snap.status === 'READY' && <span className="text-[10.5px] text-slate-500">press Play or Step first</span>}
        <div className="ml-auto flex overflow-hidden rounded-md border border-ink-500 text-[10.5px]" role="group" aria-label="Event target">
          <button className={`px-2 py-0.5 ${!p.pickMode ? 'bg-red-900/70 text-red-100' : 'bg-ink-700 text-slate-400'}`} onClick={() => p.onPickMode(false)}>
            Auto-target route
          </button>
          <button className={`px-2 py-0.5 ${p.pickMode ? 'bg-red-900/70 text-red-100' : 'bg-ink-700 text-slate-400'}`} onClick={() => p.onPickMode(true)}>
            Pick cell
          </button>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        <button className={`btn btn-danger ${p.armed?.type === 'BLOCK_ROAD' ? 'animate-alarm' : ''}`} disabled={disabled} onClick={() => fire('BLOCK_ROAD', 'Block road')}>
          Block road
        </button>
        <button className={`btn btn-danger ${p.armed?.type === 'START_FIRE' ? 'animate-alarm' : ''}`} disabled={disabled} onClick={() => fire('START_FIRE', 'Start fire')}>
          Start fire
        </button>
        <button className={`btn btn-danger ${p.armed?.type === 'NEW_EMERGENCY' ? 'animate-alarm' : ''}`} disabled={disabled} onClick={() => fire('NEW_EMERGENCY', 'New emergency')}>
          New emergency
        </button>
        <button className={`btn btn-danger ${p.armed?.type === 'ADD_VICTIM' ? 'animate-alarm' : ''}`} disabled={disabled} onClick={() => fire('ADD_VICTIM', 'Add victim', { severity: p.severity })}>
          Add victim
        </button>
        <button className="btn btn-danger" disabled={disabled || available.length === 0} onClick={() => fire('REMOVE_AMBULANCE', 'Remove ambulance', p.ambulance ? { unit_id: p.ambulance } : {}, false)}>
          Remove ambulance
        </button>
        <button className="btn btn-danger" disabled={disabled} onClick={() => fire('REDUCE_HOSPITAL_CAPACITY', 'Reduce capacity', p.hospital ? { hospital_id: p.hospital } : {}, false)}>
          Reduce hospital capacity
        </button>
        <select className="select py-1 text-[11px]" value={p.severity} onChange={(e) => p.onSeverity(e.target.value)} aria-label="Severity of new victim">
          {['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'RANDOM'].map((s) => (
            <option key={s} value={s}>
              new victim: {s.toLowerCase()}
            </option>
          ))}
        </select>
        <select className="select py-1 text-[11px]" value={p.ambulance} onChange={(e) => p.onAmbulance(e.target.value)} aria-label="Ambulance to remove">
          <option value="">ambulance: auto (on a mission)</option>
          {available.map((a) => (
            <option key={a.id} value={a.id}>
              ambulance: {a.id} ({a.medical})
            </option>
          ))}
        </select>
        <select className="select py-1 text-[11px]" value={p.hospital} onChange={(e) => p.onHospital(e.target.value)} aria-label="Hospital to reduce">
          <option value="">hospital: auto (most inbound)</option>
          {snap.hospitals.map((h) => (
            <option key={h.id} value={h.id}>
              hospital: {h.id} {h.name}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-wrap items-center gap-1 border-t border-ink-600 pt-1.5">
        <span className="mr-1 text-[10.5px] text-slate-400" title="Paint terrain on the map (click or drag). The agent perceives every edit.">
          Map editor:
        </span>
        {BRUSHES.map(([type, label, sw]) => (
          <button
            key={type}
            className={`flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10.5px] ${p.brush === type ? 'border-violet-400 bg-violet-950 text-violet-100' : 'border-ink-500 text-slate-400 hover:text-slate-100'}`}
            onClick={() => {
              p.onArm(null)
              p.onBrush(p.brush === type ? null : type)
            }}
            disabled={p.locked}
          >
            <span className={`h-2 w-2 rounded-sm ${sw}`} />
            {label}
          </button>
        ))}
      </div>
    </section>
  )
}

export function AlgorithmInfo({ snap }: { snap: Snapshot }) {
  const s = snap.last_search
  const a = snap.stats.agent
  return (
    <section className="panel flex flex-col gap-1.5 p-3">
      <div className="panel-title">Algorithm info</div>
      <div className="text-[12.5px] font-semibold text-slate-100">{ALGO_LABEL[snap.algorithm]}</div>
      <div className="text-[10.5px] leading-snug text-slate-400">
        {snap.algorithm === 'ASTAR' && 'f(n) = g(n) + h(n) · Manhattan h · danger-aware g · optimal'}
        {snap.algorithm === 'GREEDY' && 'f(n) = h(n) · fast, not optimal'}
        {snap.algorithm === 'BFS' && 'FIFO frontier · fewest steps · ignores costs'}
      </div>
      {s ? (
        <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 font-mono text-[11px]">
          <span className="text-slate-500">last route</span>
          <span className="truncate text-slate-300" title={s.purpose}>
            {s.purpose}
          </span>
          <span className="text-slate-500">path cost</span>
          <span className="text-slate-200">{s.found ? s.cost.toFixed(1) : 'no path'}</span>
          <span className="text-slate-500">nodes explored</span>
          <span className="text-slate-200">{s.nodes_expanded}</span>
          <span className="text-slate-500">execution</span>
          <span className="text-slate-200">{s.time_ms.toFixed(3)} ms</span>
        </div>
      ) : (
        <div className="text-[11px] text-slate-500">No search yet.</div>
      )}
      <div className="mt-auto border-t border-ink-600 pt-1 font-mono text-[10.5px] text-slate-500">
        total {a.searches} searches · {a.search_time_ms.toFixed(1)} ms
      </div>
    </section>
  )
}
