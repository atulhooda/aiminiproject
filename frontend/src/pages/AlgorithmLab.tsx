import { useCallback, useEffect, useRef, useState } from 'react'
import { BarChart, Legend } from '../lab/BarChart'
import { LabGrid, type Trajectory } from '../lab/LabGrid'
import { api, type LabSource } from '../services/api'
import { GUTTER } from '../simulation/renderer'
import { ALGO_COLOR, ALGO_LABEL } from '../simulation/theme'
import type { Algorithm, BenchmarkResponse, CompareResponse, LabMap, Meta, OnlineResponse, Pos } from '../types/api'

// Online-search trajectories: validated all-pairs trio (aqua / yellow / violet) + dash patterns.
const ONLINE = {
  offline: { color: '#199e70', label: 'A* (map fully known)', dash: [] as number[] },
  repeated: { color: '#c98500', label: 'Repeated A* (free-space assumption)', dash: [6, 4] },
  lrta: { color: '#9085e9', label: 'LRTA* (real-time learning)', dash: [2, 3] },
}

const ALGOS: Algorithm[] = ['BFS', 'GREEDY', 'ASTAR']
const ANIM_MS = 3200

export function AlgorithmLab({ meta, sessionId }: { meta: Meta | null; sessionId: string | null }) {
  const [source, setSource] = useState('URBAN_FIRE')
  const [map, setMap] = useState<LabMap | null>(null)
  const [start, setStart] = useState<Pos | null>(null)
  const [goal, setGoal] = useState<Pos | null>(null)
  const [pick, setPick] = useState<'start' | 'goal'>('start')
  const [profile, setProfile] = useState('GROUND_VEHICLE')
  const [heuristic, setHeuristic] = useState('manhattan')
  const [dangerAware, setDangerAware] = useState(true)
  const [result, setResult] = useState<CompareResponse | null>(null)
  const [bench, setBench] = useState<BenchmarkResponse | null>(null)
  const [trials, setTrials] = useState(100)
  const [online, setOnline] = useState<OnlineResponse | null>(null)
  const [radius, setRadius] = useState(1)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [anim, setAnim] = useState({ startedAt: 0, now: 0 })
  const [width, setWidth] = useState(1200)
  const wrapRef = useRef<HTMLDivElement>(null)

  const src: LabSource = source === 'SESSION' ? { scenario: 'EARTHQUAKE', session_id: sessionId } : { scenario: source }

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const loadMap = useCallback(async () => {
    setError(null)
    try {
      const m = await api.labMap(source === 'SESSION' ? { scenario: 'EARTHQUAKE', session_id: sessionId } : { scenario: source })
      setMap(m)
      setStart(m.suggested_start)
      setGoal(m.suggested_goal)
      setResult(null)
      setBench(null)
      setOnline(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [source, sessionId])

  useEffect(() => {
    void loadMap()
  }, [loadMap])

  // Drive the expansion animation for ANIM_MS after each (re)start.
  const animStart = anim.startedAt
  useEffect(() => {
    if (!result) return
    let raf = 0
    const tick = () => {
      const t = performance.now()
      setAnim((a) => ({ ...a, now: t }))
      if (t - animStart < ANIM_MS + 300) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [result, animStart])

  const run = async () => {
    if (!start || !goal) return
    setBusy('compare')
    setError(null)
    try {
      const r = await api.compare(src, start, goal, profile, dangerAware, heuristic)
      setResult(r)
      const t = performance.now()
      setAnim({ startedAt: t, now: t })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const runBench = async () => {
    setBusy('bench')
    setError(null)
    try {
      setBench(await api.benchmark(src, trials, profile, dangerAware, heuristic))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const runOnline = async () => {
    if (!start || !goal) return
    setBusy('online')
    setError(null)
    try {
      setOnline(await api.online(src, start, goal, profile, radius))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const onCell = (p: Pos) => {
    if (pick === 'start') {
      setStart(p)
      setPick('goal')
    } else {
      setGoal(p)
      setPick('start')
    }
    setResult(null)
    setOnline(null)
  }

  const cols = map?.cols ?? 25
  const rows = map?.rows ?? 25
  const cs3 = Math.max(7, Math.min(20, Math.floor((width / 3 - 34 - GUTTER) / cols)))
  const csBig = Math.max(8, Math.min(22, Math.floor((width * 0.5 - 40 - GUTTER) / cols)))
  // All three grids reveal at the same rate (nodes / second), so BFS visibly takes longer.
  const maxNodes = result ? Math.max(...result.results.map((r) => r.explored.length)) : 1
  const rate = maxNodes / ANIM_MS
  const elapsed = anim.now - anim.startedAt

  return (
    <div ref={wrapRef} className="scroll-thin flex-1 space-y-3 overflow-y-auto p-3">
      <section className="panel p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="max-w-xl">
            <h1 className="text-lg font-semibold text-slate-100">Algorithm Lab</h1>
            <p className="text-[12px] text-slate-400">
              Run BFS, Greedy Best-First and A* on the same map and query. Every number is measured from a real run (times are the median of{' '}
              {result?.timing_repeats ?? 5} repetitions). Click a grid to set the start (S) and goal (G).
            </p>
          </div>
          <div className="ml-auto flex flex-wrap items-end gap-2 text-[11px] text-slate-400">
            <label className="flex flex-col gap-1">
              Map
              <select className="select" value={source} onChange={(e) => setSource(e.target.value)}>
                {(meta?.scenarios ?? []).filter((s) => s.id !== 'CUSTOM').map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} (ground truth)
                  </option>
                ))}
                {sessionId && <option value="SESSION">Live simulation (agent belief map)</option>}
              </select>
            </label>
            <details className="relative">
              <summary className="btn cursor-pointer list-none">Options ▾</summary>
              <div className="panel absolute right-0 z-20 mt-1 flex w-64 flex-col gap-2 p-3">
            <label className="flex flex-col gap-1">
                  Unit profile
                  <select className="select" value={profile} onChange={(e) => setProfile(e.target.value)}>
                    {(meta?.profiles ?? []).map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  Heuristic h(n)
                  <select className="select" value={heuristic} onChange={(e) => setHeuristic(e.target.value)}>
                    {(meta?.heuristics ?? ['manhattan']).map((h) => (
                      <option key={h} value={h}>
                        {h}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex items-center gap-1.5 pb-1.5">
                  <input type="checkbox" className="accent-cyan-500" checked={dangerAware} onChange={(e) => setDangerAware(e.target.checked)} />
                  danger-aware costs
                </label>
              </div>
            </details>
            <div className="flex overflow-hidden rounded-md border border-ink-500" role="group" aria-label="Next click sets">
              <button className={`px-2 py-1.5 ${pick === 'start' ? 'bg-slate-200 text-slate-900' : 'bg-ink-700'}`} onClick={() => setPick('start')}>
                Set start {start && `(${start.join(',')})`}
              </button>
              <button className={`px-2 py-1.5 ${pick === 'goal' ? 'bg-red-400 text-slate-900' : 'bg-ink-700'}`} onClick={() => setPick('goal')}>
                Set goal {goal && `(${goal.join(',')})`}
              </button>
            </div>
            <button className="btn btn-primary" onClick={() => void run()} disabled={!map || busy !== null}>
              {busy === 'compare' ? 'Running…' : '▶ Run comparison'}
            </button>
          </div>
        </div>
        {error && <div className="mt-2 text-[12px] text-red-300">{error}</div>}
      </section>

      {map && start && goal && (
        <section className="panel p-3">
          <div className="mb-2 flex items-center gap-3">
            <span className="panel-title">Head-to-head: explored cells, frontier and path</span>
            <Legend items={ALGOS.map((a) => ({ label: ALGO_LABEL[a], color: ALGO_COLOR[a] }))} />
            {result && (
              <button className="btn ml-auto py-0.5" onClick={() => setAnim({ startedAt: performance.now(), now: performance.now() })}>
                ↺ Replay animation
              </button>
            )}
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {ALGOS.map((algo) => {
              const r = result?.results.find((x) => x.algorithm === algo)
              const revealed = r ? Math.floor(elapsed * rate) : 0
              const done = r ? revealed >= r.explored.length : false
              return (
                <div key={algo} className="min-w-0">
                  <div className="mb-1 flex items-baseline gap-2">
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ background: ALGO_COLOR[algo] }} />
                    <span className="text-[13px] font-semibold text-slate-100">{ALGO_LABEL[algo]}</span>
                    <span className="text-[10.5px] text-slate-500">
                      {algo === 'BFS' ? 'FIFO queue' : algo === 'GREEDY' ? 'f(n) = h(n)' : 'f(n) = g(n) + h(n)'}
                    </span>
                    {r && (
                      <span className="ml-auto font-mono text-[11px] text-slate-300">
                        {Math.min(revealed, r.explored.length)}/{r.nodes_expanded} nodes
                      </span>
                    )}
                  </div>
                  <LabGrid
                    map={map}
                    cellSize={cs3}
                    explored={r?.explored}
                    frontier={r?.frontier}
                    path={r?.path}
                    pathColor={ALGO_COLOR[algo]}
                    revealed={revealed}
                    showResult={done}
                    start={start}
                    goal={goal}
                    onCellClick={onCell}
                  />
                  {r && done && (
                    <div className="mt-1 grid grid-cols-3 gap-1 font-mono text-[11px]">
                      <Kv k="cost" v={r.found ? r.cost.toFixed(1) : 'no path'} hi={r.optimal} />
                      <Kv k="steps" v={String(r.steps)} />
                      <Kv k="optimal" v={r.optimal ? 'yes' : `no (×${r.cost_ratio})`} hi={r.optimal} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
          <div className="mt-2 text-[10.5px] text-slate-500">
            <span className="text-cyan-300">Cyan</span> = expanded (explored) cells, brightest = most recent; <span className="text-amber-300">amber outline</span> =
            frontier when the search stopped; line = returned path. Grey cells: buildings; striped: debris; red tint: danger.
          </div>
        </section>
      )}

      {result && (
        <section className="panel p-3">
          <div className="panel-title mb-2">
            Results · best possible cost {result.optimal_cost ?? '-'}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wide text-slate-500">
                  {['Algorithm', 'Path cost', 'Steps', 'Nodes explored', 'Time (ms)', 'Optimal?'].map((h) => (
                    <th key={h} className="py-1.5 pr-3 font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="font-mono">
                {result.results.map((r) => (
                  <tr key={r.algorithm} className="border-t border-ink-600">
                    <td className="py-1.5 pr-3 font-sans font-semibold text-slate-100">
                      <span className="mr-1.5 inline-block h-2 w-2 rounded-sm" style={{ background: ALGO_COLOR[r.algorithm] }} />
                      {r.label}
                    </td>
                    <td className="pr-3">{r.found ? r.cost.toFixed(1) : 'no path'}</td>
                    <td className="pr-3">{r.steps}</td>
                    <td className="pr-3">{r.nodes_expanded}</td>
                    <td className="pr-3">{r.time_ms.toFixed(3)}</td>
                    <td className={r.optimal ? 'text-emerald-300' : 'text-amber-300'}>{r.optimal ? '✓ yes' : `✗ no (${r.cost_ratio}× the best cost)`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            <BarChart
              title="Nodes explored"
              data={result.results.map((r) => ({ key: r.algorithm, label: ALGO_LABEL[r.algorithm], value: r.nodes_expanded, color: ALGO_COLOR[r.algorithm] }))}
            />
            <BarChart
              title="Path cost"
              unit="danger-aware"
              data={result.results.map((r) => ({
                key: r.algorithm,
                label: ALGO_LABEL[r.algorithm],
                value: r.cost,
                color: ALGO_COLOR[r.algorithm],
                detail: r.optimal ? 'optimal' : `${r.cost_ratio}× optimum`,
              }))}
              format={(v) => v.toFixed(1)}
            />
            <BarChart
              title="Execution time"
              unit="ms, median of 5"
              data={result.results.map((r) => ({ key: r.algorithm, label: ALGO_LABEL[r.algorithm], value: r.time_ms, color: ALGO_COLOR[r.algorithm] }))}
              format={(v) => v.toFixed(3)}
            />
          </div>
          <p className="mt-2 text-[11.5px] leading-relaxed text-slate-400">
            {dangerAware
              ? 'With danger-aware costs, BFS minimises the number of steps but not the cost, so it often drives straight through danger zones. Greedy follows h(n) alone and explores few nodes but can return a costly route. A* combines g(n) and an admissible h(n) and returns the cheapest route.'
              : 'With uniform costs every step costs 1, so BFS and A* both return shortest paths; A* explores fewer nodes thanks to the heuristic.'}
          </p>
        </section>
      )}

      <details className="panel p-3">
        <summary className="cursor-pointer select-none text-[12.5px] font-semibold text-slate-200">More: benchmark all three algorithms on 100 random queries</summary>
        <div className="mt-3">
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <div className="panel-title">Benchmark: random queries on this map</div>
            <div className="text-[11.5px] text-slate-400">Same random start/goal pairs for every algorithm; optimality is checked against uniform-cost search.</div>
          </div>
          <label className="ml-auto flex items-center gap-2 text-[11px] text-slate-400">
            queries
            <input type="number" min={5} max={200} value={trials} onChange={(e) => setTrials(Math.max(5, Math.min(200, Number(e.target.value))))} className="select w-20" />
          </label>
          <button className="btn btn-primary" onClick={() => void runBench()} disabled={!map || busy !== null}>
            {busy === 'bench' ? 'Running…' : 'Run benchmark'}
          </button>
        </div>
        {bench && (
          <>
            <table className="mt-3 w-full text-[12px]">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wide text-slate-500">
                  {['Algorithm', 'Avg nodes explored', 'Optimal paths', 'Avg time (ms)'].map((h) => (
                    <th key={h} className="py-1.5 pr-3 font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="font-mono">
                {bench.summary.map((r) => (
                  <tr key={r.algorithm} className="border-t border-ink-600">
                    <td className="py-1.5 pr-3 font-sans font-semibold text-slate-100">
                      <span className="mr-1.5 inline-block h-2 w-2 rounded-sm" style={{ background: ALGO_COLOR[r.algorithm] }} />
                      {r.label}
                    </td>
                    <td className="pr-3">{r.avg_nodes_expanded}</td>
                    <td className="pr-3">{(r.optimal_rate * 100).toFixed(0)}%</td>
                    <td className="pr-3">{r.avg_time_ms.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <BarChart
                title={`Average nodes explored (${bench.trials} queries)`}
                data={bench.summary.map((r) => ({ key: r.algorithm, label: ALGO_LABEL[r.algorithm], value: r.avg_nodes_expanded, color: ALGO_COLOR[r.algorithm] }))}
                format={(v) => v.toFixed(1)}
              />
              <BarChart
                title="Queries solved optimally"
                unit="%"
                data={bench.summary.map((r) => ({ key: r.algorithm, label: ALGO_LABEL[r.algorithm], value: r.optimal_rate * 100, color: ALGO_COLOR[r.algorithm] }))}
                format={(v) => `${v.toFixed(0)}%`}
              />
            </div>
          </>
        )}
        </div>
      </details>

      <details className="panel p-3">
        <summary className="cursor-pointer select-none text-[12.5px] font-semibold text-slate-200">More: online search when the map is unknown (LRTA*, repeated A*)</summary>
        <div className="mt-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="max-w-2xl">
            <div className="panel-title">Online search in an unknown environment</div>
            <div className="text-[11.5px] text-slate-400">
              The online agents start knowing nothing about the map (every unknown cell is assumed to be open road) and only see cells within their sensor
              radius. Repeated A* replans whenever its plan is contradicted; LRTA* plans one step at a time and learns H(s).
            </div>
          </div>
          <label className="ml-auto flex items-center gap-2 text-[11px] text-slate-400">
            sensor radius
            <select className="select" value={radius} onChange={(e) => setRadius(Number(e.target.value))}>
              {[0, 1, 2, 3].map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
          <button className="btn btn-primary" onClick={() => void runOnline()} disabled={!map || !start || !goal || busy !== null}>
            {busy === 'online' ? 'Running…' : 'Run online search'}
          </button>
        </div>
        {online && map && start && goal && (
          <div className="mt-3 grid gap-4 lg:grid-cols-[auto_1fr]">
            <LabGrid
              map={map}
              cellSize={csBig}
              start={start}
              goal={goal}
              revealedCells={online.repeated_astar.cells_revealed}
              trajectories={
                [
                  { path: online.offline.trajectory, color: ONLINE.offline.color, width: 4 },
                  { path: online.repeated_astar.trajectory, color: ONLINE.repeated.color, dash: ONLINE.repeated.dash, width: 2.5 },
                  { path: online.lrta_star.trajectory, color: ONLINE.lrta.color, dash: ONLINE.lrta.dash, width: 2 },
                ] satisfies Trajectory[]
              }
              onCellClick={onCell}
            />
            <div className="min-w-0">
              <Legend items={Object.values(ONLINE).map((o) => ({ label: o.label, color: o.color, dash: o.dash.length > 0 }))} />
              <table className="mt-2 w-full text-[12px]">
                <thead>
                  <tr className="text-left text-[10px] uppercase tracking-wide text-slate-500">
                    {['Agent', 'Reached goal', 'Steps walked', 'Cost', 'Replans', 'Nodes expanded', 'H updates', 'Time (ms)'].map((h) => (
                      <th key={h} className="py-1.5 pr-3 font-semibold">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="font-mono">
                  <tr className="border-t border-ink-600">
                    <td className="py-1.5 pr-3 font-sans text-slate-100">{ONLINE.offline.label}</td>
                    <td className="pr-3">{online.offline.found ? 'yes' : 'no'}</td>
                    <td className="pr-3">{online.offline.steps}</td>
                    <td className="pr-3">{online.offline.cost.toFixed(1)}</td>
                    <td className="pr-3">-</td>
                    <td className="pr-3">{online.offline.nodes_expanded}</td>
                    <td className="pr-3">-</td>
                    <td className="pr-3">-</td>
                  </tr>
                  {[
                    [ONLINE.repeated.label, online.repeated_astar],
                    [ONLINE.lrta.label, online.lrta_star],
                  ].map(([label, r]) => {
                    const run = r as OnlineResponse['lrta_star']
                    return (
                      <tr key={label as string} className="border-t border-ink-600">
                        <td className="py-1.5 pr-3 font-sans text-slate-100">{label as string}</td>
                        <td className="pr-3">{run.found ? 'yes' : 'no'}</td>
                        <td className="pr-3">{run.steps}</td>
                        <td className="pr-3">{run.cost.toFixed(1)}</td>
                        <td className="pr-3">{run.replans}</td>
                        <td className="pr-3">{run.nodes_expanded}</td>
                        <td className="pr-3">{run.heuristic_updates}</td>
                        <td className="pr-3">{run.time_ms.toFixed(2)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <div className="mt-2 grid gap-3 md:grid-cols-2">
                <BarChart
                  title="Steps actually walked"
                  data={[
                    { key: 'off', label: 'A* (known)', value: online.offline.steps, color: ONLINE.offline.color },
                    { key: 'rep', label: 'Repeated A*', value: online.repeated_astar.steps, color: ONLINE.repeated.color },
                    { key: 'lrta', label: 'LRTA*', value: online.lrta_star.steps, color: ONLINE.lrta.color },
                  ]}
                />
                <BarChart
                  title="Nodes expanded (total planning effort)"
                  data={[
                    { key: 'off', label: 'A* (known)', value: online.offline.nodes_expanded, color: ONLINE.offline.color },
                    { key: 'rep', label: 'Repeated A*', value: online.repeated_astar.nodes_expanded, color: ONLINE.repeated.color },
                    { key: 'lrta', label: 'LRTA*', value: online.lrta_star.nodes_expanded, color: ONLINE.lrta.color },
                  ]}
                />
              </div>
              {online.repeated_astar.events.length > 0 && (
                <div className="mt-2">
                  <div className="text-[10.5px] uppercase tracking-wide text-slate-500">Repeated A* replanning events</div>
                  <ul className="scroll-thin mt-1 max-h-32 overflow-y-auto font-mono text-[11px] text-slate-400">
                    {online.repeated_astar.events.map((e, i) => (
                      <li key={i}>
                        step {e.step} at ({e.pos.join(',')}): {e.message}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="mt-1 text-[10.5px] text-slate-500">
                Grey tint: cells revealed by the repeated-A* agent’s sensors ({online.repeated_astar.cells_revealed.length} of {rows * cols}).
              </div>
            </div>
          </div>
        )}
        </div>
      </details>
    </div>
  )
}

function Kv({ k, v, hi }: { k: string; v: string; hi?: boolean }) {
  return (
    <div className="rounded border border-ink-600 bg-ink-850 px-1.5 py-0.5">
      <span className="text-slate-500">{k} </span>
      <span className={hi ? 'text-emerald-300' : 'text-slate-200'}>{v}</span>
    </div>
  )
}
