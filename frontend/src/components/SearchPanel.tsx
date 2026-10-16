import { ALGO_LABEL } from '../simulation/theme'
import type { Snapshot } from '../types/api'
import { Empty } from './CspPanel'

export function SearchPanel({ snap }: { snap: Snapshot }) {
  const s = snap.last_search
  if (!s) return <Empty text="No route search yet. Searches run when missions are planned or repaired." />
  return (
    <div className="scroll-thin h-full overflow-y-auto px-3 py-2.5 text-[12px]">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-semibold text-slate-100">{ALGO_LABEL[s.algorithm]}</span>
        <span className="text-slate-400">{s.purpose}</span>
        <span className="ml-auto text-[11px] text-slate-500">tick {s.tick}</span>
      </div>
      <div className="mt-1 font-mono text-[11px] text-slate-400">
        {s.unit_id ?? 'route'} · ({s.start.join(', ')}) → ({s.goal.join(', ')}) · profile {s.profile}
      </div>
      <div className="mt-3 grid grid-cols-3 gap-1.5 md:grid-cols-6">
        <Tile label="Path cost" value={s.found ? s.cost.toFixed(1) : '-'} />
        <Tile label="Steps" value={s.found ? String(s.steps) : 'no path'} />
        <Tile label="Nodes explored" value={String(s.nodes_expanded)} />
        <Tile label="Frontier (end)" value={String(s.frontier.length)} />
        <Tile label="Time" value={`${s.time_ms.toFixed(2)} ms`} />
        <Tile label="h(start)" value={s.heuristic_start != null ? s.heuristic_start.toFixed(0) : 'n/a'} />
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
        {s.algorithm === 'ASTAR' && 'A* expands the frontier node with the lowest f(n) = g(n) + h(n): g is the danger-aware cost so far, h the Manhattan distance to the goal.'}
        {s.algorithm === 'GREEDY' && 'Greedy best-first expands the node with the lowest h(n) only - fast, but blind to the cost already paid.'}
        {s.algorithm === 'BFS' && 'BFS expands nodes in order of depth: it finds the fewest-steps route but ignores danger-weighted costs.'}{' '}
        On the map: <span className="text-cyan-300">cyan cells</span> were explored, <span className="text-amber-300">amber outlines</span> are the
        final frontier.
      </p>

      <div className="mt-3 panel-title">Recent searches</div>
      <table className="mt-1 w-full font-mono text-[11px]">
        <thead>
          <tr className="text-left text-[10px] uppercase tracking-wide text-slate-500">
            <th className="py-1 font-semibold">t</th>
            <th className="font-semibold">Purpose</th>
            <th className="text-right font-semibold">Cost</th>
            <th className="text-right font-semibold">Nodes</th>
            <th className="text-right font-semibold">ms</th>
          </tr>
        </thead>
        <tbody>
          {snap.search_history.map((h, i) => (
            <tr key={i} className="border-t border-ink-600">
              <td className="py-0.5 text-slate-500">{h.tick}</td>
              <td className="max-w-0 truncate text-slate-300">
                {h.algorithm} · {h.purpose}
              </td>
              <td className="text-right text-slate-300">{h.found ? h.cost.toFixed(1) : '✗'}</td>
              <td className="text-right text-slate-300">{h.nodes_expanded}</td>
              <td className="text-right text-slate-400">{h.time_ms.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-ink-600 bg-ink-800 px-2 py-1.5">
      <div className="text-[9.5px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="font-mono text-[13px] font-semibold text-slate-100">{value}</div>
    </div>
  )
}

export function StatePanel({ snap }: { snap: Snapshot }) {
  const st = snap.state
  return (
    <div className="scroll-thin h-full overflow-y-auto px-3 py-2.5 text-[12px]">
      <p className="text-[11.5px] leading-relaxed text-slate-400">
        The agent formulates the disaster as a <b className="text-slate-200">state-space problem</b>. This is the current state
        s<sub>{st.tick}</sub>; every primitive action (MOVE, RESCUE, TRANSPORT, DELIVER, WAIT) is a transition s → s′, and the goal test is
        “every reported victim has been rescued (or lost)”.
        <span className={`ml-1 chip border ${st.is_goal ? 'border-emerald-600 text-emerald-300' : 'border-ink-500 text-slate-400'}`}>
          goal test: {st.is_goal ? 'TRUE' : 'false'}
        </span>
      </p>
      <pre className="mt-2 overflow-x-auto rounded-md border border-ink-600 bg-ink-850 p-2.5 font-mono text-[11px] leading-relaxed text-slate-300">
        {`s(${st.tick}) = {
  resource_positions: { ${Object.entries(st.resource_positions).map(([k, p]) => `${k}: (${p.join(',')})`).join(', ')} },
  available_resources: [${st.available_resources.join(', ')}],
  remaining_victims: { ${Object.entries(st.remaining_victims).map(([k, v]) => `${k}: ${v}`).join(', ') || '∅'} },
  blocked_roads: ${st.blocked_roads.length} cells [${st.blocked_roads.slice(0, 8).map((p) => `(${p.join(',')})`).join(' ')}${st.blocked_roads.length > 8 ? ' …' : ''}],
  hazard_cells: ${st.hazard_cells} (fire + flood),
  hospital_capacity: { ${Object.entries(st.hospital_capacity).map(([k, h]) => `${k}: ER ${h.er_free} / ICU ${h.icu_free}`).join(', ')} },
  rescue_tasks: {
${Object.entries(st.rescue_tasks).map(([k, t]) => `    ${k}: ${t}`).join('\n')}
  }
}`}
      </pre>
      <div className="mt-2 text-[11px] text-slate-500">
        Belief map version {snap.belief_version} · {snap.belief_diff.length} cell(s) where the agent's belief still differs from ground truth
        (hidden hazards, shown as <span className="text-amber-300">?</span> on the map).
      </div>
    </div>
  )
}
