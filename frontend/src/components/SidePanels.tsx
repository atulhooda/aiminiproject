import { useState } from 'react'
import { CAPABILITY_GLYPH, SEVERITY_COLOR, SEVERITY_RANK } from '../simulation/theme'
import type { Snapshot, Unit, Victim } from '../types/api'

export function StatsPanel({ snap }: { snap: Snapshot }) {
  const s = snap.stats
  const a = s.agent
  return (
    <section className="panel shrink-0 p-3">
      <div className="panel-title mb-2">System statistics</div>
      <div className="grid grid-cols-3 gap-1.5">
        <Tile label="Active victims" value={s.active_victims} />
        <Tile label="Rescued" value={s.rescued_victims} tone="good" />
        <Tile label="Critical" value={s.critical_victims} tone={s.critical_victims ? 'bad' : undefined} />
        <Tile label="Ambulances" value={`${s.active_ambulances}/${s.available_ambulances}`} sub="busy / available" hint={`${s.total_ambulances - s.available_ambulances} out of service`} />
        <Tile label="Rescue teams" value={`${s.active_teams}/${s.available_teams}`} sub="busy / available" />
        <Tile label="Replans" value={s.replanning_count} tone={s.replanning_count ? 'warn' : undefined} />
        <Tile label="Distance" value={s.total_distance} sub="cells travelled" />
        <Tile label="Rescue time" value={s.total_rescue_time} sub={s.avg_rescue_time != null ? `avg ${s.avg_rescue_time} / victim` : 'ticks, total'} />
        <Tile label="Deceased" value={s.deceased_victims} tone={s.deceased_victims ? 'bad' : undefined} />
      </div>
      <div className="mt-2 rounded-md border border-ink-600 bg-ink-850 px-2 py-1.5">
        <div className="text-[9.5px] uppercase tracking-wide text-slate-500">Current mission</div>
        <div className="text-[11.5px] leading-snug text-slate-200">{s.current_mission ?? 'none - awaiting tasks'}</div>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono text-[10.5px] text-slate-400">
        <span>searches {a.searches}</span>
        <span>nodes {a.nodes_expanded.toLocaleString()}</span>
        <span>CSP runs {a.csp_runs}</span>
        <span>CSP nodes {a.csp_nodes.toLocaleString()}</span>
        <span>hazards found {a.hazards_discovered}</span>
        <span>re-assignments {a.reassignments}</span>
      </div>
    </section>
  )
}

function Tile({ label, value, tone, hint, sub }: { label: string; value: number | string; tone?: 'good' | 'bad' | 'warn'; hint?: string; sub?: string }) {
  const color = tone === 'good' ? 'text-emerald-300' : tone === 'bad' ? 'text-red-300' : tone === 'warn' ? 'text-amber-300' : 'text-slate-100'
  return (
    <div className="rounded-md border border-ink-600 bg-ink-850 px-2 py-1.5" title={hint}>
      <div className="truncate text-[9.5px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-[17px] font-semibold leading-tight ${color}`}>{value}</div>
      {sub && <div className="truncate text-[9.5px] text-slate-500">{sub}</div>}
    </div>
  )
}

export function HospitalPanel({ snap }: { snap: Snapshot }) {
  return (
    <section className="panel shrink-0 p-3">
      <div className="panel-title mb-2">Hospital capacity</div>
      <div className="space-y-2">
        {snap.hospitals.map((h) => (
          <div key={h.id}>
            <div className="flex items-baseline justify-between text-[11.5px]">
              <span className="font-semibold text-slate-200">
                {h.id} <span className="font-normal text-slate-400">{h.name}</span>
              </span>
              {(h.inbound_er > 0 || h.inbound_icu > 0) && (
                <span className="text-[10.5px] text-cyan-300">
                  {h.inbound_er + h.inbound_icu} inbound
                </span>
              )}
            </div>
            <Meter label="ER" used={h.er_occupancy} inbound={h.inbound_er} cap={h.er_capacity} />
            <Meter label="ICU" used={h.icu_occupancy} inbound={h.inbound_icu} cap={h.icu_capacity} />
          </div>
        ))}
      </div>
    </section>
  )
}

