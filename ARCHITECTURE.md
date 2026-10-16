# Architecture

This document describes how the AI Disaster Response Commander is put together: its layers and modules, what happens in one simulation tick, how the agent's belief state relates to the ground truth, how user events reach the agent, how plans are represented, the REST API, the snapshot format, session management, the frontend layout and the main design trade-offs. Algorithms are covered in [`ALGORITHMS.md`](ALGORITHMS.md).

All paths are relative to the project root.

---

## 1. Layers

```
 frontend/ (React 19 + TypeScript + Vite + Tailwind CSS v4, canvas renderer)
      |
      |  HTTP + JSON  (/api/...)
      v
 backend/app/main.py ............ FastAPI routes, CORS, static hosting of frontend/dist
 backend/app/services/ .......... session_manager, serializers (snapshot), algorithm_lab
      |
      v
 backend/app/environment/simulator.py ... Simulation: tick loop, transition model, statistics
      |                    \
      v                     v
 backend/app/agents/        backend/app/environment/ (world, grid, mobility, events, scenarios)
      |
      +--> backend/app/search/    (BFS, Greedy, A*, heuristics, online search)
      +--> backend/app/csp/       (constraints, solver, allocation models)
      +--> backend/app/planning/  (HTN planner)
      v
 backend/app/models/ ............ entities, actions, state (plain dataclasses / enums)
```

* The **AI core** (`models`, `environment`, `search`, `csp`, `planning`, `agents`) does not import FastAPI or pydantic. The one exception is `models/schemas.py`, which holds the pydantic request bodies and is used only by `main.py`. The core can be used and tested on its own; the tests in `tests/test_search.py`, `test_csp.py`, `test_planning.py` and `test_agent.py` do exactly that.
* The **service layer** turns simulation objects into JSON and manages sessions.
* The **web layer** (`main.py`) is a thin REST adapter. Its request bodies are pydantic models in `backend/app/models/schemas.py`, and its responses are plain dictionaries.

### Module reference

