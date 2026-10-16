import { useEffect, useMemo, useRef, useState } from 'react'
import { LEVEL_DOT, LEVEL_STYLE, PHASE_LABEL } from '../simulation/theme'
import type { LogEntry } from '../types/api'

const FILTERS: { id: string; label: string; match: (e: LogEntry) => boolean }[] = [
  { id: 'all', label: 'All', match: () => true },
  { id: 'alerts', label: 'Events & alerts', match: (e) => ['ALERT', 'EVENT', 'REPLAN'].includes(e.level) },
  { id: 'decisions', label: 'Decisions', match: (e) => e.level === 'DECISION' || e.level === 'SUCCESS' },
  { id: 'search', label: 'Search', match: (e) => e.level === 'SEARCH' },
  { id: 'csp', label: 'CSP', match: (e) => e.level === 'CSP' },
]

export function DecisionLog({ log }: { log: LogEntry[] }) {
  const [filter, setFilter] = useState('all')
  const [follow, setFollow] = useState(true)
  const [open, setOpen] = useState<Set<number>>(new Set())
  const scrollRef = useRef<HTMLDivElement>(null)
  const visible = useMemo(() => {
    const f = FILTERS.find((x) => x.id === filter) ?? FILTERS[0]
    return log.filter(f.match).slice(-600)
  }, [log, filter])

  useEffect(() => {
    const el = scrollRef.current
    if (el && follow) el.scrollTop = el.scrollHeight
  }, [visible, follow])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-ink-600 px-3 py-2">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            className={`chip border ${filter === f.id ? 'border-cyan-500 bg-cyan-950 text-cyan-200' : 'border-ink-500 text-slate-400 hover:text-slate-200'}`}
            onClick={() => setFilter(f.id)}
          >
            {f.label}
          </button>
        ))}
        <label className="ml-auto flex items-center gap-1.5 text-[11px] text-slate-400">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} className="accent-cyan-500" />
          Follow
        </label>
      </div>
      <div
        ref={scrollRef}
        className="scroll-thin min-h-0 flex-1 overflow-y-auto px-2 py-1.5 font-mono text-[11.5px] leading-snug"
        onWheel={(e) => {
          if (e.deltaY < 0) setFollow(false)
        }}
      >
        {visible.length === 0 && <div className="p-4 text-center text-slate-500">No entries yet. Press Play or Step.</div>}
        {visible.map((e) => {
          const expanded = open.has(e.seq)
          const isHeadline = e.message === 'ENVIRONMENT CHANGE DETECTED'
          return (
            <div
              key={e.seq}
              className={`group rounded px-1.5 py-[3px] hover:bg-ink-700/60 ${isHeadline ? 'my-0.5 border border-red-700/70 bg-red-950/40' : ''}`}
            >
              <button
                className="flex w-full items-start gap-2 text-left"
                onClick={() =>
                  e.details.length &&
                  setOpen((s) => {
                    const n = new Set(s)
                    if (n.has(e.seq)) n.delete(e.seq)
                    else n.add(e.seq)
                    return n
                  })
                }
              >
                <span className="shrink-0 text-slate-500">[{e.time}]</span>
                <span className="w-9 shrink-0 text-right text-slate-500">t{e.tick}</span>
                <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${LEVEL_DOT[e.level]}`} />
                <span className="w-[86px] shrink-0 truncate text-[10px] uppercase tracking-wide text-slate-500">
                  {PHASE_LABEL[e.phase] ?? e.phase}
                </span>
                <span className={`min-w-0 flex-1 ${isHeadline ? 'font-bold text-red-300' : LEVEL_STYLE[e.level]}`}>
                  {e.message}
                  {e.details.length > 0 && <span className="ml-1 text-slate-600">{expanded ? '▾' : `▸ ${e.details.length}`}</span>}
                </span>
              </button>
              {expanded && (
                <ul className="mb-1 ml-[178px] mt-0.5 space-y-0.5 border-l border-ink-500 pl-2 text-slate-400">
                  {e.details.map((d, i) => (
                    <li key={i}>{d}</li>
                  ))}
                </ul>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