function Meter({ label, used, inbound, cap }: { label: string; used: number; inbound: number; cap: number }) {
  const pct = (n: number) => `${cap ? Math.min(100, (n / cap) * 100) : 0}%`
  const full = used + inbound >= cap
  return (
    <div className="mt-0.5 flex items-center gap-2" title={`${label}: ${used} occupied, ${inbound} reserved for inbound patients, capacity ${cap}`}>
      <span className="w-7 text-[10px] text-slate-500">{label}</span>
      <div className="relative h-2 flex-1 overflow-hidden rounded-sm bg-sky-950">
        <div className="absolute inset-y-0 left-0 bg-sky-500" style={{ width: pct(used) }} />
        <div className="absolute inset-y-0 bg-sky-500/40" style={{ left: pct(used), width: pct(inbound) }} />
      </div>
      <span className={`w-12 text-right font-mono text-[10.5px] ${full ? 'text-amber-300' : 'text-slate-400'}`}>
        {used}+{inbound}/{cap}
      </span>
    </div>
  )
}

const STATUS_LABEL: Record<string, string> = {
  WAITING: 'waiting',
  ASSIGNED: 'units en route',
  BEING_RESCUED: 'on-scene rescue',
  IN_TRANSIT: 'in transit',
  RESCUED: 'rescued',
  DECEASED: 'deceased',
}

export function VictimPanel({ snap, selected, onSelect }: { snap: Snapshot; selected: string | null; onSelect: (id: string | null) => void }) {
  const [showDone, setShowDone] = useState(false)
  const victims = snap.victims
    .filter((v) => v.reported && (showDone || !['RESCUED', 'DECEASED'].includes(v.status)))
    .sort((a, b) => {
      const activeA = ['RESCUED', 'DECEASED'].includes(a.status) ? 1 : 0
      const activeB = ['RESCUED', 'DECEASED'].includes(b.status) ? 1 : 0
      return activeA - activeB || b.priority - a.priority || SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity]
    })
  return (
    <section className="panel flex shrink-0 flex-col p-3">
      <div className="mb-2 flex items-center">
        <span className="panel-title">Victims by priority</span>
        <label className="ml-auto flex items-center gap-1 text-[10.5px] text-slate-400">
          <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} className="accent-cyan-500" />
          show resolved
        </label>
      </div>
      <div className="space-y-1">
        {victims.length === 0 && <div className="text-[11.5px] text-slate-500">No active victims.</div>}
        {victims.map((v) => (
          <VictimRow key={v.id} v={v} open={selected === v.id} onToggle={() => onSelect(selected === v.id ? null : v.id)} />
        ))}
      </div>
    </section>
  )
}

