# Syllabus Mapping

This document maps every syllabus topic to the component that implements it, the source file, and the place in the user interface where it can be seen. It ends with a step-by-step checklist for demonstrating each concept in the viva.

File paths are relative to the project root. UI locations refer to the three pages (Command Center, Algorithm Lab, AI Concepts) and Demo Mode described in `README.md`.

---

## Summary table

| Unit | Syllabus topic | Project component(s) | File path(s) | Visible in the UI |
|---|---|---|---|---|
| 1 | Intelligent Agents | `DisasterResponseAgent`: a model-based, goal-based agent with utility-guided choices that commands all units | `backend/app/agents/disaster_agent.py` | Command Center: agent-cycle strip, AI state in the status bar, Decision Log; AI Concepts page |
| 1 | Agents and Environments | PEAS; ground-truth `World` vs. agent belief map; sensors (`SENSOR_RADIUS = 2`, field reports); actuators (`ActionType`, including the `REPLAN` action); `Simulation` | `backend/app/agents/disaster_agent.py`, `backend/app/environment/world.py`, `backend/app/environment/simulator.py`, `backend/app/environment/events.py`, `backend/app/models/actions.py` | Map (units, victims, fire, water, debris, hidden-hazard markers); DISASTER EVENT controls; State tab |
| 1 | Rational Behavior | Victim priority function (6 explained factors); CSP utility maximisation; danger-aware path costs; bounded rationality (`ATTENTION_WINDOW = 6`, `CSP_NODE_LIMIT = 5000`) | `backend/app/agents/priority.py`, `backend/app/csp/allocation.py`, `backend/app/environment/mobility.py` | Victim priority list with per-factor explanation; CSP Solver tab (utilities, score); Decision Log ("Goal formulation", "Assign ... utility") |
| 1 | Agent Architecture | 8-phase cycle `AgentPhase`: PERCEIVE -> UPDATE_STATE -> IDENTIFY_GOALS -> CHECK_CONSTRAINTS -> PLAN -> SELECT_ACTION -> EXECUTE -> OBSERVE; internal model (belief map); `DecisionLog` | `backend/app/agents/disaster_agent.py`, `backend/app/agents/decision_log.py`, `backend/app/environment/simulator.py` (`step`) | Live agent-cycle strip with per-phase summaries; Decision Log (phase and level of every entry) |
| 2 | State Space Search | `WorldState` (state tuple built from the belief map, goal test); `GridSearchProblem` (route sub-problem); transition model `Simulation.execute` | `backend/app/models/state.py`, `backend/app/search/base.py`, `backend/app/environment/simulator.py` | State tab (state tuple, `is_goal`); Search tab |
| 2 | BFS | `bfs()` | `backend/app/search/bfs.py` | Algorithm selector (Command Center); Algorithm Lab comparison, charts, benchmark |
| 2 | Greedy Best First Search | `greedy_best_first()` | `backend/app/search/greedy_best_first.py` | Algorithm selector; Algorithm Lab |
| 2 | A* Search | `astar()` with (f, h, counter) tie-breaking; the agent's default navigation algorithm | `backend/app/search/astar.py` | Map search overlay (explored and frontier cells, planned paths); Search tab; last-search info; Algorithm Lab |
| 2 | Heuristic Functions | `manhattan` (default), `euclidean`, `zero`; `MIN_STEP_COST = 1.0` makes Manhattan admissible and consistent | `backend/app/search/heuristics.py`, `backend/app/environment/mobility.py` | Algorithm Lab (heuristic choice, `h(start)`, A* vs. UCS optimum); AI Concepts page |
| 2 | Online Search | `repeated_astar` (free-space assumption), `lrta_star` (LRTA*); the agent's sense-validate-replan loop | `backend/app/search/online.py`, `backend/app/agents/disaster_agent.py` | Algorithm Lab online comparison (A* on the known map vs. repeated A* vs. LRTA*, sensor radius); hidden-hazard markers on the map |
| 2 | Search in Dynamic / Unknown Environments | Belief map with hidden hazards; plan validation (`first_blocked_index`, `path_cost_on`); issues `ROUTE_BLOCKED` / `ROUTE_DEGRADED` / `NEEDS_ROUTE` / `TRIP_DETOUR`; `_repair_route`; `REPLAN` action; dynamic events | `backend/app/agents/disaster_agent.py`, `backend/app/search/online.py`, `backend/app/environment/events.py` | Decision Log replanning sequence; replan animation; alert banner; Block road / Start fire events |
| 3 | Constraint Satisfaction Problems | Generic `CSP`; resource-allocation CSP (variables = victims; domains = method x resources x destination, plus DEFER and a partial EXTRACT_ONLY plan allowed only as a fallback); destination re-allocation CSP | `backend/app/csp/solver.py`, `backend/app/csp/constraints.py`, `backend/app/csp/allocation.py` | CSP Solver tab (variables, domain sizes, constraints, assignment) |
| 3 | Constraint Propagation | Node consistency, AC-3 (`ac3`, `_revise`), forward checking generalised to n-ary `CapacityConstraint` | `backend/app/csp/solver.py`, `backend/app/csp/constraints.py` | CSP Solver tab (domain size initial -> after node consistency -> after AC-3; pruning counts per constraint); Decision Log "Constraint propagation: ..." |
| 3 | Backtracking Search | `BacktrackingSolver._backtrack`: MRV + degree, utility / LCV value ordering, branch-and-bound with a capacity-aware bound `min(pooled, plain)`, node budget | `backend/app/csp/solver.py`, `backend/app/csp/allocation.py` | CSP Solver tab stats (nodes, backtracks, forward-checking prunings, bound prunings, optimal); Decision Log "Backtracking search: ..." |
| 5 | Planning | `HierarchicalPlanner`, `PlanTask`, per-unit agendas, plan repair, critical pre-emption (`_preempt_for_critical`) | `backend/app/planning/planner.py`, `backend/app/agents/disaster_agent.py` | Mission Plan tab; planned paths on the map |
| 5 | Goal-based Planning | Goal formulation in `identify_goals`; top goal MISSION; `WorldState.is_goal`; "Check remaining goals" task | `backend/app/agents/disaster_agent.py`, `backend/app/models/state.py` | Decision Log ("Goal formulation", "Most urgent unassigned goal"); Mission Plan root; State tab `is_goal` |
| 5 | Hierarchical Planning | HTN methods `AMBULANCE_DIRECT`, `EXTRACT_AND_TRANSPORT`, `TEAM_EVACUATE` and the partial `EXTRACT_ONLY`; shared trips with mirrored tasks and a detour rule (`TRIP_DETOUR_RATIO = 2.0`, `TRIP_DETOUR_MARGIN = 12.0`) | `backend/app/planning/planner.py` | Mission Plan tab (expandable task tree with status, path cost, progress) |
| 5 | AI Applications | The complete disaster-response system: an agent combining search, CSP and planning in a dynamic, partially observable world | all of `backend/app/` and the UI | Demo Mode (narrated end-to-end run); Command Center; final statistics report |

