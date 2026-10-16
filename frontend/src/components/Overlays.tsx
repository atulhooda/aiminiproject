import { useEffect, useRef, useState } from 'react'
import type { Reaction } from '../hooks/useSimulation'
import { api } from '../services/api'
import type { CellInfo, CustomConfig, LogEntry, Pos, Snapshot } from '../types/api'

// ------------------------------------------------------------ reaction banner
function stepStyle(e: LogEntry): { icon: string; cls: string } {
  if (e.message === 'ENVIRONMENT CHANGE DETECTED') return { icon: '⚠', cls: 'text-red-300 font-bold' }
  if (e.level === 'EVENT') return { icon: '◆', cls: 'text-orange-300' }
  if (e.message.startsWith('Mission affected') || e.message.startsWith('Constraint violated')) return { icon: '✗', cls: 'text-red-300' }
  if (e.level === 'REPLAN') return { icon: '↻', cls: 'text-amber-300' }
  if (e.level === 'SEARCH') return { icon: '⌕', cls: 'text-cyan-300' }
  if (e.level === 'CSP') return { icon: '▦', cls: 'text-violet-300' }
  if (e.message.startsWith('Mission resumed')) return { icon: '▶', cls: 'text-emerald-300 font-semibold' }
  if (e.level === 'SUCCESS' || e.message.startsWith('Checking constraints')) return { icon: '✓', cls: 'text-emerald-300' }
  return { icon: '·', cls: 'text-slate-300' }
}

