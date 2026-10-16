import { useState } from 'react'
import type { PlanTaskNode } from '../types/api'

const STATUS_ICON: Record<string, { icon: string; cls: string }> = {
  DONE: { icon: '✓', cls: 'text-emerald-400' },
  ACTIVE: { icon: '▶', cls: 'text-cyan-300' },
  PENDING: { icon: '○', cls: 'text-slate-500' },
  CANCELLED: { icon: '✗', cls: 'text-slate-500' },
}

export function MissionTree({ root }: { root: PlanTaskNode }) {
  const [hideDone, setHideDone] = useState(false)
  const missions = root.children.filter((c) => c.kind === 'RESCUE_VICTIM')
  const shown = hideDone ? missions.filter((m) => m.status === 'ACTIVE' || m.status === 'PENDING') : missions
  const meta = root.children.filter((c) => c.kind !== 'RESCUE_VICTIM')
  const active = missions.filter((m) => m.status === 'ACTIVE').length
  const done = missions.filter((m) => m.status === 'DONE').length
  const aborted = missions.filter((m) => m.status === 'CANCELLED').length

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-3 border-b border-ink-600 px-3 py-2 text-[11px] text-slate-400">
        <span>
          <b className="text-cyan-300">{active}</b> active · <b className="text-emerald-300">{done}</b> completed ·{' '}
          <b className="text-slate-300">{aborted}</b> re-planned
        </span>
        <label className="ml-auto flex items-center gap-1.5">
          <input type="checkbox" checked={hideDone} onChange={(e) => setHideDone(e.target.checked)} className="accent-cyan-500" />
          Hide finished
        </label>
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-3 py-2 font-mono text-[11.5px]">
        <div className="mb-1 font-bold text-slate-100">
          <span className={STATUS_ICON[root.status].cls}>{STATUS_ICON[root.status].icon}</span> {root.label}
        </div>
        <div className="ml-1 border-l border-ink-500 pl-3">
          {meta.slice(0, 1).map((t) => (
            <Row key={t.id} node={t} />
          ))}
          {shown.map((m) => (
            <MissionNode key={m.id} node={m} />
          ))}
          {shown.length === 0 && <div className="py-2 text-slate-500">No rescue missions yet - press Step to run the first decision cycle.</div>}
          {meta.slice(1).map((t) => (
            <Row key={t.id} node={t} />
          ))}
        </div>
      </div>
    </div>
  )
}

function MissionNode({ node }: { node: PlanTaskNode }) {
  const [open, setOpen] = useState(node.status === 'ACTIVE')
  const s = STATUS_ICON[node.status]
  return (
    <div className="my-1">
      <button className="flex w-full items-center gap-1.5 text-left hover:text-white" onClick={() => setOpen(!open)}>
        <span className="text-slate-500">{open ? '▾' : '▸'}</span>
        <span className={s.cls}>{s.icon}</span>
        <span className={`font-semibold ${node.status === 'CANCELLED' ? 'text-slate-500 line-through' : 'text-slate-100'}`}>{node.label}</span>
        <span className="truncate text-[10.5px] text-slate-500">{node.note}</span>
      </button>
      {open && (
        <div className="ml-[7px] border-l border-ink-500 pl-3">
          {node.children.map((c) => (
            <Row key={c.id} node={c} />
          ))}
        </div>
      )}
    </div>
  )
}

function Row({ node }: { node: PlanTaskNode }) {
  const s = STATUS_ICON[node.status]
  const moving = node.kind === 'NAVIGATE' || node.kind === 'TRANSPORT'
  const onScene = node.kind === 'EXTRACT' || node.kind === 'RESCUE'
  return (
    <div className={`flex items-baseline gap-1.5 py-[1px] ${node.status === 'ACTIVE' ? 'rounded bg-cyan-950/40' : ''}`}>
      <span className="text-slate-600">├─</span>
      <span className={s.cls}>{s.icon}</span>
      <span className={node.status === 'CANCELLED' ? 'text-slate-500 line-through' : node.status === 'DONE' ? 'text-slate-400' : 'text-slate-200'}>
        {node.label}
      </span>
      {moving && node.steps !== undefined && (
        <span className="text-[10.5px] text-slate-500">
          {node.algorithm} · {node.steps} steps · cost {node.path_cost?.toFixed(1)}
        </span>
      )}
      {onScene && node.status === 'ACTIVE' && (
        <span className="text-[10.5px] text-cyan-300">
          {node.progress}/{node.duration} ticks
        </span>
      )}
      {node.replans > 0 && <span className="chip border border-amber-600 text-amber-300">↻ replanned ×{node.replans}</span>}
      {node.shared && <span className="chip border border-ink-500 text-slate-400">shared trip</span>}
      {!moving && !onScene && node.note && <span className="truncate text-[10.5px] text-slate-500">{node.note}</span>}
    </div>
  )
}