---

## Unit 1: Intelligent Agents

**Intelligent agents.** `DisasterResponseAgent` (`backend/app/agents/disaster_agent.py`) is the single decision-maker of the system. It maps percepts to actions for every ambulance and rescue team. Its docstring classifies it as a *model-based, goal-based agent with utility-guided choices*:

* It keeps an internal model, the belief map `self.belief`.
* It formulates explicit goals, the prioritised `self.goals`.
* It chooses among alternatives with a utility function inside the CSP.

The UI's status bar shows its current `ai_state`: `STANDBY`, `ALLOCATING RESOURCES`, `EXECUTING PLAN`, `REPLANNING`, `AWAITING RESOURCES` or `GOALS SATISFIED`.

**Agents and environments.** The PEAS description is part of the agent's docstring and is tabulated in `README.md`.

* **Environment.** The ground-truth `World` (`backend/app/environment/world.py`), advanced by `Simulation.step()` (`backend/app/environment/simulator.py`).
* **Sensors.** Field reports (`EnvironmentReport` from `backend/app/environment/events.py`) and unit sensors covering a Manhattan diamond of radius `SENSOR_RADIUS = 2`.
* **Actuators.** The primitive `ActionType`s in `backend/app/models/actions.py`. `REPLAN` is one of them: a unit whose route was repaired during a tick spends that tick adopting the new plan.

The environment is partially observable (hidden hazards, unreported victims), stochastic, dynamic, sequential, discrete and cooperative multi-unit. Each property is justified against the code in the README's environment table.

