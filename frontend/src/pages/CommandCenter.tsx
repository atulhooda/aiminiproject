import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlgorithmInfo, DisasterEvents, PlaybackControls, type ArmedEvent } from '../components/ControlBar'
import { CspPanel } from '../components/CspPanel'
import { DecisionLog } from '../components/DecisionLog'
import { MapCanvas } from '../components/MapCanvas'
import { MissionTree } from '../components/MissionTree'
import { CellInspector, CustomScenarioDialog, FinalReport, ReactionBanner } from '../components/Overlays'
import { SearchPanel, StatePanel } from '../components/SearchPanel'
import { HospitalPanel, ResourcePanel, StatsPanel, VictimPanel } from '../components/SidePanels'
import { ActivityFeed, CompactCycle, CompactLegend, KeyStats, SimpleControls } from '../components/SimpleView'
import { AgentCycle, MissionStatusBar } from '../components/StatusBar'
import type { CenterTab, DemoController } from '../hooks/useDemoMode'
import type { SimController } from '../hooks/useSimulation'
import type { Overlays } from '../simulation/renderer'
import { SEVERITY_COLOR } from '../simulation/theme'
import type { Meta, Pos } from '../types/api'

export type CommandView = 'simple' | 'advanced'

// The simple view keeps the map uncluttered: routes and labels, no search heat-map.
const SIMPLE_OVERLAYS: Overlays = { paths: true, search: false, danger: false, unknown: true, labels: true }

const TABS: { id: CenterTab; label: string }[] = [
  { id: 'log', label: 'Decision log' },
  { id: 'plan', label: 'Mission plan (HTN)' },
  { id: 'csp', label: 'CSP solver' },
  { id: 'search', label: 'Search' },
  { id: 'state', label: 'State' },
]

interface Props {
  view: CommandView
  sim: SimController
  meta: Meta | null
  demo: DemoController
  tab: CenterTab
  setTab: (t: CenterTab) => void
  selectedVictim: string | null
  setSelectedVictim: (id: string | null) => void
}