function VictimRow({ v, open, onToggle }: { v: Victim; open: boolean; onToggle: () => void }) {
  const max = Math.max(1, ...v.priority_breakdown.map((f) => f.points))
  const done = v.status === 'RESCUED' || v.status === 'DECEASED'
  return (
    <div className={`rounded-md border ${open ? 'border-cyan-700 bg-ink-750' : 'border-ink-600 bg-ink-850'} ${done ? 'opacity-55' : ''}`}>
      <button className="flex w-full items-center gap-2 px-2 py-1.5 text-left" onClick={onToggle}>
        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: SEVERITY_COLOR[v.severity] }} />
        <span className="w-8 font-mono text-[12px] font-semibold text-slate-100">{v.id}</span>
        <span className="w-16 text-[10px] font-bold tracking-wide text-slate-300">{v.severity}</span>
        <span className="min-w-0 flex-1">
          <span className="block h-1.5 overflow-hidden rounded-sm bg-ink-600">
            <span
              className="block h-1.5"
              style={{ width: `${v.health}%`, background: v.health > 50 ? '#22c55e' : v.health > 25 ? '#eab308' : '#ef4444' }}
            />
          </span>
          <span className="text-[10px] text-slate-500">
            {v.health.toFixed(0)}% · {STATUS_LABEL[v.status] ?? v.status}
            {v.trapped && !v.extracted ? ' · trapped' : ''}
          </span>
        </span>
        <span className="w-10 text-right font-mono text-[12.5px] font-semibold text-cyan-200" title="priority score">
          {done ? '-' : v.priority.toFixed(0)}
        </span>
      </button>
      {open && (
        <div className="border-t border-ink-600 px-2 pb-2 pt-1.5">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Why this priority ({v.priority.toFixed(1)})</div>
          {v.priority_breakdown.map((f) => (
            <div key={f.factor} className="mt-0.5 flex items-center gap-2 text-[10.5px]">
              <span className="w-24 shrink-0 text-slate-300">{f.factor}</span>
              <span className="h-1.5 flex-1 rounded-sm bg-ink-700">
                <span className="block h-1.5 rounded-r-[4px] bg-cyan-500" style={{ width: `${(f.points / max) * 100}%` }} />
              </span>
              <span className="w-9 text-right font-mono text-slate-200">+{f.points}</span>
            </div>
          ))}
          <div className="mt-1 space-y-0.5 text-[10px] text-slate-500">
            {v.priority_breakdown.map((f) => (
              <div key={f.factor}>
                {f.factor}: {f.detail}
              </div>
            ))}
          </div>
          {v.required_resources.length > 0 && (
            <>
              <div className="mt-1.5 text-[10px] uppercase tracking-wide text-slate-500">Required resources</div>
              <div className="mt-0.5 flex flex-wrap gap-1">
                {v.required_resources.map((r) => (
                  <span key={r} className="chip border border-ink-500 text-slate-300">
                    {r}
                  </span>
                ))}
              </div>
            </>
          )}
          <div className="mt-1 font-mono text-[10px] text-slate-500">
            at ({v.pos.join(', ')}) · on-scene time {v.rescue_time} ticks
            {v.assigned_units.length > 0 && ` · assigned ${v.assigned_units.join(' + ')}`}
            {v.destination_id && ` → ${v.destination_id}`}
          </div>
        </div>
      )}
    </div>
  )
}

const UNIT_STATUS_STYLE: Record<string, string> = {
  IDLE: 'text-slate-400',
  EN_ROUTE: 'text-cyan-300',
  ON_SCENE: 'text-amber-300',
  TRANSPORTING: 'text-emerald-300',
  WAITING: 'text-violet-300',
  OUT_OF_SERVICE: 'text-red-400',
}

export function ResourcePanel({ snap, colors }: { snap: Snapshot; colors: Record<string, string> }) {
  const plans = new Map(snap.plans.map((p) => [p.unit_id, p]))
  const row = (u: Unit) => {
    const plan = plans.get(u.id)
    return (
      <div key={u.id} className="flex items-center gap-2 py-1 text-[11px]">
        <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: u.available ? colors[u.id] : '#475569' }} />
        <span className="w-7 font-mono font-semibold text-slate-100">{u.id}</span>
        <span className="w-9 text-[10px] text-slate-500" title={u.kind === 'AMBULANCE' ? `${u.medical} ambulance, ${u.capacity} seat(s)` : `${u.capability} team`}>
          {u.kind === 'AMBULANCE' ? `${u.medical}·${u.capacity}` : CAPABILITY_GLYPH[u.capability] + '-team'}
        </span>
        <span className={`w-[86px] shrink-0 text-[10px] font-semibold ${UNIT_STATUS_STYLE[u.status]}`}>{u.status.replaceAll('_', ' ')}</span>
        <span className="min-w-0 flex-1 truncate text-slate-400" title={plan?.current_task ?? ''}>
          {plan?.holding ? 'holding - no route' : plan?.waiting_for.length ? `waiting: ${plan.waiting_for[0]}` : plan?.current_task ?? '-'}
        </span>
      </div>
    )
  }
  return (
    <section className="panel shrink-0 p-3">
      <div className="panel-title mb-1">Resources</div>
      <div className="divide-y divide-ink-600">
        {snap.ambulances.map(row)}
        {snap.teams.map(row)}
      </div>
    </section>
  )
}