**Rational behaviour.** The agent chooses the actions that maximise its expected performance measure given its percepts:

* `compute_priority()` (`backend/app/agents/priority.py`) ranks victims by severity, health deficit, survival window, hazard exposure, waiting time and entrapment, and returns every factor for explanation.
* The allocation CSP maximises `1000 + 20 * priority - ETA` subject to hard constraints such as medical capability, ICU beds and team skills.
* Every route minimises `terrain + 6.0 * danger`, which reduces exposure.
* A waiting critical victim that no idle unit can serve may pre-empt an ALS ambulance from a less urgent mission (`_preempt_for_critical`).

Rationality is bounded on purpose. The CSP sees an attention window of 6 victims and has a 5000-node budget, and goal reporting uses a hysteresis of 1.0 to avoid flip-flopping.

**Agent architecture.** `decide()` runs PERCEIVE, UPDATE_STATE, IDENTIFY_GOALS, CHECK_CONSTRAINTS, PLAN and SELECT_ACTION. After the simulator executes the actions, `observe()` traces EXECUTE and OBSERVE. Each phase appends a one-line summary to `phase_trace`, which drives the live 8-phase strip. Each phase also writes timestamped `DecisionLog` entries (`backend/app/agents/decision_log.py`) with a phase and a level (INFO, DECISION, ALERT, SUCCESS, SEARCH, CSP, REPLAN, EVENT). `tests/test_agent.py::test_decision_cycle_runs_all_eight_phases_in_order` checks the order.

---

## Unit 2: Search

**State-space search.** The high-level problem state is the immutable `WorldState`:

```
(tick, resource_positions, available_resources, remaining_victims,
 blocked_roads, hazard_cells, hospital_capacity, rescue_tasks)
```

It is defined in `backend/app/models/state.py`. Its goal test, `is_goal`, holds when no reported victim remains active. The transition model is `Simulation.execute(action)`. Route finding is formulated separately as `GridSearchProblem` (`backend/app/search/base.py`):

* states are cells;
* actions are N/E/S/W moves allowed by the unit's mobility profile;
* the step cost is `terrain_cost + 6.0 * danger`.

The State tab shows the current `WorldState`, and the Search tab shows the latest route search.

**BFS.** `bfs()` (`backend/app/search/bfs.py`) uses a FIFO frontier and applies the goal test when a node is generated. It returns the path with the fewest steps but ignores costs. In the 100-query URBAN_FIRE benchmark it was optimal in only 54% of the queries and expanded 146.9 nodes on average. The algorithm can be selected for the live agent or compared in the Algorithm Lab.

**Greedy Best-First Search.** `greedy_best_first()` (`backend/app/search/greedy_best_first.py`) orders the frontier by `h(n)` alone. It is the fastest of the three (28.9 and 20.5 average expansions in the two benchmarks), but it is not optimal: its worst path cost was 2.907 times the optimum. Selecting it for the live agent shows that it can route units through dangerous cells.

**A\* search.** `astar()` (`backend/app/search/astar.py`) orders the frontier by `f = g + h` and breaks ties towards smaller `h`, using lazy deletion and a closed set. It is the agent's default (`Simulation(algorithm="ASTAR")`). It was optimal in all 200 benchmark queries while expanding 3.4-4.1 times fewer nodes than BFS. Its explored and frontier cells are drawn as the map's search overlay.

**Heuristic functions.** `manhattan`, `euclidean` and `zero` are defined in `backend/app/search/heuristics.py`. Manhattan is admissible and consistent because every step costs at least `MIN_STEP_COST = 1.0` (`backend/app/environment/mobility.py`) and changes the Manhattan distance by exactly 1. `ALGORITHMS.md` gives the proof, and `tests/test_search.py::test_manhattan_is_admissible_and_consistent` checks it. The Algorithm Lab can switch heuristics; `zero` turns A* into uniform-cost search, which is used as the certified optimum.

**Online search.** `backend/app/search/online.py` implements:

* `repeated_astar`: plans under the free-space assumption, senses after each move, and replans when the plan is contradicted;
* `lrta_star`: Learning Real-Time A*, with one-step look-ahead and `H(s) <- min[c + H(s')]`.