export function CommandCenter({ view, sim, meta, demo, tab, setTab, selectedVictim, setSelectedVictim }: Props) {
  const snap = sim.snap
  const [overlays, setOverlays] = useState<Overlays>({ paths: true, search: true, danger: false, unknown: true, labels: true })
  const [hover, setHover] = useState<Pos | null>(null)
  const [pickMode, setPickMode] = useState(false)
  const [armed, setArmed] = useState<ArmedEvent | null>(null)
  const [brush, setBrush] = useState<string | null>(null)
  const [severity, setSeverity] = useState('CRITICAL')
  const [ambulance, setAmbulance] = useState('')
  const [hospital, setHospital] = useState('')
  const [scenario, setScenario] = useState('EARTHQUAKE')
  const [showCustom, setShowCustom] = useState(false)
  const [reportClosed, setReportClosed] = useState<string | null>(null)

  useEffect(() => {
    if (snap && !demo.active && !['DEMO', 'CUSTOM'].includes(snap.scenario.id)) setScenario(snap.scenario.id)
  }, [snap?.scenario.id, demo.active, snap])

  // Map placement tools only exist in the advanced view.
  useEffect(() => {
    if (view === 'simple') {
      setArmed(null)
      setBrush(null)
    }
  }, [view])

  // The mission report appears once per finished run, until closed.
  const runKey = snap ? `${snap.session_id}:${snap.tick}` : ''
  const finished = snap?.status === 'COMPLETE'

  const onCellClick = useCallback(
    (pos: Pos) => {
      if (!snap) return
      if (armed) {
        void sim.trigger(armed.type, pos, armed.params).then((r) => {
          if (r) setArmed(null)
        })
        return
      }
      if (brush) {
        void sim.trigger('SET_CELL', pos, { cell_type: brush })
        return
      }
      const v = snap.victims.find((x) => x.pos[0] === pos[0] && x.pos[1] === pos[1] && x.reported && !['RESCUED', 'DECEASED'].includes(x.status))
      setSelectedVictim(v ? v.id : null)
    },
    [snap, armed, brush, sim, setSelectedVictim],
  )

  const onHover = useCallback((p: Pos | null) => setHover(p), [])
  const dismissReaction = sim.dismissReaction
  const closeReaction = useCallback(() => dismissReaction(), [dismissReaction])

  const placementLabel = armed ? `Click a cell: ${armed.label}` : null
  const legend = useMemo(
    () => [
      { swatch: <span className="h-2.5 w-3.5 rounded-sm bg-slate-300" />, label: 'Ambulance (colour = unit)' },
      { swatch: <span className="h-2.5 w-2.5 rotate-45 bg-slate-300" />, label: 'Rescue team: S urban SAR, F fire, W water' },
      { swatch: <span className="h-2.5 w-2.5 rounded-full" style={{ background: SEVERITY_COLOR.CRITICAL }} />, label: 'Victim (colour = severity)' },
      { swatch: <span className="h-2.5 w-2.5 rounded-sm bg-blue-700" />, label: 'Hospital' },
      { swatch: <span className="h-2.5 w-2.5 rounded-sm bg-indigo-600" />, label: 'Rescue base' },
      { swatch: <span className="h-2.5 w-2.5 rounded-sm bg-green-900 ring-1 ring-green-400" />, label: 'Safe zone' },
      { swatch: <span className="h-2.5 w-2.5 rounded-sm bg-orange-600" />, label: 'Fire' },
      { swatch: <span className="h-2.5 w-2.5 rounded-sm bg-sky-800" />, label: 'Flood water' },
      { swatch: <span className="h-2.5 w-2.5 rounded-sm bg-[repeating-linear-gradient(45deg,#eab308_0_2px,#1f1a0a_2px_4px)]" />, label: 'Debris / blocked road' },
      { swatch: <span className="h-2.5 w-2.5 rounded-sm border border-dashed border-amber-400" />, label: 'Hazard unknown to agent' },
    ],
    [],
  )

  if (!snap) {
    return (
      <div className="flex flex-1 items-center justify-center text-slate-400">
        {sim.error ? <span className="text-red-300">{sim.error}</span> : 'Connecting to the AI engine…'}
      </div>
    )
  }

  const loadScenario = () => (scenario === 'CUSTOM' ? setShowCustom(true) : void sim.create(scenario, snap.algorithm))
  const mapCanvas = (
    <MapCanvas
      snap={snap}
      anim={sim.anim}
      colors={sim.colors}
      overlays={view === 'simple' ? SIMPLE_OVERLAYS : overlays}
      placementLabel={placementLabel}
      selectedVictim={selectedVictim}
      painting={brush !== null}
      onCellClick={onCellClick}
      onCellHover={onHover}
    >
      <ReactionBanner reaction={sim.reaction} onClose={closeReaction} />
      <CellInspector snap={snap} pos={hover} />
      {demo.caption && <DemoCaption demo={demo} />}
    </MapCanvas>
  )
  const dialogs = (
    <>
      <KeyHandler onEscape={() => { setArmed(null); setBrush(null) }} />
      {showCustom && (
        <CustomScenarioDialog
          onClose={() => setShowCustom(false)}
          onCreate={(cfg) => {
            setShowCustom(false)
            void sim.create('CUSTOM', snap.algorithm, cfg)
          }}
        />
      )}
      {finished && reportClosed !== runKey && (
        <FinalReport snap={snap} demo={snap.scenario.id === 'DEMO'} onClose={() => setReportClosed(runKey)} />
      )}
    </>
  )

  if (view === 'simple') {
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-2 p-2">
        <MissionStatusBar snap={snap} playing={sim.playing} compact />
        <CompactCycle snap={snap} />
        <div className="grid min-h-[520px] flex-1 gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(340px,400px)]">
          <section className="panel relative flex min-h-[420px] flex-col p-2">
            <div className="relative min-h-0 flex-1">{mapCanvas}</div>
            <CompactLegend />
          </section>
          <aside className="flex min-h-0 flex-col gap-2">
            <KeyStats snap={snap} />
            <ActivityFeed log={sim.log} />
            <div className="scroll-thin max-h-[40%] shrink-0 overflow-y-auto">
              <VictimPanel snap={snap} selected={selectedVictim} onSelect={setSelectedVictim} />
            </div>
          </aside>
        </div>
        <SimpleControls sim={sim} snap={snap} meta={meta} scenario={scenario} onScenario={setScenario} onLoad={loadScenario} locked={demo.active} />
        {dialogs}
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 p-2">
      <div className="grid gap-2 2xl:grid-cols-[minmax(560px,auto)_1fr]">
        <MissionStatusBar snap={snap} playing={sim.playing} />
        <AgentCycle snap={snap} />
      </div>

      <div className="grid min-h-[560px] flex-1 gap-2 lg:grid-cols-[minmax(0,1.15fr)_minmax(360px,1fr)_minmax(300px,330px)]">
        {/* LEFT: disaster map */}
        <section className="panel relative flex min-h-[420px] flex-col p-2">
          <div className="flex items-center gap-2 px-1 pb-1">
            <span className="panel-title">Disaster zone · {snap.grid.rows}×{snap.grid.cols}</span>
            {placementLabel && <span className="chip border border-amber-500 text-amber-200">{placementLabel} · Esc to cancel</span>}
            {brush && <span className="chip border border-violet-500 text-violet-200">Painting {brush.toLowerCase()} - click or drag</span>}
            <span className="ml-auto text-[10.5px] text-slate-500">
              {snap.belief_diff.length > 0 && `${snap.belief_diff.length} hidden hazard(s) · `}hover a cell to inspect
            </span>
          </div>
          <div className="relative min-h-0 flex-1">{mapCanvas}</div>
          <div className="flex flex-wrap gap-x-3 gap-y-1 px-1 pt-1.5 text-[10.5px] text-slate-400">
            {legend.map((l) => (
              <span key={l.label} className="flex items-center gap-1.5">
                {l.swatch}
                {l.label}
              </span>
            ))}
          </div>
        </section>

        {/* CENTER: decision log / mission timeline */}
        <section className="panel flex min-h-[420px] min-w-0 flex-col">
          <div className="flex gap-0.5 overflow-x-auto border-b border-ink-600 px-2 pt-2" role="tablist">
            {TABS.map((t) => (
              <button
                key={t.id}
                role="tab"
                aria-selected={tab === t.id}
                className={`whitespace-nowrap rounded-t-md px-3 py-1.5 text-[11.5px] font-semibold ${tab === t.id ? 'bg-ink-700 text-cyan-200' : 'text-slate-400 hover:text-slate-200'}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1">
            {tab === 'log' && <DecisionLog log={sim.log} />}
            {tab === 'plan' && <MissionTree root={snap.mission_tree} />}
            {tab === 'csp' && <CspPanel csp={snap.last_csp} />}
            {tab === 'search' && <SearchPanel snap={snap} />}
            {tab === 'state' && <StatePanel snap={snap} />}
          </div>
        </section>

        {/* RIGHT: statistics */}
        <aside className="scroll-thin flex min-h-0 flex-col gap-2 overflow-y-auto lg:max-h-full">
          <StatsPanel snap={snap} />
          <HospitalPanel snap={snap} />
          <VictimPanel snap={snap} selected={selectedVictim} onSelect={setSelectedVictim} />
          <ResourcePanel snap={snap} colors={sim.colors} />
        </aside>
      </div>

      {/* BOTTOM: controls & algorithm info */}
      <div className="grid gap-2 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.25fr)_minmax(220px,0.55fr)]">
        <PlaybackControls
          sim={sim}
          snap={snap}
          meta={meta}
          scenario={scenario}
          onScenario={setScenario}
          onLoad={loadScenario}
          onCustom={loadScenario}
          overlays={overlays}
          onOverlays={setOverlays}
          locked={demo.active}
        />
        <DisasterEvents
          sim={sim}
          snap={snap}
          pickMode={pickMode}
          onPickMode={(v) => {
            setPickMode(v)
            setArmed(null)
          }}
          armed={armed}
          onArm={setArmed}
          brush={brush}
          onBrush={setBrush}
          severity={severity}
          onSeverity={setSeverity}
          ambulance={ambulance}
          onAmbulance={setAmbulance}
          hospital={hospital}
          onHospital={setHospital}
          locked={demo.active}
        />
        <AlgorithmInfo snap={snap} />
      </div>

      {dialogs}
    </div>
  )
}

function DemoCaption({ demo }: { demo: DemoController }) {
  const c = demo.caption!
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const iv = setInterval(() => setNow(Date.now()), 100)
    return () => clearInterval(iv)
  }, [])
  const pct = c.holdMs ? Math.min(100, ((now - c.shownAt) / c.holdMs) * 100) : 100
  return (
    <div className="fixed bottom-4 left-1/2 z-40 w-[min(760px,94vw)] -translate-x-1/2 rounded-lg border border-cyan-700 bg-ink-950/95 p-3.5 shadow-2xl backdrop-blur">
      <div className="flex items-center gap-2">
        <span className="chip border border-cyan-500 bg-cyan-950 text-cyan-200">DEMO {c.step}/{c.total}</span>
        <span className="text-[13.5px] font-semibold text-slate-100">{c.title}</span>
        <div className="ml-auto flex gap-1">
          {demo.active ? (
            <button className="btn px-2 py-0.5 text-[11px]" onClick={demo.stop}>
              Exit demo
            </button>
          ) : (
            <button className="btn px-2 py-0.5 text-[11px]" onClick={demo.dismissCaption}>
              Close
            </button>
          )}
        </div>
      </div>
      <p className="mt-1.5 text-[12.5px] leading-relaxed text-slate-300">{c.body}</p>
      <div className="mt-2 h-1 overflow-hidden rounded bg-ink-600">
        <div className="h-1 bg-cyan-500 transition-[width] duration-100" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function KeyHandler({ onEscape }: { onEscape: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onEscape()
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onEscape])
  return null
}