| Module | Key contents |
|---|---|
| `backend/app/models/entities.py` | `CellType` (ROAD, BUILDING, OBSTACLE, FIRE, WATER, HOSPITAL, VICTIM, RESCUE_BASE, SAFE_ZONE) and the one-character `CELL_CODES`. `Severity`, `SEVERITY_RANK`, `SEVERITY_DECAY`. `VictimStatus` (UNREPORTED, WAITING, ASSIGNED, BEING_RESCUED, IN_TRANSIT, RESCUED, DECEASED). `MedicalLevel` (ALS, BLS), `TeamCapability` (URBAN_SAR, FIREFIGHTING, WATER_RESCUE), `UnitStatus`. Dataclasses `Victim`, `Ambulance`, `RescueTeam`, `Hospital`, `SafeZone`. |
| `backend/app/models/actions.py` | `ActionType` (MOVE, RESCUE, TRANSPORT, DELIVER_TO_HOSPITAL, DELIVER_TO_SAFE_ZONE, WAIT, REPLAN), `RescueMode` (EXTRACT, LOAD), frozen `Action`, `ActionResult` |
| `backend/app/models/state.py` | `WorldState` (immutable state-space state with `is_goal`) and `capture_state(world, tasks, grid)`. Terrain facts come from `grid`, which the simulator sets to the agent's belief map. |
| `backend/app/environment/grid.py` | `Grid` (terrain, danger matrix, `version`), `Cell`, danger constants, `PROTECTED_TYPES`, 4-neighbour `DIRECTIONS` |
| `backend/app/environment/mobility.py` | `MobilityProfile`, `GROUND_VEHICLE`, `URBAN_SAR_TEAM`, `FIREFIGHTING_TEAM`, `WATER_RESCUE_TEAM`, `DANGER_WEIGHT = 6.0`, `MIN_STEP_COST = 1.0`, `profile_for(unit)` |
| `backend/app/environment/world.py` | `World` (ground truth, including `hidden_hazards`), `Dynamics` (fire spread, flood rise parameters) |
| `backend/app/environment/events.py` | `EventType`, `USER_EVENT_TYPES`, `DisasterEvent`, `EnvironmentReport`, `RouteHint`, `apply_event()` and its handlers, auto-targeting, `spread_fire()`, `rise_flood()` |
| `backend/app/environment/scenarios.py` | `ScenarioBuilder` (a small layout DSL), the EARTHQUAKE / URBAN_FIRE / FLOOD / DEMO builders, `CustomConfig` with `_custom()`, `build_scenario()`, `list_scenarios()` |
| `backend/app/environment/simulator.py` | `Simulation` (`reset`, `step`, `inject`, `execute`, `statistics`, `state`), `SimulationStatus`, `TIME_LIMIT = 600` |
| `backend/app/agents/disaster_agent.py` | `DisasterResponseAgent`: decision cycle `decide(world, reports, reactive=False)`, plan repair (`_repair_route`, `_issue_resolved`), trip-detour check, allocation with minimal relaxation, critical pre-emption (`_preempt_for_critical`), `preview_priorities`, stall detection. Also `AgentPhase`, `Issue`, `Mission`, `AgentMetrics`. Constants: `SENSOR_RADIUS = 2`, `ATTENTION_WINDOW = 6`, `CSP_NODE_LIMIT = 5000`, `DEGRADE_RATIO = 1.35`, `DEGRADE_MARGIN = 2.0`, `GOAL_HYSTERESIS = 1.0` |
| `backend/app/agents/priority.py` | `compute_priority()`, `survival_window()`, priority weights |
| `backend/app/agents/decision_log.py` | `DecisionLog` (bounded deque, maxlen 3000) of `LogEntry` (seq, tick, time, phase, level, message, details) |
| `backend/app/search/*` | `GridSearchProblem`, `SearchResult`, `bfs`, `greedy_best_first`, `astar`, heuristics, `run_search()`. Online search: `first_blocked_index`, `path_cost_on`, `repeated_astar`, `lrta_star`. |
| `backend/app/csp/constraints.py` | `Constraint`, `UnaryConstraint`, `BinaryConstraint`, `not_equal`, `CapacityConstraint` |
| `backend/app/csp/solver.py` | `CSP`, `BacktrackingSolver`, `SolverStats`, `CSPSolution`, `Removal` |
| `backend/app/csp/allocation.py` | Method constants (`METHOD_DIRECT`, `METHOD_EXTRACT`, `METHOD_EVACUATE`, `METHOD_EXTRACT_ONLY`), `SERVE_BASE_UTILITY = 1000`, `PARTIAL_BASE_UTILITY = 600`, `PRIORITY_WEIGHT = 20`, `HAZARD_DANGER_THRESHOLD = 0.6`. Also `AllocationOption`, `DEFER`, `HOLD`, `RouteOracle`, `VictimNeeds` with `assess_needs()`, `build_allocation_problem(..., require_critical, coverage=None)` (with the `partial-plan-fallback` and `critical-coverage` constraints), `build_destination_problem()`. |
| `backend/app/planning/planner.py` | `TaskKind`, `TaskStatus`, `PlanTask`, `MissionPlan`, `HierarchicalPlanner`, `assign_path()`, shared-trip detour rule `TRIP_DETOUR_RATIO = 2.0`, `TRIP_DETOUR_MARGIN = 12.0` |
| `backend/app/services/algorithm_lab.py` | `lab_map`, `suggested_endpoints`, `compare`, `benchmark`, `online_comparison` |
| `backend/app/services/serializers.py` | `snapshot()`, `cell_info()` |
| `backend/app/services/session_manager.py` | `SessionManager` (`MAX_SESSIONS = 32`) |

---

## 2. Data flow per tick

`Simulation.reset()` builds the scenario, creates the agent and calls `agent.preview_priorities(world)`. That call scores the initially reported victims without any search or logging, so the UI can rank them at tick 0. `Simulation.step()` in `backend/app/environment/simulator.py` then advances the world by one tick. It runs these calls in order:

```
Simulation.step()
 ├─ if status == COMPLETE: return
 ├─ world.tick += 1 ; status = RUNNING
 ├─ tick 1 only: reports += _situation_report()             # SITUATION_REPORT
 ├─ for event in schedule.pop(tick):                         # scripted scenario events
 │     reports += apply_event(world, event, agent.route_hints())
 │     (EventError -> logged "Scheduled event skipped")
 ├─ if tick % dynamics.fire_spread_interval == 0: reports += spread_fire(world)
 ├─ if tick % dynamics.flood_interval == 0:       reports += rise_flood(world)
 ├─ reports += _update_victims()                             # deterioration, death, escalation
 ├─ actions = agent.decide(world, reports)                   # reactive=False
 │     ├─ _begin_cycle(tick)
 │     ├─ perceive(world, reports)        -> Percept         [PERCEIVE]
 │     ├─ update_state(world, percept)                       [UPDATE_STATE]
 │     ├─ identify_goals(world)                              [IDENTIFY_GOALS]
 │     ├─ check_constraints(world)        -> [Issue]         [CHECK_CONSTRAINTS]
 │     ├─ plan(world, issues)                                [PLAN]
 │     │     abort / re-queue -> destination CSP -> _repair_route (unless _issue_resolved)
 │     │       -> _allocate (CSP + HTN) -> _preempt_for_critical -> _allocate again if it acted
 │     └─ select_actions(world)           -> one Action per available unit   [SELECT_ACTION]
 │           (a unit whose route was repaired this cycle gets REPLAN instead of moving)
 ├─ results = [execute(a) for a in actions]                  # T(s, a) on the ground truth
 ├─ agent.observe(world, results)                            [EXECUTE] + [OBSERVE]
 ├─ _record(reports) ; last_actions = ...
 └─ _update_status()                                         # COMPLETE / STALLED / RUNNING
```

Details:

* **Victim update** (`_update_victims`). Every active victim loses health each tick:

  `SEVERITY_DECAY[severity] * factor * (1 + DANGER_DECAY_FACTOR * danger)`

  * `factor` is 0.15 in an ALS ambulance, 0.4 in a BLS ambulance, 0.5 when carried by a team, 0.8 while `BEING_RESCUED`, and 1.0 otherwise.
  * `danger` is 0 while the victim is carried, and `DANGER_DECAY_FACTOR = 1.5`.
  * At health <= 0 the victim becomes `DECEASED`.
  * A `WAITING` victim escalates from MEDIUM to HIGH below 45 health, and from HIGH to CRITICAL below 28. Escalating to CRITICAL also sets `needs_icu`.
* **Execution** (`execute`) checks every action against the ground truth:
  * `MOVE`/`TRANSPORT`: the target must be adjacent and passable for the unit's profile.
  * `RESCUE`: the victim must be active and at the unit's position. An ambulance cannot free a trapped victim. A full carrier cannot load another patient.
  * `DELIVER_*`: the unit must be at the destination.
  * `REPLAN` is a no-op: the unit holds position for this tick while it adopts its repaired route.
  * An illegal action returns `ActionResult(success=False)`. The agent logs it and marks its agenda dirty, which forces route re-validation on the next cycle.
* **Status** (`_update_status`):
  * `COMPLETE` when `tick >= TIME_LIMIT`, or when no known victim is active, no mission is open and no scheduled event remains.
  * `STALLED` when active victims remain, nothing is scheduled and `agent.is_stalled()` is true. That holds in two cases. Either no mission is running and the allocation is exhausted: no idle unit, or an unchanged allocation signature since the last solve. Or missions exist, but every busy unit is holding without a route and nothing new can be allocated.
  * Otherwise `RUNNING`.
* The agent records a trace of all eight phases in `phase_trace` (`test_decision_cycle_runs_all_eight_phases_in_order`). `EXECUTE` and `OBSERVE` are traced by `observe()`, after the simulator has applied the actions.

---

## 3. Belief state vs. ground truth

| | Ground truth | Agent belief |
|---|---|---|
| Object | `World` (`world.grid`, `world.victims`, units, hospitals) | `agent.belief` (a `Grid` copy), `agent.known_victims`, `agent.belief_version` |
| Initialisation | Scenario builder. `hidden_hazards` maps position to its true type (`OBSTACLE`). | `world.grid.copy()` with every hidden-hazard cell set back to `ROAD`, which is the free-space assumption for unreported damage |
| Updated by | Events, fire spread, flood rise, actions | `perceive()` -> `update_state()` only |
| Used for | Executing actions, victim deterioration, statistics | Every search, reachability check, route validation and danger estimate inside the agent, and the terrain part of `WorldState` (`Simulation.state()` passes `agent.belief` to `capture_state`) |

`perceive()` builds a list of `CellChange`s from two sources:

1. **Field reports.** For every cell mentioned in an `EnvironmentReport`, the true type is compared with the believed type. Report-driven changes include scheduled and user events, fire spread and flood rise.
2. **Unit sensors.** Every available unit observes the diamond of Manhattan radius `SENSOR_RADIUS = 2` around itself. Hidden hazards are never mentioned in a report, so this is the only way to discover them. The same check finds `UNREPORTED` victims within radius 2. Such a victim becomes reported and `WAITING`, and `victims_discovered` is incremented.