The Algorithm Lab compares both with offline A* for a chosen sensor radius. On the EARTHQUAKE map at radius 1 the costs are 44.2 (repeated A*), 46.2 (LRTA*) and 33.0 (offline A*).

**Search in dynamic and unknown environments.** The live agent plans on a belief map in which hidden damage is believed to be open road. Each cycle it senses around its units, writes changes into the belief map, and validates every open route with `first_blocked_index` and `path_cost_on`. It then repairs routes with a new search from the unit's current position (`_repair_route`). Dynamic events come from three sources: scheduled scenario events, natural fire spread and flood rise, and user events from the UI. The Decision Log shows the full replanning sequence: ENVIRONMENT CHANGE DETECTED, Mission affected, Previous plan invalid, Stopping current plan, A* Search started, New path generated, Checking constraints for revised plan... satisfied. Inside a tick, the unit then spends the tick on "Action selected: REPLAN - ... adopts the new route" and logs "Mission resumed" on the next tick. A reaction between ticks to a user event logs "Mission resumed" at once. A shared trip is also re-checked while it runs: if a patient on board would face a long pick-up detour, a `TRIP_DETOUR` issue ("Rationality check failed: ...") cancels the pending pick-ups. The map animates the old and new routes (`replan_events`).

---

## Unit 3: Constraint Satisfaction

**Constraint satisfaction problems.** `CSP` (`backend/app/csp/solver.py`) supports unary, binary and n-ary capacity constraints (`backend/app/csp/constraints.py`). `build_allocation_problem` (`backend/app/csp/allocation.py`) models rescue resource allocation:

* **Variables.** The waiting victims in the attention window.
* **Domains.** The full Cartesian product of rescue method, ambulance, team and destination, plus the partial `EXTRACT_ONLY` plan (team only) and DEFER. That is 37 values per victim in EARTHQUAKE and 67 in URBAN_FIRE.
* **Constraints.**
  * Unary: method applicability, availability, ALS for critical victims, ICU/ER beds, FIREFIGHTING teams for fire zones, reachability, partial-plan fallback, and critical coverage. Partial-plan fallback allows EXTRACT_ONLY only when no complete plan is feasible. Critical coverage requires a *complete* plan for a critical victim that could have one.
  * Binary: resource conflicts and shared-ambulance same hospital.
  * Global: ambulance seats, team exclusivity, hospital beds.

A second CSP, `build_destination_problem`, re-assigns hospitals when capacity drops. The CSP Solver tab shows each variable with its domain sizes, assigned value, utility and pruning counts, the constraint summary, and the solver statistics.

**Constraint propagation.** Three mechanisms are implemented:

1. `enforce_node_consistency` applies every unary constraint before search. On the first EARTHQUAKE round it removes 166 of 222 values.
2. `ac3` with `_revise` enforces arc consistency on all binary constraints. For example, at EARTHQUAKE tick 47 critical V10 can only be served by ambulance A2, so AC-3 removes the A2 options of V06 and V05 (4 values).
3. `_forward_check` prunes neighbour domains after each assignment. It is generalised to n-ary `CapacityConstraint`s through `CapacityConstraint.prune`, which removes values whose usage exceeds the remaining capacity.

The CSP Solver tab shows the domain size after each stage, and the Decision Log prints "Constraint propagation: node consistency removed N value(s); AC-3 removed M".

**Backtracking search.** `BacktrackingSolver._backtrack` is depth-first assignment:

* MRV variable ordering with a degree tie-break;
* values in descending utility (or LCV for pure satisfaction problems);
* forward checking after every assignment;
* branch-and-bound pruning with an admissible bound, the minimum of a capacity-aware "pooled" bound and the plain best-value bound, which turns the solver into an optimiser;
* a node budget of `CSP_NODE_LIMIT = 5000`. The largest solve in the five scenario runs needed 90 nodes.

When critical victims cannot all be covered, a minimal relaxation drops `critical-coverage` one victim at a time, lowest priority first, and re-solves until the CSP is satisfiable. The CSP Solver tab shows nodes, backtracks, forward-checking prunings, bound prunings and whether the result is proven optimal, plus the phase-1 result when relaxation happened. The generic solver is also tested on map colouring, 8-queens and brute-force-verified optimisation (`tests/test_csp.py`).

---

## Unit 5: Planning

