import { useEffect, useMemo, useRef, useState } from 'react'
import { useDemoMode, type CenterTab } from './hooks/useDemoMode'
import { useSimulation } from './hooks/useSimulation'
import { AlgorithmLab } from './pages/AlgorithmLab'
import { CommandCenter, type CommandView } from './pages/CommandCenter'
import { ConceptsPage } from './pages/ConceptsPage'
import { api } from './services/api'
import type { Meta } from './types/api'

type Page = 'command' | 'lab' | 'concepts'

const VIEW_KEY = 'drc.commandView'

function storedView(): CommandView {
  try {
    return localStorage.getItem(VIEW_KEY) === 'advanced' ? 'advanced' : 'simple'
  } catch {
    return 'simple'
  }
}

const PAGES: { id: Page; label: string }[] = [
  { id: 'command', label: 'Command Center' },
  { id: 'lab', label: 'Algorithm Lab' },
  { id: 'concepts', label: 'AI Concepts' },
]

export default function App() {
  const sim = useSimulation()
  const [meta, setMeta] = useState<Meta | null>(null)
  const [metaError, setMetaError] = useState<string | null>(null)
  const [page, setPage] = useState<Page>('command')
  const [view, setView] = useState<CommandView>(storedView)
  const changeView = (v: CommandView) => {
    setView(v)
    try {
      localStorage.setItem(VIEW_KEY, v)
    } catch {
      /* storage unavailable: the choice just won't be remembered */
    }
  }
  const [tab, setTab] = useState<CenterTab>('log')
  const [selectedVictim, setSelectedVictim] = useState<string | null>(null)
  const ui = useMemo(() => ({ setTab, selectVictim: setSelectedVictim }), [])
  const demo = useDemoMode(sim, ui)
  const booted = useRef(false)

  useEffect(() => {
    if (booted.current) return
    booted.current = true
    api
      .meta()
      .then(setMeta)
      .catch((e: Error) => setMetaError(e.message))
    void sim.create('EARTHQUAKE', 'ASTAR')
  }, [sim])

  const connected = meta !== null && !metaError

  return (
    <div className="flex h-full min-h-[880px] flex-col">
      <header className="flex items-center gap-4 border-b border-ink-600 bg-ink-950/80 px-4 py-2 backdrop-blur">
        <div className="flex items-center gap-2.5">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <div className="leading-tight">
            <div className="text-[14px] font-bold tracking-wide text-slate-100">AI Disaster Response Commander</div>
            <div className="text-[10.5px] text-slate-500">Intelligent agent for autonomous rescue planning · classical AI, no ML</div>
          </div>
        </div>
        <nav className="ml-4 flex gap-1" aria-label="Pages">
          {PAGES.map((p) => (
            <button
              key={p.id}
              className={`rounded-md px-3 py-1.5 text-[12.5px] font-semibold ${page === p.id ? 'bg-ink-700 text-cyan-200 ring-1 ring-cyan-800' : 'text-slate-400 hover:text-slate-100'}`}
              onClick={() => setPage(p.id)}
            >
              {p.label}
            </button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {page === 'command' && (
            <div className="flex overflow-hidden rounded-md border border-ink-500 text-[12px]" role="group" aria-label="Command Center view">
              {(['simple', 'advanced'] as const).map((v) => (
                <button
                  key={v}
                  className={`px-3 py-1.5 font-semibold ${view === v ? 'bg-cyan-900 text-cyan-50' : 'bg-ink-800 text-slate-400 hover:text-slate-100'}`}
                  onClick={() => changeView(v)}
                  title={v === 'simple' ? 'Map, key numbers and the main AI decisions' : 'Every detail: CSP, HTN tree, search traces, state, map editor'}
                >
                  {v === 'simple' ? 'Simple view' : 'Advanced view'}
                </button>
              ))}
            </div>
          )}
          <span className="flex items-center gap-1.5 text-[11px] text-slate-400" title={metaError ?? 'Python AI engine reachable'}>
            <span className={`h-2 w-2 rounded-full ${connected ? 'bg-emerald-400' : 'bg-red-500'}`} />
            {connected ? 'AI engine online' : 'AI engine offline'}
          </span>
          {demo.active ? (
            <button className="btn btn-active" onClick={demo.stop}>
              ■ Stop demo
            </button>
          ) : (
            <button
              className="btn btn-primary"
              onClick={() => {
                setPage('command')
                void demo.start()
              }}
              title="Scripted 2-4 minute presentation run"
            >
              ▶ Demo Mode
            </button>
          )}
        </div>
      </header>

      {page === 'command' && (
        <CommandCenter
          view={view}
          sim={sim}
          meta={meta}
          demo={demo}
          tab={tab}
          setTab={setTab}
          selectedVictim={selectedVictim}
          setSelectedVictim={setSelectedVictim}
        />
      )}
      {page === 'lab' && <AlgorithmLab meta={meta} sessionId={sim.snap?.session_id ?? null} />}
      {page === 'concepts' && <ConceptsPage snap={sim.snap} onNavigate={setPage} />}

      {(sim.error || metaError) && (
        <div className="fixed bottom-4 right-4 z-50 flex max-w-md items-start gap-3 rounded-lg border border-red-700 bg-red-950/95 px-4 py-3 text-[12.5px] text-red-100 shadow-2xl">
          <span className="font-bold">!</span>
          <span className="flex-1">{sim.error ?? metaError}</span>
          <button className="text-red-300 hover:text-white" onClick={() => (sim.error ? sim.clearError() : setMetaError(null))} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}
    </div>
  )
}