`update_state()` writes the changes into the belief map, recomputes danger, increments `belief_version`, and replaces the `RouteOracle` so that no cached route survives a map change. Sensor-detected differences increment `hazards_discovered`. The snapshot exposes the difference between the two maps as `belief_diff`, which lets the UI mark undiscovered hazards.

The agent is not fully blind. Once a victim is known, its exact position and health are read from `world.victims`. Unit positions and availability, and hospital beds, are also read directly as telemetry.

---

## 4. Injecting user events

```
POST /api/simulations/{sid}/events {type, target?, params, since}
  -> main.trigger_event: validate type ∈ USER_EVENT_TYPES, build DisasterEvent(source="USER")
  -> Simulation.inject(event)
        report = apply_event(world, event, agent.route_hints())   # ground truth changes now
        agent.decide(world, [report], reactive=True)   # PERCEIVE ... SELECT_ACTION, actions discarded
        _record([report]); last_actions = []
        if status was COMPLETE/STALLED: status = RUNNING
        _update_status()
  -> snapshot(...) + {"report": report.to_dict()}
```

The agent reacts immediately: it perceives, replans and logs `Mission resumed`, all without advancing time. The actions this reactive cycle selects are discarded. Nothing is executed between ticks, so a repaired unit is not given a `REPLAN` action. The next `step()` runs a normal decision cycle, and the unit moves on its new route. Invalid events raise `EventError`, which becomes HTTP 400. Examples are blocking a cell that is not a road, or placing a victim on a building.

**User event types** (`USER_EVENT_TYPES`): `BLOCK_ROAD`, `CLEAR_ROAD`, `START_FIRE`, `ADD_VICTIM`, `REMOVE_AMBULANCE`, `REDUCE_HOSPITAL_CAPACITY`, `NEW_EMERGENCY`, `SET_CELL` (map editor; ROAD, BUILDING, OBSTACLE, FIRE or WATER), `FLOOD_CELLS`.

**Auto-targeting.** When no target is given, `apply_event` chooses one from `agent.route_hints()`, which lists the remaining paths of open movement tasks:

| Event | Target chosen when omitted |
|---|---|
| `BLOCK_ROAD` | Active routes are tried first, longest first; routes shorter than 6 cells are skipped. On that route the target is a free road cell at about 40% of its length, at least 3 steps ahead of the unit and 2 before the end, **such that a detour still exists** (BFS reachability check). Fallback: a random reachable road cell. |
| `START_FIRE` | A free building next to a route cell between one third of the route and 2 cells before its end. Fallback: a random building. The fire immediately spreads to `params.spread` (default 1) neighbouring cells, roads first. |
| `REMOVE_AMBULANCE` | A busy ambulance that carries no patient, then any busy one, then any available one. Patients on board are left at its position as `WAITING`. |
| `REDUCE_HOSPITAL_CAPACITY` | The hospital targeted by the most active transport routes, otherwise the one with the most free beds. Default cut: `er = 3`, `icu` = all free ICU beds. Capacity never drops below occupancy. |
| `ADD_VICTIM`, `NEW_EMERGENCY` | A random free road cell with danger < 0.3 that a ground vehicle can reach from a hospital (from a base if there is no hospital). `NEW_EMERGENCY` ignites the nearest building within distance 2. It then adds a CRITICAL (trapped), a HIGH and a MEDIUM victim on nearby road cells with danger < 0.6. |

Hidden hazards are never part of any `EnvironmentReport`. `CLEAR_ROAD` and `SET_CELL` remove the cell from `world.hidden_hazards`.

---

## 5. Plan representation

### Mission tree

The agent owns a `PlanTask` tree rooted at `M0`:

```
M0  MISSION: Rescue all reported victims (critical first) and deliver them to suitable care
 ├── M1  Identify & prioritise victims        (note: "N active · M critical · top Vxx")
 ├── <RESCUE_VICTIM root per mission>         inserted before M2 by _commit()
 ├── M2  Check remaining goals                (DONE when no victim and no mission remains)
 └── M3  Replan if required                   (DONE after the first replan, note shows count)
```