**Planning.** `HierarchicalPlanner` (`backend/app/planning/planner.py`) turns the CSP's decisions into executable plans made of `PlanTask` trees and per-unit agendas. Movement tasks carry concrete paths from the selected search algorithm. On-scene tasks carry durations, and cross-unit ordering is expressed with `depends_on`: a load waits for its extraction. Plans are monitored and repaired during execution by re-routing, aborting and re-queuing, or re-allocating destinations. Critical victims can also pre-empt an ALS ambulance from a less urgent mission. The Mission Plan tab shows the whole tree with live task statuses.

**Goal-based planning.** In `identify_goals()` the agent formulates its goals from the current state: one goal per active known victim, sorted by priority. It logs `Goal formulation: N victim(s) to rescue, M critical` and the most urgent unassigned goal with its factor breakdown. The top-level task is `MISSION: Rescue all reported victims (critical first) and deliver them to suitable care`. The goal test is `WorldState.is_goal`, and the "Check remaining goals" task is marked DONE when it holds.

**Hierarchical planning.** MISSION is decomposed into one `RESCUE_VICTIM` per victim. Each is refined by one of four HTN methods:

* `AMBULANCE_DIRECT`: Assign -> Navigate -> Stabilise & load -> Select hospital -> Transport -> Deliver -> Release.
* `EXTRACT_AND_TRANSPORT`: the team navigates and extracts, then the ambulance navigates, loads, transports and delivers.
* `TEAM_EVACUATE`: the team navigates, extracts and carries, escorts the victim to a hospital or safe zone, and delivers.
* `EXTRACT_ONLY` (partial plan, only when no complete plan is feasible): the team navigates, extracts and is released. The mission achieves the sub-goal "victim freed"; the victim returns to the goal queue, and a later round plans its transport.

The CSP binds each method's parameters. Patients on the same multi-seat ambulance become a shared trip with an optimal pick-up order, and the shared tasks are mirrored into each victim's sub-tree. A trip is rejected at planning time when a patient on board would ride more than 2.0 x the direct cost + 12.0; the highest-priority patient then keeps the ambulance. During execution, pending pick-ups are aborted under the same threshold (`TRIP_DETOUR`). The Mission Plan tab renders this tree; the README shows a real tick-1 decomposition and a shared trip.

**AI applications.** The project applies all of the above to emergency management:

* prioritising casualties by medical urgency;
* matching scarce resources (ALS ambulances, specialised teams, ICU beds) to needs;
* routing safely around hazards;
* adapting to aftershocks, fires, floods, breakdowns and hospital capacity changes.

Demo Mode presents this as a narrated end-to-end run and ends with a statistics report.

---

## No machine learning, LLMs, external AI APIs or path-finding libraries

This was verified by inspecting the dependency files and every import in the backend:

* `backend/requirements.txt`: `fastapi`, `uvicorn[standard]`, `pydantic`. This is the web server and request validation only.
* `requirements-dev.txt`: the above plus `pytest` and `httpx`, for testing only.
* `frontend/package.json`: `react` and `react-dom`, with build tooling (`vite`, `@vitejs/plugin-react`, `typescript`, `tailwindcss`, `@tailwindcss/vite`, `@types/*`).
* Every import in `backend/app/` is from the Python standard library (`heapq`, `collections`, `itertools`, `dataclasses`, `enum`, `math`, `random`, `statistics`, `time`, `threading`, `uuid`, `datetime`, `pathlib`, `typing`, `abc`), from FastAPI/pydantic in the web layer only (`main.py`, `models/schemas.py`), or from the project itself.
* A search for `networkx`, `numpy`, `scipy`, `sklearn`, `torch`, `tensorflow`, `openai`, `anthropic`, `langchain` and `pathfinding` across `backend/`, `tests/`, `requirements-dev.txt` and `frontend/package.json` returns no matches.

Every search, CSP, planning and agent algorithm is implemented from scratch in this repository. No component is learned from data, and no external AI service is called.

---

## How to demonstrate in the viva

Start the system with `./run.sh` and open http://localhost:5173. Tick numbers below refer to the default seeds. The Command Center opens in **Simple view**; for any step that mentions a tab (Decision Log, Mission Plan, CSP Solver, Search, State), the map editor, overlays, hospital or resource panels, first switch to **Advanced view** with the toggle in the header.