export function ReactionBanner({ reaction, onClose }: { reaction: Reaction | null; onClose: () => void }) {
  const [shown, setShown] = useState(0)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    if (!reaction) return
    setShown(0)
    let n = 0
    const iv = setInterval(() => {
      n += 1
      setShown(n)
      if (n >= reaction.lines.length) clearInterval(iv)
    }, 320)
    const close = setTimeout(() => closeRef.current(), 4500 + reaction.lines.length * 320)
    return () => {
      clearInterval(iv)
      clearTimeout(close)
    }
  }, [reaction])
  if (!reaction) return null
  return (
    <div className="pointer-events-auto absolute left-1/2 top-3 z-20 w-[min(480px,90%)] -translate-x-1/2 rounded-lg border border-red-700 bg-ink-950/92 p-3 shadow-2xl backdrop-blur animate-alarm">
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-extrabold tracking-[0.12em] text-red-400">ENVIRONMENT CHANGE DETECTED</span>
        <span className="text-[11px] text-slate-400">tick {reaction.tick}</span>
        <button className="ml-auto text-slate-500 hover:text-slate-200" onClick={onClose} aria-label="Dismiss">
          ✕
        </button>
      </div>
      <div className="mt-0.5 text-[11.5px] text-slate-300">{reaction.headline}</div>
      <ol className="mt-2 space-y-0.5 font-mono text-[11px]">
        {reaction.lines.slice(0, shown).map((e) => {
          const s = stepStyle(e)
          return (
            <li key={e.seq} className={`animate-blink-in flex gap-2 ${s.cls}`}>
              <span className="w-3 shrink-0 text-center">{s.icon}</span>
              <span className="min-w-0">
                {e.message}
                {e.details[0] && e.level !== 'CSP' && <span className="block truncate text-slate-500">{e.details[0]}</span>}
              </span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

// ------------------------------------------------------------- cell inspector
export function CellInspector({ snap, pos }: { snap: Snapshot; pos: Pos | null }) {
  const [info, setInfo] = useState<CellInfo | null>(null)
  const key = pos ? `${pos[0]},${pos[1]}|${snap.tick}|${snap.grid.version}|${snap.belief_version}` : ''
  useEffect(() => {
    if (!pos) {
      setInfo(null)
      return
    }
    let alive = true
    const t = setTimeout(() => {
      api
        .cell(snap.session_id, pos)
        .then((c) => alive && setInfo(c))
        .catch(() => alive && setInfo(null))
    }, 90)
    return () => {
      alive = false
      clearTimeout(t)
    }
    // Refetch only when the hovered cell or the world changes (encoded in `key`).
  }, [key])
  if (!pos || !info) return null
  return (
    <div className="pointer-events-none absolute bottom-2 left-2 z-10 w-60 rounded-md border border-ink-500 bg-ink-950/92 p-2 font-mono text-[10.5px] text-slate-300 shadow-xl">
      <div className="flex justify-between text-[11.5px] font-semibold text-slate-100">
        <span>
          ({info.row}, {info.col}) {info.type}
        </span>
        {info.facility && <span className="text-sky-300">{info.facility}</span>}
      </div>
      <div>danger level {info.danger.toFixed(2)}</div>
      <div>
        ambulance: {info.accessible ? `accessible · cost ${info.traversal_cost}` : 'inaccessible'}
      </div>
      {Object.entries(info.profiles)
        .filter(([k]) => k !== 'GROUND_VEHICLE')
        .map(([k, v]) => (
          <div key={k} className="text-slate-500">
            {k.toLowerCase().replace('_', ' ')}: {v.accessible ? `cost ${v.cost}` : 'no'}
          </div>
        ))}
      {!info.known_to_agent && <div className="mt-1 text-amber-300">Agent believes {info.belief_type}: hazard not yet discovered</div>}
      {info.occupants.length > 0 && <div className="mt-1 text-cyan-300">here: {info.occupants.join(', ')}</div>}
    </div>
  )
}

// ------------------------------------------------------------ custom scenario
export const DEFAULT_CUSTOM: CustomConfig = {
  rows: 25,
  cols: 25,
  seed: 42,
  victims: 8,
  critical_ratio: 0.3,
  ambulances: 3,
  teams: 3,
  hospitals: 2,
  obstacle_density: 0.06,
  fire_seeds: 1,
  fire_spread: true,
  hidden_hazards: 2,
  flood: false,
}

export function CustomScenarioDialog({ onClose, onCreate }: { onClose: () => void; onCreate: (c: CustomConfig) => void }) {
  const [cfg, setCfg] = useState<CustomConfig>(DEFAULT_CUSTOM)
  const num = (k: keyof CustomConfig, label: string, min: number, max: number, step = 1) => (
    <label className="flex flex-col gap-1 text-[11px] text-slate-400">
      <span className="flex justify-between">
        {label}
        <b className="font-mono text-slate-200">{String(cfg[k])}</b>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={Number(cfg[k])}
        onChange={(e) => setCfg({ ...cfg, [k]: Number(e.target.value) })}
        className="accent-cyan-500"
      />
    </label>
  )
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="panel w-full max-w-xl p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center">
          <h2 className="text-base font-semibold text-slate-100">Custom scenario</h2>
          <button className="ml-auto text-slate-500 hover:text-slate-200" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <p className="mt-1 text-[12px] text-slate-400">
          Generates a city grid with avenues and alleys, then places facilities, units, victims and hazards. Connectivity between base,
          hospitals and safe zone is guaranteed. After loading you can also paint terrain with the map editor.
        </p>
        <div className="mt-4 grid grid-cols-2 gap-x-5 gap-y-3">
          {num('rows', 'Rows', 12, 40)}
          {num('cols', 'Columns', 12, 40)}
          {num('victims', 'Victims', 1, 25)}
          {num('critical_ratio', 'Critical share', 0, 1, 0.05)}
          {num('ambulances', 'Ambulances', 1, 8)}
          {num('teams', 'Rescue teams', 0, 8)}
          {num('hospitals', 'Hospitals', 1, 4)}
          {num('obstacle_density', 'Debris density', 0, 0.25, 0.01)}
          {num('fire_seeds', 'Fire seeds', 0, 6)}
          {num('hidden_hazards', 'Hidden hazards', 0, 10)}
          {num('seed', 'Random seed', 1, 999)}
          <div className="flex flex-col justify-end gap-1.5 text-[11.5px] text-slate-300">
            <label className="flex items-center gap-2">
              <input type="checkbox" className="accent-cyan-500" checked={cfg.fire_spread} onChange={(e) => setCfg({ ...cfg, fire_spread: e.target.checked })} />
              Fire spreads over time
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" className="accent-cyan-500" checked={cfg.flood} onChange={(e) => setCfg({ ...cfg, flood: e.target.checked })} />
              River flooding
            </label>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button className="btn" onClick={() => setCfg(DEFAULT_CUSTOM)}>
            Defaults
          </button>
          <button className="btn btn-primary" onClick={() => onCreate(cfg)}>
            Generate & load
          </button>
        </div>
      </div>
    </div>
  )
}

// --------------------------------------------------------------- final report
export function FinalReport({ snap, onClose, demo }: { snap: Snapshot; onClose: () => void; demo?: boolean }) {
  const s = snap.stats
  const a = s.agent
  const rows: [string, string | number][] = [
    ['Victims rescued', `${s.rescued_victims} / ${s.total_victims}`],
    ['Victims lost', s.deceased_victims],
    ['Mission duration', `${snap.tick} ticks`],
    ['Average rescue time', s.avg_rescue_time != null ? `${s.avg_rescue_time} ticks` : '-'],
    ['Total distance travelled', `${s.total_distance} cells`],
    ['Replanning events', s.replanning_count],
    ['  route repairs (online search)', a.route_replans],
    ['  mission re-assignments', a.reassignments],
    ['  hospital re-allocations', a.destination_changes],
    ['Hidden hazards discovered', a.hazards_discovered],
    ['Unreported victims found', a.victims_discovered],
    ...(s.unreported_victims > 0 ? ([['Victims never discovered', s.unreported_victims]] as [string, number][]) : []),
    ['Route searches', `${a.searches} (${a.nodes_expanded.toLocaleString()} nodes, ${a.search_time_ms.toFixed(1)} ms)`],
    ['CSP solves', `${a.csp_runs} (${a.csp_nodes.toLocaleString()} nodes, ${a.csp_time_ms.toFixed(1)} ms)`],
    ['HTN missions', `${a.missions_created} planned · ${a.missions_completed} completed · ${a.missions_aborted} aborted`],
  ]
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-4" onClick={onClose}>
      <div className="panel w-full max-w-lg p-5" onClick={(e) => e.stopPropagation()}>
        <div className="panel-title text-cyan-300">{demo ? 'Demo complete' : 'Mission report'}</div>
        <h2 className="mt-1 text-lg font-semibold text-slate-100">{snap.scenario.name}</h2>
        <p className="text-[12px] text-slate-400">{snap.end_reason}</p>
        <div className="mt-3 flex items-end gap-3">
          <div className="text-5xl font-semibold text-emerald-300">{s.total_victims ? Math.round((100 * s.rescued_victims) / s.total_victims) : 0}%</div>
          <div className="pb-1.5 text-[12px] text-slate-400">of reported victims delivered to care</div>
        </div>
        <table className="mt-3 w-full text-[12px]">
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k} className="border-t border-ink-600">
                <td className={`py-1 ${k.startsWith('  ') ? 'pl-4 text-slate-500' : 'text-slate-400'}`}>{k.trim()}</td>
                <td className="py-1 text-right font-mono text-slate-100">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-3 text-[11px] text-slate-500">
          Hospitals:{' '}
          {snap.hospitals.map((h) => `${h.id} ER ${h.er_occupancy}/${h.er_capacity}, ICU ${h.icu_occupancy}/${h.icu_capacity}`).join(' · ')}
        </div>
        <div className="mt-4 flex justify-end">
          <button className="btn btn-primary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
