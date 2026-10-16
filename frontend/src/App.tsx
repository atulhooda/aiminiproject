import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MapCanvas } from './components/MapCanvas'
import { useSimulation } from './hooks/useSimulation'
import type { Overlays } from './simulation/renderer'
import type { LogEntry, Pos } from './types/api'

// One scenario, one screen: the urban fire, planned by A*.
const SCENARIO = 'URBAN_FIRE'
const MAP_LAYERS: Overlays = { paths: true, search: false, danger: false, unknown: false, labels: true }

// Only the moments worth saying out loud: what happened, what the AI decided, the result.
function isKeyMoment(e: LogEntry): boolean {
  const m = e.message
  if (e.level === 'EVENT') return !m.includes('situation report')
  return (
    m === 'ENVIRONMENT CHANGE DETECTED' ||
    m.startsWith('Assign ') ||
    m.startsWith('New path generated') ||
    m.startsWith('Mission resumed') ||
    (m.startsWith('Victim ') && m.includes('delivered'))
  )
}

export default function App() {
  const sim = useSimulation()
  const snap = sim.snap
  const booted = useRef(false)
  const [, setHover] = useState<Pos | null>(null)

  useEffect(() => {
    if (booted.current) return
    booted.current = true
    sim.setSpeed(2)
    void sim.create(SCENARIO, 'ASTAR')
  }, [sim])

  const feed = useMemo(() => sim.log.filter(isKeyMoment).slice(-40), [sim.log])
  const feedRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = feedRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [feed])

  const onHover = useCallback((p: Pos | null) => setHover(p), [])
  const noop = useCallback(() => {}, [])

  if (!snap) {
    return <div className="flex h-full items-center justify-center text-slate-400">{sim.error ?? 'Starting…'}</div>
  }

  const s = snap.stats
  const done = snap.status === 'COMPLETE'
  const started = snap.status !== 'READY'

  return (
    <div className="mx-auto flex h-full max-w-[1400px] flex-col gap-3 p-4">
      <header>
        <h1 className="text-2xl font-bold text-slate-100">AI Fire Rescue Commander</h1>
        <p className="text-sm text-slate-400">
          A fire is spreading through the city. The AI decides who to save first, sends ambulances and fire teams, and finds safe roads with A*.
        </p>
      </header>

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section className="panel relative flex min-h-[460px] flex-col p-2">
          <div className="relative min-h-0 flex-1">
            <MapCanvas
              snap={snap}
              anim={sim.anim}
              colors={sim.colors}
              overlays={MAP_LAYERS}
              placementLabel={null}
              selectedVictim={null}
              painting={false}
              onCellClick={noop}
              onCellHover={onHover}
            />
            {done && (
              <div className="absolute inset-x-0 top-4 mx-auto w-fit rounded-lg border border-emerald-600 bg-ink-950/95 px-5 py-3 text-center text-emerald-200 shadow-xl">
                <div className="text-lg font-semibold">All {s.rescued_victims} victims rescued</div>
                <div className="text-sm text-slate-400">
                  in {snap.tick} steps · {s.replanning_count} replans · {s.deceased_victims} lost
                </div>
              </div>
            )}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 px-1 pt-2 text-xs text-slate-400">
            <span>▭ Ambulance</span>
            <span>◆ Rescue team</span>
            <span className="text-red-400">● Victim</span>
            <span className="text-blue-400">✚ Hospital</span>
            <span className="text-orange-400">■ Fire</span>
            <span>- - Planned route</span>
          </div>
        </section>

        <aside className="flex min-h-0 flex-col gap-3">
          <div className="grid grid-cols-3 gap-2">
            <Stat label="Rescued" value={`${s.rescued_victims}/${s.total_victims}`} tone="text-emerald-300" />
            <Stat label="Waiting" value={String(s.active_victims)} tone="text-slate-100" />
            <Stat label="Replans" value={String(s.replanning_count)} tone="text-amber-300" />
          </div>

          <div className="panel p-3 text-sm text-slate-300">
            <div className="panel-title mb-1">How the AI works</div>
            <ol className="list-decimal space-y-0.5 pl-5">
              <li><b>Sense</b> – see the fire, roads and victims</li>
              <li><b>Decide</b> – rank victims, assign units (CSP)</li>
              <li><b>Plan</b> – find the safest road (A* search)</li>
              <li><b>Act &amp; replan</b> – if fire blocks a road, plan again</li>
            </ol>
          </div>

          <div className="panel flex min-h-0 flex-1 flex-col p-3">
            <div className="panel-title mb-1.5">What the AI is doing</div>
            <div ref={feedRef} className="scroll-thin min-h-0 flex-1 space-y-1 overflow-y-auto text-[13px] leading-snug">
              {feed.length === 0 && <div className="py-6 text-center text-slate-500">Press Start.</div>}
              {feed.map((e) => (
                <div key={e.seq} className={lineColor(e)}>
                  <span className="mr-2 font-mono text-xs text-slate-500">t{e.tick}</span>
                  {plain(e.message)}
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>

      <footer className="panel flex flex-wrap items-center gap-2 p-3">
        {sim.playing ? (
          <button className="btn btn-active px-5" onClick={sim.pause}>❚❚ Pause</button>
        ) : (
          <button className="btn btn-primary px-5" onClick={sim.play} disabled={done}>▶ Start</button>
        )}
        <button className="btn" onClick={() => void sim.reset()}>↺ Restart</button>
        <span className="ml-4 text-sm text-slate-400">Make it harder:</span>
        <button className="btn btn-danger" disabled={!started || done} onClick={() => void sim.trigger('START_FIRE')}>
          🔥 Start a new fire
        </button>
        <button className="btn btn-danger" disabled={!started || done} onClick={() => void sim.trigger('BLOCK_ROAD')}>
          🚧 Block a road
        </button>
        {sim.error && <span className="ml-auto text-sm text-red-300">{sim.error}</span>}
      </footer>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="panel px-3 py-2">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-2xl font-semibold ${tone}`}>{value}</div>
    </div>
  )
}

function lineColor(e: LogEntry): string {
  if (e.message === 'ENVIRONMENT CHANGE DETECTED' || e.level === 'EVENT') return 'text-orange-300'
  if (e.message.startsWith('New path') || e.message.startsWith('Mission resumed')) return 'text-amber-300'
  if (e.message.includes('delivered')) return 'text-emerald-300'
  return 'text-sky-300'
}

// Turn the agent's log lines into sentences you can read out loud.
function plain(m: string): string {
  let r: RegExpMatchArray | null
  if ((r = m.match(/^Assign (\w+) \((\w+), priority [\d.]+\) -> (.*)$/))) {
    const [, victim, severity, plan] = r
    return `Send help to ${victim} (${severity.toLowerCase()}): ${plan.replace(/->/g, '→')}`
  }
  if ((r = m.match(/^New path generated for (\w+)/))) return `${r[1]} found a new safe road (A*)`
  if ((r = m.match(/^Mission resumed: \w+ - .*?(\w+) -> (\w+)$/))) return `${r[1]} is back on its way to ${r[2]}`
  if ((r = m.match(/^Mission resumed: \w+ - (.*)$/))) return `Back on plan: ${r[1]}`
  if ((r = m.match(/^Victim (\w+) delivered to (.*?) -/))) return `✓ ${r[1]} reached ${r[2]}`
  if (m === 'ENVIRONMENT CHANGE DETECTED') return 'Change detected - checking every route'
  return m.replace(/^\[\w+\] /, '')
}