Each `RESCUE_VICTIM` root is built by `HierarchicalPlanner` and holds its sub-tasks as `children`. The labels and methods are listed in `README.md` and `ALGORITHMS.md`. Completed missions stay in the tree with status `DONE`. Aborted missions become `CANCELLED`, with a note giving the reason.

A victim can own several roots over time. An `EXTRACT_ONLY` mission ends when the extraction finishes (`_complete_extraction`); its root becomes `DONE` with the note "extracted at tick N - transport goes back to the goal queue". The transport mission planned later gets a new root labelled `Rescue Victim Vxx [SEV] (attempt 2)`.

### PlanTask fields

| Field | Purpose |
|---|---|
| `id`, `kind`, `label`, `status`, `note` | Identity. `TaskKind` is one of MISSION, IDENTIFY_VICTIMS, RESCUE_VICTIM, ASSIGN_RESOURCES, NAVIGATE, EXTRACT, RESCUE, SELECT_DESTINATION, TRANSPORT, DELIVER, UPDATE_RESOURCES, CHECK_GOALS or REPLAN. `TaskStatus` is one of PENDING, ACTIVE, DONE or CANCELLED. |
| `mission_id`, `unit_id`, `victim_ids`, `target`, `target_id` | What the task concerns |
| `path`, `path_index`, `path_cost`, `step_costs`, `algorithm`, `nodes_expanded` | Movement tasks: the concrete route from the search algorithm and the progress along it |
| `duration`, `progress` | On-scene tasks (EXTRACT, RESCUE) |
| `depends_on` | Ordering across units. `Load Vxx into Ay` depends on `Extract Vxx (Tz)`. |
| `children` | The HTN decomposition |
| `mirrors`, `mirror_of` | Shared trips: one primary Transport, Deliver and Update task executes, and a mirror appears in every passenger's sub-tree. `set_status` and `sync_mirrors` keep the copies identical. |
| `replans`, `needs_route` | Repair bookkeeping. `needs_route` means the unit holds position until a route exists. |

### Per-unit agendas

`agent.agendas[unit_id]` is the ordered list of primitive tasks the unit will execute. Examples:

* A1: `Navigate A1 -> V01`, `Load V01 into A1`, `Transport V01 -> H1`, `Deliver ...`, `Release A1 · update H1 beds`.
* T3: `Navigate T3 -> V01`, `Extract V01 (T3)`, `Release T3`.
* T1 on a partial plan: `Navigate T1 -> V03`, `Extract V03 (T1)`, `Release T1 · V03 awaits an ambulance`.

Action selection walks the agenda:

* `_current_task` skips finished tasks and completes *instant* tasks (`ASSIGN_RESOURCES`, `SELECT_DESTINATION`, `UPDATE_RESOURCES`) without spending a tick. It activates the next task, and re-searches a leg if the unit is not on its path.
* `select_actions` first checks whether the unit's route was repaired in this cycle. In a normal (non-reactive) cycle such a unit gets `Action(REPLAN)` and holds position; on the next tick it logs `Mission resumed: ...`. Otherwise `_action_for` maps the current task to one `Action`:

| Current task | Action |
|---|---|
| Route repaired in this tick (non-reactive cycle) | `REPLAN` ("adopt new route for '...'") |
| `needs_route` set | `WAIT` ("holding: no route available") |
| Unfinished `depends_on` | `WAIT` ("waiting for: Extract V01 (T3)") |
| NAVIGATE / TRANSPORT | `MOVE` to `path[path_index + 1]`, or `TRANSPORT` if the unit carries patients |
| EXTRACT | `RESCUE` with mode `EXTRACT`, `duration = rescue_time` |
| RESCUE | `RESCUE` with mode `LOAD` (`duration = 1` after an extraction, else `rescue_time`) |
| DELIVER | `DELIVER_TO_HOSPITAL` or `DELIVER_TO_SAFE_ZONE` |
| No open task | `WAIT` ("standby") |

`observe()` advances `path_index`, marks tasks `DONE` and completes missions on delivery, or on extraction for an `EXTRACT_ONLY` mission.

### Missions and caches

* `agent.missions` maps a victim id to its `Mission`: the CSP's `AllocationOption`, the root task, the creation tick, the attempt number and the status. `mission_history` keeps every mission, including aborted ones.
* `RouteOracle` memoises search results by `(start, goal, profile)`. The cache is valid for one belief-map version and is rebuilt on every belief change, or once it exceeds 4000 entries.
* The **allocation signature** is a tuple of the waiting victims, idle units, `belief_version`, the hospitals' free beds and the set of extracted waiting victims. The allocation CSP is solved again only when this signature changes. Stall detection uses the same signature (see `ALGORITHMS.md`).

