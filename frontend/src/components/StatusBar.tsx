import { PHASES, PHASE_LABEL, PHASE_SHORT } from '../simulation/theme'
import type { Snapshot } from '../types/api'

const STATUS_STYLE: Record<string, string> = {
  READY: 'bg-slate-700/60 text-slate-200 border-slate-500',
  RUNNING: 'bg-emerald-900/50 text-emerald-200 border-emerald-500',
  COMPLETE: 'bg-sky-900/50 text-sky-200 border-sky-500',
  STALLED: 'bg-amber-900/50 text-amber-200 border-amber-500',
}

const AI_STATE_STYLE: Record<string, string> = {
  REPLANNING: 'text-amber-300',
  'ALLOCATING RESOURCES': 'text-violet-300',
  'EXECUTING PLAN': 'text-emerald-300',
  'AWAITING RESOURCES': 'text-orange-300',
  'GOALS SATISFIED': 'text-sky-300',
  STANDBY: 'text-slate-300',
}

export function MissionStatusBar({ snap, playing, compact }: { snap: Snapshot; playing: boolean; compact?: boolean }) {
  const s = snap.stats
  const next = snap.upcoming_events[0]
  return (
    <div className="panel flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5">
      <div className="min-w-0">
        <div className="panel-title">Mission</div>
        <div className="truncate text-sm font-semibold text-slate-100">{snap.scenario.name}</div>
      </div>
      <span className={`chip border ${STATUS_STYLE[snap.status]}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${snap.status === 'RUNNING' && playing ? 'animate-pulse bg-emerald-400' : 'bg-current'}`} />
        {snap.status === 'RUNNING' && !playing ? 'PAUSED' : snap.status}
      </span>
      <Metric label="Tick" value={String(snap.tick)} mono />
      <Metric label="AI state" value={s.ai_state} className={AI_STATE_STYLE[s.ai_state] ?? 'text-slate-200'} />
      {!compact && (
        <>
          <Metric label="Rescued" value={`${s.rescued_victims} / ${s.total_victims}`} />
          <Metric label="Critical active" value={String(s.critical_victims)} className={s.critical_victims ? 'text-red-300' : ''} />
          <Metric label="Replans" value={String(s.replanning_count)} className={s.replanning_count ? 'text-amber-300' : ''} />
        </>
      )}
      <div className="ml-auto flex min-w-0 items-center gap-4">
        {next && snap.status !== 'COMPLETE' && (
          <div className="hidden text-right xl:block">
            <div className="panel-title">Scripted event</div>
            <div className="text-xs text-slate-300">
              t={next.tick} · {next.label ?? next.type.replaceAll('_', ' ').toLowerCase()}
            </div>
          </div>
        )}
        {snap.end_reason && snap.status !== 'RUNNING' && (
          <div className="max-w-72 truncate text-xs text-slate-400" title={snap.end_reason}>
            {snap.end_reason}
          </div>
        )}
      </div>
    </div>
  )
}

function Metric({ label, value, mono, className = '' }: { label: string; value: string; mono?: boolean; className?: string }) {
  return (
    <div>
      <div className="panel-title">{label}</div>
      <div className={`text-sm font-semibold text-slate-100 ${mono ? 'font-mono' : ''} ${className}`}>{value}</div>
    </div>
  )
}

export function AgentCycle({ snap }: { snap: Snapshot }) {
  const trace = new Map(snap.phase_trace.map((p) => [p.phase, p.summary]))
  const reacting = snap.phase_trace.length > 0 && !trace.has('EXECUTE')
  return (
    <div className="panel @container px-3 py-2">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="panel-title">Agent decision cycle · tick {snap.tick}</span>
        <span className="text-[10px] text-slate-500">
          {reacting ? 'reactive cycle (event injected between ticks)' : 'perceive → act → observe, every tick'}
        </span>
      </div>
      <ol className="grid grid-cols-4 gap-1 @[760px]:grid-cols-8">
        {PHASES.map((phase, i) => {
          const summary = trace.get(phase)
          const ran = summary !== undefined
          return (
            <li
              key={`${phase}-${snap.tick}-${snap.log_seq}`}
              className={`min-w-0 rounded-md border px-2 py-1 ${ran ? 'phase-active border-cyan-700/70' : 'border-ink-600 opacity-45'}`}
              style={{ animationDelay: `${i * 70}ms` }}
              title={`${PHASE_LABEL[phase]}: ${summary ?? 'not run in this cycle'}`}
            >
              <div className="flex items-center gap-1 text-[11px] font-semibold text-cyan-200">
                <span className="text-cyan-500/80">{i + 1}</span>
                <span className="truncate">{PHASE_SHORT[phase]}</span>
              </div>
              <div className="truncate text-[10.5px] leading-tight text-slate-300">{summary ?? '-'}</div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