| # | Concept | What to do | What to point at |
|---|---|---|---|
| 1 | Intelligent agent, agent architecture | Command Center, scenario EARTHQUAKE, press **Step** once | The 8-phase strip fills PERCEIVE ... OBSERVE with summaries. The Decision Log shows each phase's entries. The status bar AI state changes to ALLOCATING RESOURCES. |
| 2 | PEAS, partial observability | Look at the hidden-hazard markers on the EARTHQUAKE map, then play to about tick 15 | The markers are cells whose true terrain differs from the agent's belief (`belief_diff`). At tick 4 A2 discovers unreported victim V09 ("Unreported victim V09 discovered by A2"). At tick 8 A3's sensor reveals debris at (17, 4), and at tick 15 T1 reveals (12, 9) ("Unknown terrain revealed by sensors"). |
| 3 | Rational behaviour | Open the victim priority list (already filled at tick 0 by `preview_priorities`), then press Step | At tick 1, V01 has priority 65.1: Severity +45.0, Health deficit +11.3, Survival window +4.8, Waiting +0.1, Entrapment +4.0. It is ranked above V02 (62.9). |
| 4 | Goal-based planning | Decision Log at tick 1 | "Goal formulation: 8 victim(s) to rescue, 2 critical" and "Most urgent unassigned goal: rescue V01" |
| 5 | State-space representation | State tab | State tuple fields, `remaining_victims`, `is_goal = false`. `blocked_roads` lists only the debris the agent knows: hidden hazards appear after a sensor finds them. Play to the end: `is_goal = true`. |
| 6 | CSP formulation | Decision Log and CSP Solver tab at tick 1 | "Resource allocation CSP started: 6 victim variable(s), 6 idle unit(s)" (V01, V02, V03, V04, V06, V05; 37 values each; 75 constraints = 50 unary, 15 binary, 10 global). The CSP tab shows this window. Assignments: V01 -> T3 extract + A1 -> H1 (utility 2265), V02 -> A2 -> H1 (2228), V03 -> T1 extract + A3 -> H1 (1873), V04 -> A3 -> H1 (1757). V06 and V05 are deferred. |
| 7 | Constraint propagation | Tick-1 domain-size columns; then EARTHQUAKE at tick 47 | Tick 1: domains 37 -> 12 / 4 / 19 / 7 / 7 / 7 after node consistency. The log reads "node consistency removed 166 value(s); AC-3 removed 0 (30 arc revisions)" (method-applicability -150, partial-plan-fallback -6). At tick 47, critical V10 can only be served by A2, so AC-3 removes the A2 options of V06 and V05 (3 values -> 1 each). |
| 8 | Backtracking, branch-and-bound | CSP Solver tab stats at tick 1 | "Backtracking search: 42 nodes, 13 backtracks, 295 forward-checking prunings, 24 bound prunings ... - optimal", score 8123.4 |
| 9 | Critical-coverage relaxation | Reset EARTHQUAKE. **Before pressing Play** (tick 0), trigger **New emergency** (auto-target). | It adds a third critical victim for two ALS ambulances. The log shows "Phase 1 (hard 'critical-coverage') has no solution: backtracking search proved no consistent assignment exists", then "Relaxing 'critical-coverage' for V02; still required for V10, V01". The CSP tab marks the window as relaxed; V10 and V01 get complete plans. Alternatively, after a reset trigger **Remove ambulance** at tick 0. Phase 1 is refuted by AC-3 alone ("AC-3 emptied the domain of V01 (resource-conflict with V02)"), and coverage is dropped for V02 only. |
| 10 | Hierarchical planning | Mission Plan tab at tick 1 | MISSION -> Rescue Victim V01 [CRITICAL] -> Assign / Navigate T3 / Extract / Release T3 / Navigate A1 / Load (waits for Extract) / Select hospital / Transport / Deliver / Release A1. The V04+V03 shared trip on A3 has mirrored Transport and Deliver tasks in both sub-trees. |
| 11 | Partial plan, sub-goal and critical pre-emption | Keep playing EARTHQUAKE to tick 47 | Tick 30: the new trapped critical V10 gets `T1 extract only (ambulance later)` because no ALS ambulance is idle. Tick 46: "Sub-goal achieved: V10 is free; transport will be allocated in the next round". Tick 47: "Pre-emption: A2 diverted from V05 (MEDIUM) to critical victim V10 (14 away)", then "Assign V10 ... -> A2 -> H2". |
| 12 | Shared-trip detour rule (rationality check) | URBAN_FIRE, play to tick 15 | "Rationality check failed: A3 carries V03 but the pickup detour via V06 costs 42 vs 15 straight to H1", then "Mission for V06 aborted: A3 delivers its patients first." The planning-time version of the rule (the highest-priority patient keeps the ambulance) does not trigger in the default runs; `test_shared_trip_is_rejected_when_the_first_patient_would_ride_a_long_detour` shows it. |
| 13 | A* search, heuristic | Search tab and map search overlay; last-search info | Explored and frontier cells, `h(start)`, nodes expanded, path cost of the latest route |
| 14 | BFS vs. Greedy vs. A* | Algorithm Lab, scenario URBAN_FIRE, suggested endpoints, **Compare** | BFS 257 nodes and Greedy 35 nodes, both cost 54.8 (x1.481, through fire danger). A* 40 nodes, cost 37.0, optimal, 2 extra steps around the fire. |
| 15 | Benchmark | Algorithm Lab, 100-query benchmark | A* optimal rate 1.00. Greedy has the fewest nodes but worst ratio up to about 2.0-2.9. BFS has the most nodes. |
| 16 | Online search | Algorithm Lab, online comparison, EARTHQUAKE, sensor radius 0 / 1 / 2 | At radius 1: offline A* 33.0 vs. repeated A* 44.2 (12 replans) vs. LRTA* 46.2 (11 heuristic updates). Repeated A* approaches the optimum as the radius grows (35.0 at radius 2). |
| 17 | Dynamic replanning inside a tick | DEMO (or Demo Mode) up to tick 10 | Tick 9 log: ENVIRONMENT CHANGE DETECTED -> Mission affected: Ambulance A1 -> Victim V01 -> Previous plan invalid -> Stopping current plan for A1. Replanning... -> A* Search started -> New path generated for A1 -> Checking constraints for revised plan... satisfied -> "Action selected: REPLAN - A1 adopts the new route; mission resumes next tick". Tick 10: "Mission resumed: MOVE - Navigate A1 -> V01". |
| 18 | Dynamic replanning between ticks | Play EARTHQUAKE to tick 10, Pause, **Block road** (auto-target) | The block lands on A1's active route at (12, 8). Alert banner and the same sequence, but because the reaction is between ticks there is no REPLAN action: the log goes straight to "Mission resumed: MOVE - Navigate A1 -> V01". The map shows the replan animation. |
| 19 | Plan repair: resources | At tick 10 (after a reset): **Remove ambulance**; or, after another reset, **Reduce hospital capacity** | Remove ambulance: "Constraint violated (unit unavailable): A1 is out of service", then "Mission for V01 aborted ...". The new CSP keeps team T3 working: "Assign V01 (CRITICAL, ...) -> T3 extract only (ambulance later)". Reduce hospital capacity: "Constraint violated (hospital overbooked): H1 has 3 ER / 0 ICU beds free but 2 ER / 2 ICU patients inbound", then "Destination re-allocation CSP started" and "Destination of V01 changed: H1 -> H2" (V02 likewise). |
| 20 | AI application, end-to-end | **Demo Mode** | Narrated run in this order:<br>- tick 9: aftershock<br>- tick 24: fire<br>- tick 34: new critical victim V10, given `T1 extract only` because no ALS ambulance is free<br>- tick 48: H1 capacity cut; V05 and V06 are re-routed to H2, then A1 is pre-empted for V10<br>- tick 56: "autonomous completion" caption<br>Without user interaction, the backend run of DEMO ends with 10/10 rescued, 0 deceased, complete at tick 97 (V10 delivered at tick 95). |
| 21 | Switching the agent's algorithm | Algorithm selector -> BFS or Greedy, then Play | New routes use the chosen algorithm (log lines read "Breadth-First Search: ..." or "Greedy Best-First Search: ..."). BFS expands many more nodes per search. Greedy expands fewer, but its paths are not guaranteed to be cheapest or safest. |
| 22 | Tests | `.venv/bin/python -m pytest` | 69 passed |