---

## 6. REST API

All routes are defined in `backend/app/main.py`. FastAPI also serves interactive OpenAPI docs at `/docs`. CORS allows `http://localhost:5173` and `http://127.0.0.1:5173`.

| Method | Path | Body / query | Purpose |
|---|---|---|---|
| GET | `/api/health` | none | Liveness check and number of sessions |
| GET | `/api/meta` | none | Algorithms (`BFS`, `GREEDY`, `ASTAR` with labels), heuristics, mobility profiles, user event types, scenario list |
| GET | `/api/scenarios` | none | Scenario descriptions and challenges |
| POST | `/api/simulations` | `{scenario, seed?, algorithm, custom?}` | Create a session and return its snapshot. `custom` is validated by `CustomScenarioConfig`: 12-40 rows/cols, 1-25 victims, 1-8 ambulances, 0-8 teams, 1-4 hospitals, and so on. |
| GET | `/api/simulations/{sid}` | `?since=<log seq>` | Current snapshot. Only log entries newer than `since` are included. |
| POST | `/api/simulations/{sid}/step` | `{steps: 1-50, since}` | Advance `steps` ticks, stopping early at COMPLETE or STALLED |
| POST | `/api/simulations/{sid}/reset` | none | Rebuild the scenario (same seed and algorithm) |
| POST | `/api/simulations/{sid}/algorithm` | `{algorithm, since}` | Switch the agent's search algorithm (BFS / GREEDY / ASTAR) |
| POST | `/api/simulations/{sid}/events` | `{type, target?: [r, c], params, since}` | Inject a user event. Returns the snapshot plus `report`. |
| GET | `/api/simulations/{sid}/cells/{row}/{col}` | none | Cell inspector: true type, danger, traversal cost per mobility profile, believed type, `known_to_agent`, occupants, facility |
| DELETE | `/api/simulations/{sid}` | none | Delete a session |
| GET | `/api/lab/map` | `?scenario&seed&session_id` | Lab map: cell codes, danger, suggested start and goal, victims, hospitals, units. With `session_id`, the live agent's belief map is used. |
| POST | `/api/lab/compare` | `{scenario, seed?, session_id?, start, goal, profile, danger_aware, heuristic}` | BFS vs. Greedy vs. A* on one query, with traces, metrics, and the optimum certified by UCS |
| POST | `/api/lab/benchmark` | `{..., trials: 1-200, bench_seed, profile, danger_aware, heuristic}` | Random-query benchmark summary per algorithm |
| POST | `/api/lab/online` | `{..., start, goal, profile, sensor_radius: 0-5}` | Offline A* vs. repeated A* vs. LRTA* |
| GET | `/assets/*`, `/{path}` | none | Built UI (only registered when `frontend/dist` exists). Unknown paths fall back to `index.html`. |

Errors: `404` for an unknown or evicted session, `400` for an invalid event, target, algorithm, scenario or lab query, and `422` for request bodies that fail pydantic validation.

---

## 7. Snapshot JSON

`serializers.snapshot(sim, session_id, since)` returns one dictionary per request:

