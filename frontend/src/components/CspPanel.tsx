import { SEVERITY_COLOR } from '../simulation/theme'
import type { CspReport } from '../types/api'

export function CspPanel({ csp }: { csp: CspReport | null }) {
  if (!csp) {
    return <Empty text="The CSP solver runs when victims are waiting and resources are idle. Press Step." />
  }
  const st = csp.stats
  const nodeCounts = Object.entries(csp.removal_counts.NODE ?? {}).sort((a, b) => b[1] - a[1])
  const ac3Counts = Object.entries(csp.removal_counts.AC3 ?? {})
  const totalInitial = csp.variables.reduce((n, v) => n + (v.domain_initial ?? 0), 0)
  const totalNode = csp.variables.reduce((n, v) => n + (v.domain_after_node ?? 0), 0)
  const totalAc3 = csp.variables.reduce((n, v) => n + (v.domain_after_ac3 ?? 0), 0)
  const assigned = csp.variables.filter((v) => v.assigned && v.assigned !== 'DEFER' && v.assigned !== 'HOLD').length

  return (
    <div className="scroll-thin h-full overflow-y-auto px-3 py-2.5 text-[12px]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-slate-100">
          {csp.kind === 'RESOURCE_ALLOCATION' ? 'Resource allocation CSP' : 'Hospital re-allocation CSP'}
        </span>
        <span className={`chip border ${csp.result === 'SATISFIED' ? 'border-emerald-600 text-emerald-300' : 'border-red-600 text-red-300'}`}>
          {csp.result}
        </span>
        <span className={`chip border ${csp.optimal ? 'border-cyan-600 text-cyan-300' : 'border-amber-600 text-amber-300'}`}>
          {csp.optimal ? 'optimal (proved)' : 'best within node budget'}
        </span>
        <span className="ml-auto text-[11px] text-slate-500">
          run #{csp.run} · tick {csp.tick}
        </span>
      </div>

      {csp.relaxed && csp.phase1 && (
        <div className="mt-2 rounded-md border border-amber-700/70 bg-amber-950/30 px-2.5 py-1.5 text-[11.5px] text-amber-200">
          Phase 1 with hard <b>critical-coverage</b> was <b>UNSATISFIABLE</b>: {csp.phase1.reason}. The agent relaxed the
          constraint and re-solved (phase 2), deferring the critical victims it cannot serve yet.
        </div>
      )}

      {/* Pipeline */}
      <div className="mt-3 grid grid-cols-4 gap-1.5">
        <Stage title="Variables & domains" value={`${csp.variables.length} vars`} sub={`${totalInitial} candidate values`} />
        <Stage title="Node consistency" value={`−${st.node_consistency_removals}`} sub={`${totalNode} values left`} />
        <Stage title="AC-3" value={`−${st.ac3_removals}`} sub={`${st.ac3_revisions} arc revisions · ${totalAc3} left`} />
        <Stage
          title="Backtracking + FC"
          value={`${st.nodes} nodes`}
          sub={`${st.backtracks} backtracks · ${st.fc_prunings} FC · ${st.bound_prunings} bound · ${st.time_ms.toFixed(1)} ms`}
        />
      </div>

      {/* Variables */}
      <div className="mt-3 panel-title">Variables → assignment ({assigned} assigned)</div>
      <table className="mt-1 w-full border-collapse font-mono text-[11px]">
        <thead>
          <tr className="text-left text-[10px] uppercase tracking-wide text-slate-500">
            <th className="py-1 pr-3 font-semibold">Var</th>
            <th className="pr-3 font-semibold">Prio</th>
            <th className="pr-3 font-semibold" title="domain size: initial → after node consistency → after AC-3">|D| init→NC→AC3</th>
            <th className="font-semibold">Value chosen</th>
            <th className="text-right font-semibold">Utility</th>
          </tr>
        </thead>
        <tbody>
          {csp.variables.map((v) => (
            <tr key={v.var} className="border-t border-ink-600 align-top">
              <td className="whitespace-nowrap py-1 pr-3">
                <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: SEVERITY_COLOR[v.severity] }} />
                <span className="text-slate-100">{v.var}</span>
                {v.coverage_required && <span className="ml-1 text-[9px] text-red-300">must</span>}
              </td>
              <td className="pr-3 text-slate-300">{v.priority.toFixed(1)}</td>
              <td className="whitespace-nowrap pr-3 text-slate-400">
                {v.domain_initial}→{v.domain_after_node}→{v.domain_after_ac3}
              </td>
              <td className={v.assigned === 'DEFER' || v.assigned === 'HOLD' ? 'text-slate-500' : 'text-emerald-300'}>
                {v.assigned}
                {Object.keys(v.prunings).length > 0 && (
                  <div className="text-[10px] text-slate-500">
                    pruned by {Object.entries(v.prunings).map(([k, n]) => `${k}×${n}`).join(', ')}
                  </div>
                )}
              </td>
              <td className="text-right text-slate-300">{v.utility?.toFixed(0)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Constraints */}
      <div className="mt-3 panel-title">Constraints ({csp.constraints.total})</div>
      <div className="mt-1 grid gap-2 md:grid-cols-2">
        <div className="rounded-md border border-ink-600 p-2">
          <div className="mb-1 text-[11px] font-semibold text-slate-300">Unary - node consistency pruning</div>
          {nodeCounts.length === 0 && <div className="text-slate-500">no values removed</div>}
          {nodeCounts.map(([name, n]) => (
            <Bar key={name} label={name} value={n} max={nodeCounts[0][1]} />
          ))}
          {csp.constraints.unary
            .filter((u) => !nodeCounts.some(([n]) => n === u))
            .map((u) => (
              <div key={u} className="text-[10.5px] text-slate-500">
                {u}: no removals
              </div>
            ))}
        </div>
        <div className="rounded-md border border-ink-600 p-2">
          <div className="mb-1 text-[11px] font-semibold text-slate-300">
            Binary ({csp.constraints.binary}) - AC-3 {ac3Counts.length ? ac3Counts.map(([k, n]) => `${k} −${n}`).join(', ') : 'found all arcs consistent'}
          </div>
          <div className="mb-1 mt-2 text-[11px] font-semibold text-slate-300">Global capacity constraints</div>
          <ul className="space-y-0.5">
            {csp.constraints.global.slice(0, 14).map((g) => (
              <li key={g.name} className="text-[10.5px] text-slate-400">
                <span className="font-mono text-slate-300">{g.name}</span> ≤ {g.capacity}
              </li>
            ))}
          </ul>
        </div>
      </div>
      {csp.failure_reason && <div className="mt-2 text-[11px] text-red-300">Failure: {csp.failure_reason}</div>}
    </div>
  )
}

function Stage({ title, value, sub }: { title: string; value: string; sub: string }) {
  return (
    <div className="rounded-md border border-ink-600 bg-ink-800 px-2 py-1.5">
      <div className="text-[9.5px] font-bold uppercase tracking-wide text-violet-300">{title}</div>
      <div className="font-mono text-[13px] font-semibold text-slate-100">{value}</div>
      <div className="text-[10px] leading-tight text-slate-500">{sub}</div>
    </div>
  )
}

function Bar({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div className="mb-0.5 flex items-center gap-2 text-[10.5px]" title={`${label}: ${value} values removed`}>
      <span className="w-32 shrink-0 truncate font-mono text-slate-300">{label}</span>
      <span className="h-2 flex-1 rounded-sm bg-ink-700">
        <span className="block h-2 rounded-r-[4px] bg-violet-500" style={{ width: `${(value / Math.max(1, max)) * 100}%` }} />
      </span>
      <span className="w-8 text-right font-mono text-slate-400">−{value}</span>
    </div>
  )
}

export function Empty({ text }: { text: string }) {
  return <div className="flex h-full items-center justify-center p-6 text-center text-[12px] text-slate-500">{text}</div>
}
