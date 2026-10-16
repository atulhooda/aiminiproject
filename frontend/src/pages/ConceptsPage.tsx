import type { ReactNode } from 'react'
import { PHASES, PHASE_LABEL } from '../simulation/theme'
import type { Snapshot } from '../types/api'

type Page = 'command' | 'lab' | 'concepts'

interface Concept {
  unit: string
  title: string
  body: ReactNode
  where: string[]
  see: string
  live?: (s: Snapshot) => string | null
}

const CONCEPTS: Concept[] = [
  {
    unit: 'Unit 1',
    title: 'Intelligent agent',
    body: 'The Disaster Response Commander observes the environment, maintains an internal state, chooses actions and tries to maximise its rescue objectives. It is a model-based, goal-based agent whose choices are guided by a utility (priority-weighted rescues minus rescue time).',
    where: ['backend/app/agents/disaster_agent.py - DisasterResponseAgent'],
    see: 'Command Center → agent decision cycle strip',
    live: (s) => `AI state: ${s.stats.ai_state}; ${s.stats.agent.actions_executed} primitive actions executed so far.`,
  },
  {
    unit: 'Unit 1',
    title: 'Agents & environments (PEAS)',
    body: (
      <table className="mt-1 w-full text-[11.5px]">
        <tbody>
          {[
            ['Performance', 'victims rescued (critical first), survival, rescue time, distance, danger exposure, no violated constraints'],
            ['Environment', '2-D disaster grid: roads, buildings, debris, fire, flood, hospitals, safe zones, victims'],
            ['Actuators', 'MOVE, RESCUE, TRANSPORT, DELIVER_TO_HOSPITAL / SAFE_ZONE, WAIT (per unit), REPLAN'],
            ['Sensors', 'field/radio reports, unit sensors (radius 2), unit telemetry, hospital status'],
          ].map(([k, v]) => (
            <tr key={k} className="border-t border-ink-600">
              <td className="w-28 py-1 font-semibold text-slate-200">{k}</td>
              <td className="py-1 text-slate-400">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    ),
    where: ['backend/app/agents/disaster_agent.py (module docstring)', 'backend/app/environment/'],
    see: 'Command Center map + decision log',
  },
  {
    unit: 'Unit 1',
    title: 'Rational behaviour',
    body: 'A rational agent picks the action expected to maximise its performance measure given what it knows. Here victims are ranked by an explainable priority function, resources are allocated by a CSP that maximises priority-weighted rescues minus estimated rescue time, and plans are repaired as soon as new percepts make them invalid or worse - including dropping a pick-up when a patient on board would face a long detour, and pre-empting a less urgent mission when a critical victim has no free ALS ambulance.',
    where: ['backend/app/agents/priority.py', 'backend/app/csp/allocation.py (utility + branch-and-bound)'],
    see: 'Right panel → Victims by priority → click a victim for “why”',
    live: (s) => {
      const top = [...s.victims].filter((v) => v.reported && !['RESCUED', 'DECEASED'].includes(v.status)).sort((a, b) => b.priority - a.priority)[0]
      return top ? `Current top goal: ${top.id} (${top.severity}) with priority ${top.priority.toFixed(1)}.` : null
    },
  },
  {
    unit: 'Unit 1',
    title: 'Agent architecture',
    body: (
      <div>
        <p>Every tick runs the same eight-phase cycle. User events trigger an immediate reactive cycle between ticks.</p>
        <div className="mt-2 flex flex-wrap items-center gap-1 text-[10.5px]">
          {PHASES.map((p, i) => (
            <span key={p} className="flex items-center gap-1">
              <span className="rounded border border-cyan-800 bg-cyan-950/50 px-1.5 py-0.5 font-semibold text-cyan-200">{PHASE_LABEL[p]}</span>
              {i < PHASES.length - 1 && <span className="text-slate-500">→</span>}
            </span>
          ))}
          <span className="text-slate-500">↺</span>
        </div>
      </div>
    ),
    where: ['DisasterResponseAgent.decide / observe', 'backend/app/environment/simulator.py - Simulation.step'],
    see: 'Agent decision cycle strip (summary of each phase, every tick)',
    live: (s) => (s.phase_trace.length ? s.phase_trace.map((p) => `${PHASE_LABEL[p.phase]}: ${p.summary}`).join(' · ') : null),
  },
  {
    unit: 'Unit 2',
    title: 'State-space search',
    body: 'Each configuration of resources, victims and environmental conditions is a state: s = (resource positions, remaining victims, blocked roads, hazards, available resources, hospital capacity, current rescue tasks). Actions are the primitive unit actions; executing them is the transition model T(s, a); the goal test is “no reported victim remains”. Route finding is the search sub-problem: states are cells, actions are N/E/S/W moves, step cost is danger-aware.',
    where: ['backend/app/models/state.py - WorldState', 'backend/app/search/base.py - GridSearchProblem', 'Simulation.execute (transition model)'],
    see: 'Command Center → State tab',
    live: (s) => `s(${s.state.tick}): ${Object.keys(s.state.remaining_victims).length} remaining victims, ${s.state.blocked_roads.length} blocked roads, goal test ${s.state.is_goal}.`,
  },
  {
    unit: 'Unit 2',
    title: 'BFS',
    body: 'Uninformed search with a FIFO frontier. Complete; returns the route with the fewest steps, which is not the cheapest once costs depend on danger.',
    where: ['backend/app/search/bfs.py'],
    see: 'Algorithm Lab (blue) · or select BFS for the live agent',
  },
  {
    unit: 'Unit 2',
    title: 'Greedy best-first search',
    body: 'Expands the node with the smallest heuristic h(n). Usually explores very few nodes, but ignores the cost already paid g(n) and therefore is not optimal.',
    where: ['backend/app/search/greedy_best_first.py'],
    see: 'Algorithm Lab (orange)',
  },
  {
    unit: 'Unit 2',
    title: 'A* search',
    body: (
      <p>
        A* combines the actual path cost <b className="text-slate-200">g(n)</b> with the heuristic estimate <b className="text-slate-200">h(n)</b>:{' '}
        <span className="font-mono text-cyan-200">f(n) = g(n) + h(n)</span>. With an admissible, consistent heuristic the first time the goal is popped its path is
        optimal. The agent uses A* by default for every route.
      </p>
    ),
    where: ['backend/app/search/astar.py'],
    see: 'Search tab + cyan explored cells on the map; Algorithm Lab (aqua)',
    live: (s) => (s.last_search ? `Last route: ${s.last_search.algorithm} ${s.last_search.purpose} - cost ${s.last_search.cost.toFixed(1)}, ${s.last_search.nodes_expanded} nodes, ${s.last_search.time_ms.toFixed(2)} ms.` : null),
  },
  {
    unit: 'Unit 2',
    title: 'Heuristic functions',
    body: 'h(n) = Manhattan distance to the goal. Every legal step costs at least 1 (terrain cost ≥ 1, danger adds a non-negative penalty) and changes the Manhattan distance by exactly 1, so h never overestimates (admissible) and h(n) ≤ c(n, n′) + h(n′) (consistent). Euclidean and h = 0 (uniform-cost search) are available in the lab for comparison.',
    where: ['backend/app/search/heuristics.py', 'backend/app/environment/mobility.py - step cost = terrain + 6 × danger'],
    see: 'Algorithm Lab → heuristic selector',
  },
  {
    unit: 'Unit 2',
    title: 'Online search',
    body: 'The agent interleaves planning and execution. It plans with the free-space assumption on its belief map, executes one action per tick, perceives, and replans when the remaining plan is contradicted. The lab also runs LRTA*, which learns H(s) one step at a time.',
    where: ['backend/app/search/online.py - repeated_astar, lrta_star', 'DisasterResponseAgent.check_constraints / _repair_route'],
    see: 'Algorithm Lab → Online search section',
    live: (s) => `Route repairs so far: ${s.stats.agent.route_replans}.`,
  },
  {
    unit: 'Unit 2',
    title: 'Dynamic & unknown environments',
    body: 'Roads get blocked, fire spreads, water rises, victims appear, ambulances break down and hospitals lose capacity. Some damage is missing from the initial report and is only found by unit sensors. The agent detects every change, marks invalid plans and replans autonomously.',
    where: ['backend/app/environment/events.py', 'backend/app/environment/scenarios.py (hidden hazards)'],
    see: 'Command Center → Disaster event panel; amber “?” cells on the map',
    live: (s) => `${s.stats.agent.hazards_discovered} hidden hazard(s) discovered, ${s.belief_diff.length} still unknown, ${s.stats.replanning_count} replans.`,
  },
  {
    unit: 'Unit 3',
    title: 'Constraint satisfaction problem',
    body: 'Resource allocation is modelled as a CSP. Variables: victims in the attention window. Domains: every (method, ambulance, team, hospital/safe-zone) combination - including a partial EXTRACT_ONLY plan - plus DEFER. Constraints: availability, ALS capability for critical patients, ICU and ER capacity, hazard capability (firefighters), reachability, ambulance seats, one task per team, same hospital for a shared trip, and critical coverage.',
    where: ['backend/app/csp/allocation.py', 'backend/app/csp/constraints.py'],
    see: 'Command Center → CSP solver tab',
    live: (s) => (s.last_csp ? `Last CSP: ${s.last_csp.variables.length} variables, ${s.last_csp.constraints.total} constraints, ${s.last_csp.result.toLowerCase()}.` : null),
  },
  {
    unit: 'Unit 3',
    title: 'Constraint propagation',
    body: 'Node consistency applies the unary constraints to the domains, AC-3 makes every binary arc consistent (and can prove infeasibility without search), and forward checking prunes the domains of future variables after each assignment, including n-ary capacity constraints.',
    where: ['backend/app/csp/solver.py - enforce_node_consistency, ac3, _forward_check'],
    see: 'CSP solver tab → pipeline',
    live: (s) => (s.last_csp ? `Node consistency −${s.last_csp.stats.node_consistency_removals}, AC-3 −${s.last_csp.stats.ac3_removals}, forward checking −${s.last_csp.stats.fc_prunings}.` : null),
  },
  {
    unit: 'Unit 3',
    title: 'Backtracking search',
    body: 'Depth-first assignment with MRV + degree variable ordering and utility-ordered values, extended with branch-and-bound so the solver returns the best consistent assignment. If “every critical victim must be served” is unsatisfiable, the agent relaxes that constraint and solves again.',
    where: ['backend/app/csp/solver.py - BacktrackingSolver'],
    see: 'CSP solver tab → backtracking stats',
    live: (s) => (s.last_csp ? `Last search: ${s.last_csp.stats.nodes} nodes, ${s.last_csp.stats.backtracks} backtracks, ${s.last_csp.optimal ? 'optimal' : 'best within budget'}.` : null),
  },
  {
    unit: 'Unit 5',
    title: 'Goal-based planning',
    body: 'The mission goal - “rescue all reported victims, critical first, and deliver them to suitable care” - is turned into one sub-goal per victim; the goal set is re-formulated every cycle as victims appear, deteriorate, are rescued or die.',
    where: ['DisasterResponseAgent.identify_goals', 'backend/app/agents/priority.py'],
    see: 'Mission plan tab → MISSION root',
  },
  {
    unit: 'Unit 5',
    title: 'Hierarchical planning',
    body: 'An HTN planner decomposes RESCUE_VICTIM(v) with the method the CSP chose: AMBULANCE_DIRECT, EXTRACT_AND_TRANSPORT, TEAM_EVACUATE or the partial EXTRACT_ONLY → Assign → Navigate → Extract/Rescue → Select hospital → Transport → Deliver → Update resources. Primitive tasks are queued on each unit’s agenda; joint tasks are synchronised (an ambulance waits for the team’s extraction).',
    where: ['backend/app/planning/planner.py - HierarchicalPlanner'],
    see: 'Mission plan (HTN) tab',
    live: (s) => `${s.stats.agent.missions_created} missions planned, ${s.stats.agent.missions_completed} completed.`,
  },
  {
    unit: 'Unit 5',
    title: 'AI application',
    body: 'Disaster response is a classic AI application: a dynamic, partially observable, multi-unit environment where search, constraint reasoning and planning must work together in real time. No machine learning or language models are used - all intelligence comes from classical algorithms implemented in this project.',
    where: ['whole system'],
    see: 'Demo Mode',
  },
]

export function ConceptsPage({ snap, onNavigate }: { snap: Snapshot | null; onNavigate: (p: Page) => void }) {
  const units = ['Unit 1', 'Unit 2', 'Unit 3', 'Unit 5']
  const unitTitle: Record<string, string> = {
    'Unit 1': 'Intelligent agents',
    'Unit 2': 'Search',
    'Unit 3': 'Constraint satisfaction',
    'Unit 5': 'Planning & applications',
  }
  return (
    <div className="scroll-thin flex-1 overflow-y-auto p-3">
      <section className="panel p-4">
        <h1 className="text-lg font-semibold text-slate-100">AI Concepts - where each syllabus topic lives</h1>
        <p className="mt-1 max-w-4xl text-[12.5px] leading-relaxed text-slate-400">
          Each card explains a concept, points to the module that implements it and to the part of the interface where you can watch it work.
          {snap ? ' Green lines are live values from the simulation currently loaded in the Command Center.' : ''}
        </p>
        <div className="mt-2 flex gap-2">
          <button className="btn" onClick={() => onNavigate('command')}>
            Open Command Center
          </button>
          <button className="btn" onClick={() => onNavigate('lab')}>
            Open Algorithm Lab
          </button>
        </div>
      </section>

      {units.map((u) => (
        <section key={u} className="mt-3">
          <h2 className="mb-2 px-1 text-[12px] font-bold uppercase tracking-[0.14em] text-cyan-300">
            {u} · {unitTitle[u]}
          </h2>
          <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
            {CONCEPTS.filter((c) => c.unit === u).map((c) => {
              const live = snap && c.live ? c.live(snap) : null
              return (
                <article key={c.title} className="panel flex flex-col p-3.5">
                  <h3 className="text-[14px] font-semibold text-slate-100">{c.title}</h3>
                  <div className="mt-1.5 flex-1 text-[12.5px] leading-relaxed text-slate-400">{c.body}</div>
                  {live && <div className="mt-2 rounded border border-emerald-800/70 bg-emerald-950/30 px-2 py-1 text-[11.5px] text-emerald-200">{live}</div>}
                  <div className="mt-2 border-t border-ink-600 pt-2 text-[11px]">
                    {c.where.map((w) => (
                      <div key={w} className="font-mono text-slate-400">
                        {w}
                      </div>
                    ))}
                    <div className="mt-1 text-slate-500">See it: {c.see}</div>
                  </div>
                </article>
              )
            })}
          </div>
        </section>
      ))}

      <section className="panel mt-3 p-4">
        <div className="panel-title mb-2">Search algorithm properties (b = branching factor ≤ 4, d = depth of the shallowest goal, m = max depth)</div>
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-left text-[10.5px] uppercase tracking-wide text-slate-500">
              <th className="py-1.5">Algorithm</th>
              <th>Frontier order</th>
              <th>Complete</th>
              <th>Optimal (danger-aware costs)</th>
              <th>Time / space</th>
            </tr>
          </thead>
          <tbody className="text-slate-300">
            <tr className="border-t border-ink-600">
              <td className="py-1.5 font-semibold">BFS</td>
              <td>FIFO (depth)</td>
              <td>yes</td>
              <td>only when every step costs the same</td>
              <td>O(b^d) / O(b^d)</td>
            </tr>
            <tr className="border-t border-ink-600">
              <td className="py-1.5 font-semibold">Greedy best-first</td>
              <td>h(n)</td>
              <td>yes on a finite grid with an explored set</td>
              <td>no</td>
              <td>O(b^m) worst case, usually far less</td>
            </tr>
            <tr className="border-t border-ink-600">
              <td className="py-1.5 font-semibold">A*</td>
              <td>g(n) + h(n)</td>
              <td>yes</td>
              <td>yes (admissible, consistent h)</td>
              <td>exponential in the error of h; ≤ grid size here</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
  )
}