| Field | Content |
|---|---|
| `session_id`, `scenario`, `tick`, `status`, `end_reason`, `algorithm` | Session and scenario metadata (`scenario` = `ScenarioInfo.to_dict()`: id, name, description, challenges, recommended_algorithm, seed, demo) |
| `grid` | `{rows, cols, cells, danger, version}`. `cells` is a list of strings using the codes `.` road, `#` building, `X` debris, `F` fire, `~` water, `H` hospital, `B` base, `S` safe zone. `danger` holds integer percentages. |
| `belief_version`, `belief_diff` | Agent map version and the cells where belief differs from truth: `[{pos, belief, truth}]` |
| `victims` | id, pos, severity, health, health_status, status, priority, `priority_breakdown`, trapped, extracted, needs_icu, rescue_time, rescue_progress, required_resources, carrier_id, destination_id, assigned_units, reported, reported_tick, rescued_tick, deceased_tick |
| `ambulances`, `teams` | id, kind, pos, capacity, medical, capability, available, status, carrying, distance |
| `hospitals` | ER/ICU capacity, occupancy and free beds, plus `inbound_er` / `inbound_icu` from the agent's missions |
| `safe_zones`, `bases` | Facilities |
| `plans` | Per unit: `current_task`, `current_kind`, `mission`, `legs` (task_id, kind, active, remaining path, cost, replans, label), `waiting_for`, `holding` |
| `mission_tree` | `agent.root.to_dict()`, the HTN tree. Movement tasks add path_cost, steps and algorithm; on-scene tasks add duration and progress; `shared` marks mirrors. |
| `log`, `log_seq` | Decision-log entries newer than `since`, and the latest sequence number |
| `phase_trace` | The phases of the last cycle, each with a one-line summary |
| `alerts` | Alerts of the last cycle (codes `ENV_CHANGE`, `PLAN_INVALID`, `RESUMED`) |
| `replan_events` | Route changes of the last cycle: unit, task, reason, blocked cell, old and new path |
| `last_search`, `search_history` | The last logged search with explored and frontier trace, purpose, unit and profile; the 12 most recent searches without traces |
| `last_csp` | The CSP report written last in the cycle. An allocation stores its highest-priority attention window that assigned something, otherwise its first window. A destination re-allocation stores its own report. When both run in one cycle, the later one wins: the allocation runs after the destination CSP, and again after a pre-emption. The full report includes kind, result, optimal, score, relaxed and phase-1 result, per-variable domain sizes (initial / after node consistency / after AC-3), assignment, utility, pruning counts, constraint summary, solver stats, removal samples |
| `stats` | `Simulation.statistics()`: victim and unit counts, hospital totals, current mission, `ai_state`, replanning count, total distance, rescue times, agent metrics |
| `state` | `WorldState.to_dict()` including `is_goal`. Its blocked roads and hazards come from the agent's belief map. |
| `events`, `last_actions`, `upcoming_events` | The last 40 environment reports, the actions executed in the last tick with success and message, and the scheduled events still to come |

The `?since=` mechanism lets the UI fetch only new log entries on every poll or step.

---

## 8. Session management

`backend/app/services/session_manager.py`:

* Each browser session owns one `Simulation`. Session ids are `uuid4().hex[:12]`.
* Sessions are kept in an `OrderedDict` and evicted least-recently-used once there are more than `MAX_SESSIONS = 32`. `get()` refreshes recency.
* Each session has a `threading.Lock`. Every route that reads or mutates a simulation (step, reset, algorithm, events, cell, snapshot, lab requests on a live session) holds that lock, so concurrent requests cannot interleave a tick.
* Everything lives in process memory. Restarting the server discards all sessions, and running several worker processes would split them.

---

## 9. Frontend structure

The UI lives in `frontend/` and uses React 19, TypeScript, Vite and Tailwind CSS v4. The map is drawn on an HTML canvas. In development, Vite serves on port 5173 and proxies `/api` to `http://localhost:8000` (`frontend/vite.config.ts`). In production, `npm run build` writes `frontend/dist`, which FastAPI serves itself.

`frontend/src/` is organised by responsibility:

| Folder | Role |
|---|---|
| `App.tsx`, `main.tsx` | Application shell and page switching |
| `pages/` | The three pages: `CommandCenter` (renders a Simple or an Advanced view; the toggle lives in `App.tsx`), `AlgorithmLab`, `ConceptsPage` |
| `components/` | UI pieces of the Command Center: `MapCanvas`, `SimpleView` (compact cycle strip, activity feed, key numbers, one-row controls for the Simple view), `DecisionLog`, `MissionTree`, `CspPanel`, `SearchPanel`, `SidePanels`, `StatusBar`, `ControlBar`, `Overlays` (alert banner, captions, final report) |
| `hooks/` | React state and playback logic: `useSimulation` (session, play/pause/step, alert banner) and `useDemoMode` (demo sequencing and narration) |
| `lab/` | Algorithm Lab widgets: `LabGrid` (animated search grid) and `BarChart` |
| `services/` | `api.ts`, the typed HTTP client for the REST API above |
| `simulation/` | `renderer.ts` and `theme.ts`: canvas drawing of the disaster map, paths and search overlays |
| `types/` | `api.ts`, TypeScript types mirroring the snapshot and lab JSON |

The backend is the single source of truth. The frontend keeps no AI logic: everything it shows, from priorities and CSP domains to explored cells and replans, comes from the snapshot or lab responses.

---

## 10. Design decisions and trade-offs

| Decision | Rationale | Trade-off |
|---|---|---|
| Algorithms written from scratch in pure Python (`heapq`, `deque`) | Transparent, matches textbook pseudo-code, no hidden behaviour, every node can be traced | Slower than compiled libraries. Not a problem at 25x25 (sub-millisecond searches). |
| AI core independent of the web layer | Unit-testable, reusable, clear layering | Serialisation code (`serializers.py`) has to mirror the domain objects |
| Two-level state space (`WorldState` for the mission, `GridSearchProblem` per route) | Makes the high-level problem explicit while keeping route search tractable | `WorldState` is an abstraction for display and the goal test, built from the belief map. The agent does not search over it directly. |
| Separate belief map | Makes partial observability and online replanning real, since hidden damage must be sensed | The agent needs explicit validation (`first_blocked_index`) and cache invalidation on every belief change |
| Full Cartesian CSP domains, then node consistency | Shows the size of the raw problem and how much each constraint prunes (visible in the CSP Solver tab) | More values are generated than strictly needed. They are pruned immediately. |
| Utility + branch-and-bound inside the CSP | Turns satisfaction into optimisation: serve the highest-priority victims first, with the fastest feasible assignment | Needs an admissible bound. A problem-specific bound, `min(pooled, plain)`, keeps the search small. |
| Partial `EXTRACT_ONLY` plans (base utility 600), restricted by `partial-plan-fallback` to victims with no feasible complete plan | A team can free a trapped victim now, even with no ambulance free (for example after a breakdown), and transport follows in a later round. Partial plans never displace a complete one. | One more value per team in every domain, removed by node consistency when not needed. A partial plan delays transport until a later round. |
| Attention window (6) and node budget (5000) | Bounded rationality keeps every decision cycle fast and predictable | Assignments across windows are greedy. A truncated solve is not proven optimal. |
| HTN with four fixed methods (three complete, one partial) chosen by the CSP | Plans are explainable and always executable. Planning cost is linear in the number of assigned victims (plus `k!` orders for a shared trip of `k` patients). | Less general than STRIPS/PDDL planning. New rescue procedures require a new method. |
| Shared-trip detour rule (2.0 x direct + 12.0), at planning time and while running | Patients already on board are not dragged on long detours. When a merge is split, the highest-priority patient keeps the ambulance. | The CSP does not know the rule, so a merge it proposes can be split afterwards. The running check skips blocked legs and leaves them to route repair. |
| Minimal relaxation of `critical-coverage` (drop the lowest-priority critical victim first) | Keeps as many critical victims covered as the resources allow | One extra CSP solve per dropped victim |
| Critical pre-emption (`_preempt_for_critical`) | A waiting critical victim that no idle unit can serve can take an ALS ambulance from a non-critical mission, provided no patient is on board. In DEMO, V10 reaches hospital at tick 95 with 34% health. | Narrow by design: only critical victims and only ALS ambulances. The displaced victim waits for a new assignment, and other missions are never re-optimised. |
| `REPLAN` as an action inside a tick | Makes plan repair visible as the agent's own action, and the unit spends the tick switching plans | Costs one tick of movement per repair. Reactive cycles between ticks skip it. |
| Missions as commitments, repaired on detected issues | Stable plans, readable logs, no oscillation (also `GOAL_HYSTERESIS` for goal reporting) | Apart from critical pre-emption, misses improvements that appear later, such as a closer unit becoming free |
| Memoised `RouteOracle` and allocation signature | Avoids repeated identical searches and CSP solves when nothing changed | Correctness depends on invalidating on every belief or resource change, which is done through `belief_version` and the signature |
| Event auto-targeting on active routes | Demonstrations reliably trigger replanning, and a detour is guaranteed to exist | Mission-level outcomes become path-dependent, so runs with different algorithms are not controlled experiments |
| REST + JSON snapshots with incremental logs | Simple, stateless HTTP, easy to test (`tests/test_api.py`) | Polling and step requests rather than server push. A full snapshot per request (fine for 25x25). |
| In-memory sessions with per-session locks | Zero infrastructure, safe concurrent requests | No persistence, single process only |
| Seeded `random.Random` per scenario | Reproducible runs, testable results | Different decisions consume random numbers differently, so the stochastic events still diverge between runs |
