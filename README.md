# AI Disaster Response Commander: An Intelligent Agent for Autonomous Rescue Planning

An intelligent agent that commands ambulances and rescue teams in a simulated disaster zone (earthquake, urban fire, flood). It perceives a partially known, changing city grid. It prioritises victims, allocates resources by solving a constraint satisfaction problem, routes every unit with informed search, decomposes each rescue into a hierarchical plan, and replans on its own when the world changes.

The project uses only classical AI: an agent architecture, state-space search, constraint satisfaction and hierarchical planning. It has no machine learning, no large language models, no external AI services and no path-finding libraries. Every algorithm is implemented from scratch in Python using only the standard library (`heapq`, `collections.deque`, `itertools`).

Companion documents:

| Document | Contents |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Layers and modules, per-tick data flow, belief vs. ground truth, plan representation, REST API, snapshot format, design trade-offs |
| [`ALGORITHMS.md`](ALGORITHMS.md) | Pseudo-code, complexity and properties of every algorithm, proofs and worked examples |
| [`SYLLABUS_MAPPING.md`](SYLLABUS_MAPPING.md) | Syllabus topic -> code -> UI mapping and a viva demonstration checklist |

---

## Problem statement

After a large disaster, a command centre must decide, continuously and under time pressure:

* which victims to rescue first, given different injury severities and survival windows;
* which ambulance, rescue team and hospital to assign to each victim, given medical capability, team skills, vehicle seats and hospital ER/ICU capacity;
* how each unit should travel through a damaged road network where debris blocks roads, fires spread, flood water rises and some damage has not been reported yet;
* how to repair the plan when a road is blocked, a vehicle breaks down, a hospital loses capacity or new casualties are reported.

The goal of this project is to build an agent that makes these decisions autonomously, explains every decision, and adapts its plan when the environment changes. Throughout the project the problem is modelled as a discrete-time simulation on a grid.

## Motivation

* Disaster response combines the main topics of an introductory AI course in one realistic problem. Routing is a search problem, resource assignment is a CSP, mission execution is a planning problem, and the whole system is an agent acting in a dynamic, partially observable environment.
* Classical AI methods are transparent. Every number the agent uses (priority factors, pruned CSP values, nodes expanded, path costs) can be logged and shown to a human operator. In this domain explainability matters more than raw performance.
* The project contrasts algorithms on identical inputs. BFS, Greedy Best-First and A* run on the same maps, and offline search is compared with online search (repeated A*, LRTA*) when the map is unknown.

## Objectives

1. Design a rational, model-based, goal-based agent with an explicit decision cycle (PERCEIVE -> UPDATE_STATE -> IDENTIFY_GOALS -> CHECK_CONSTRAINTS -> PLAN -> SELECT_ACTION -> EXECUTE -> OBSERVE).
2. Formulate the problem as a state space and implement BFS, Greedy Best-First Search and A* with an admissible, consistent heuristic on danger-aware step costs.
3. Formulate resource allocation as a CSP and solve it with node consistency, AC-3, backtracking (MRV, degree, value ordering), forward checking and branch-and-bound.
4. Decompose the mission goal with HTN-style hierarchical planning into executable per-unit task agendas.
5. Handle dynamic and unknown environments: a belief map, sensors, plan validation, online replanning, and the online algorithms repeated A* and LRTA*.
6. Measure everything: nodes expanded, path cost optimality, CSP nodes, replans, rescue times. Visualise it all in a web interface.

---

## System architecture

### Agent loop

```
 +-------------------------------------------------------------------------------+
 | ENVIRONMENT  ground-truth World: Grid, victims, ambulances, teams, hospitals  |
 |              (backend/app/environment/world.py, simulator.py)                 |
 +-------------------------------------------------------------------------------+
        |  field reports (EnvironmentReport), unit sensors (SENSOR_RADIUS = 2),
        |  unit / victim / hospital telemetry
        v
 +----------------------+   DisasterResponseAgent.perceive()
 | PERCEPTION           |   diff ground truth vs. belief in reported cells and sensor range
 +----------------------+
        v
 +----------------------+   update_state(): belief map (Grid copy), belief_version,
 | STATE REPRESENTATION |   known victims; WorldState = state-space abstraction
 +----------------------+
        v
 +----------------------+   identify_goals(): compute_priority() + assess_needs()
 | GOAL GENERATION      |   -> goals sorted by priority
 +----------------------+
        v
 +----------------------+   check_constraints(): validate every plan on the belief map
 | CONSTRAINT CHECKING  |   -> Issues (ROUTE_BLOCKED, HOSPITAL_OVERBOOKED, ...)
 +----------------------+   plus the resource-allocation CSP (csp/allocation.py)
        v
 +----------------------+   BFS / Greedy / A* on the belief map via RouteOracle
 | SEARCH               |   (route estimates for the CSP, concrete paths for tasks)
 +----------------------+
        v
 +----------------------+   HierarchicalPlanner: MISSION -> RESCUE_VICTIM -> primitive
 | PLANNING             |   tasks; per-unit agendas
 +----------------------+
        v
 +----------------------+   select_actions(): exactly one Action per available unit
 | ACTION SELECTION     |   (MOVE, TRANSPORT, RESCUE, DELIVER_*, WAIT, REPLAN)
 +----------------------+
        v
 +----------------------+   Simulation.execute(): transition model T(s, a)
 | EXECUTION            |   applied to the ground truth
 +----------------------+
        v
 +----------------------+   scheduled / user events, fire spread, flood rise,
 | ENVIRONMENT UPDATE   |   victim deterioration (next tick)
 +----------------------+
        v
 +----------------------+   issue -> repair: re-route, abort & re-allocate,
 | REPLANNING           |   destination re-allocation CSP
 +----------------------+
        |
        +------------------------------> next tick: back to PERCEPTION
```

The diagram follows the conceptual order. In the code, CHECK_CONSTRAINTS validates existing plans. The PLAN phase then repairs them (replanning), runs the allocation CSP for idle units, calls search, and builds HTN plans. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the exact call sequence.

### Backend / frontend split

```
 +---------------------------------- Browser -----------------------------------+
 |  React 19 + TypeScript + Vite + Tailwind CSS v4, canvas map renderer         |
 |  Command Center  |  Algorithm Lab  |  AI Concepts  |  Demo Mode              |
 +------------------------------------------------------------------------------+
                 |  JSON over HTTP: /api/...   (Vite dev server proxies /api -> :8000)
                 v
 +------------------------ FastAPI  (backend/app/main.py) ----------------------+
 |  SessionManager (in-memory, one Simulation per session)                      |
 |  serializers.snapshot()    algorithm_lab: compare / benchmark / online       |
 |  serves frontend/dist when it has been built                                 |
 +------------------------------------------------------------------------------+
                 |
                 v
 +------------------- AI core: pure Python, no web dependencies ----------------+
 |  models/       entities, actions, state (WorldState)                         |
 |  environment/  grid (danger model), mobility, events, scenarios, simulator   |
 |  agents/       DisasterResponseAgent, priority, decision log                 |
 |  search/       BFS, Greedy, A*, heuristics, online (repeated A*, LRTA*)      |
 |  csp/          constraints, BacktrackingSolver, allocation models            |
 |  planning/     HierarchicalPlanner (HTN)                                     |
 +------------------------------------------------------------------------------+
```

### User interface

The web app is one simple screen built around the **Urban Fire** scenario:

* **Map:** the burning city, ambulances, rescue teams, victims and hospitals, with each unit's planned route drawn as a dashed line.
* **Numbers:** victims rescued, victims still waiting, and how many times the AI replanned.
* **How the AI works:** Sense → Decide (CSP) → Plan (A* search) → Act and replan.
* **What the AI is doing:** a plain-language feed of its key decisions and results.
* **Controls:** Start/Pause, Restart, and two buttons to make it harder: **Start a new fire** and **Block a road**. Each one forces the AI to detect the change and replan live.

The other scenarios (Earthquake, Flood, Demo, Custom) and the Algorithm Lab still exist in the backend and its REST API and tests, but the simplified UI only uses the fire scenario.

---

## AI architecture

| Layer | Technique | Where |
|---|---|---|
| Agent | Model-based, goal-based agent with utility-guided choices; 8-phase decision cycle; belief map; plan repair and critical pre-emption | `backend/app/agents/disaster_agent.py` |
| Rationality | Victim priority function (6 explained factors); utility maximisation in the CSP; danger-aware path costs | `backend/app/agents/priority.py`, `backend/app/csp/allocation.py`, `backend/app/environment/mobility.py` |
| Search | BFS, Greedy Best-First, A* (Manhattan, Euclidean, zero heuristics) on a 4-connected grid | `backend/app/search/` |
| Online search | Free-space assumption, sensing, plan validation (`first_blocked_index`), repeated A*, LRTA* | `backend/app/search/online.py`, agent `check_constraints` / `_repair_route` |
| CSP | Node consistency, AC-3, backtracking with MRV + degree, utility/LCV value ordering, forward checking for n-ary capacity constraints, branch-and-bound | `backend/app/csp/solver.py`, `backend/app/csp/constraints.py` |
| CSP models | Resource-allocation CSP (with critical-coverage relaxation) and destination re-allocation CSP | `backend/app/csp/allocation.py` |
| Planning | HTN-style decomposition with three complete methods and one partial method (EXTRACT_ONLY); shared multi-patient trips guarded by a detour rule; per-unit agendas | `backend/app/planning/planner.py` |
| Simulation | Discrete-time transition model, natural dynamics, scripted and user events | `backend/app/environment/simulator.py`, `events.py` |

---

## Intelligent agent design

The agent (`DisasterResponseAgent`) is a single centralised commander that controls all units. Its docstring classifies it as a *model-based, goal-based agent with utility-guided choices*.

### PEAS

| PEAS | Description (based on the PEAS docstring of `backend/app/agents/disaster_agent.py`) |
|---|---|
| **Performance** | Victims rescued (critical first), survival, rescue time, distance travelled, exposure to danger, no constraint violations |
| **Environment** | Dynamic, partially observable disaster grid (roads, buildings, debris, fire, flood water, hospitals, rescue bases, safe zones) with victims, ambulances and rescue teams |
| **Actuators** | Per unit: `MOVE`, `RESCUE`, `TRANSPORT`, `DELIVER_TO_HOSPITAL`, `DELIVER_TO_SAFE_ZONE`, `WAIT`, `REPLAN` |
| **Sensors** | Field / radio reports (`EnvironmentReport`), unit sensors (Manhattan radius `SENSOR_RADIUS = 2`), unit telemetry, hospital status |

`REPLAN` is a real action. In a normal tick, a unit whose route was repaired in that decision cycle is given `Action(REPLAN)` instead of a move. It holds position for that tick (the simulator executes `REPLAN` as a no-op) and resumes on the next tick. Reactions to events injected between ticks (`Simulation.inject`) skip this step; the repaired mission resumes on the next tick without a REPLAN action.

### Environment properties

| Property | Classification | Justification in the code |
|---|---|---|
| Observability | **Partially observable** | The agent plans on a belief map in which hidden hazards (`World.hidden_hazards`) are believed to be open road. They are revealed only when a unit's sensors come within radius 2. Unreported victims (`VictimStatus.UNREPORTED`) are found the same way. Unit positions, victim health and hospital beds are read directly as telemetry once known. |
| Determinism | **Stochastic** | Primitive actions are deterministic (`Simulation.execute`), but exogenous changes are random. Fire spreads with probability `fire_spread_probability`, flood rises on random frontier cells, and new victims get random positions and attributes. All randomness comes from a seeded `random.Random`. |
| Dynamics | **Dynamic** | Victims lose health every tick, and fire, flood and scheduled or user events change the map between decisions. |
| Episodes | **Sequential** | Every assignment and route affects future states, for example a seat used now is unavailable later. |
| State / time | **Discrete** | Grid cells, integer ticks, a finite action set |
| Agents | **Multi-unit, cooperative** | One commander agent controls up to 8 ambulances and 8 teams (the CUSTOM limits). The units cooperate, as in extraction followed by transport or shared trips. There are no adversaries. |
| Knowledge | **Known rules, partially unknown state** | The agent knows the transition model of its own actions and the mobility rules. It does not know hidden damage, unreported victims, or when and where future events will occur. |

---

## State-space representation

### High-level state (`backend/app/models/state.py`)

```
s = (tick, resource_positions, available_resources, remaining_victims,
     blocked_roads, hazard_cells, hospital_capacity, rescue_tasks)
```

`WorldState` is an immutable, hashable dataclass that captures exactly this tuple. Victims appear as `(id, status)`, hospitals as `(id, er_free, icu_free)` and tasks as `(unit id, current task label)`. `capture_state(world, tasks, grid)` builds it. The simulator passes the agent's belief map as `grid`, so `blocked_roads` and `hazard_cells` hold only what the agent has perceived; undiscovered hidden hazards never appear in the state.

| Component | Definition |
|---|---|
| **Initial state** | Scenario at tick 0: units at their starting positions (mostly rescue bases), reported victims `WAITING`, initial debris, fire and water, full hospital capacity |
| **Actions** | A joint action: one primitive `Action` per available unit per tick, namely `MOVE` (one cell, empty), `TRANSPORT` (one cell with patients on board), `RESCUE` (mode `EXTRACT` or `LOAD`, multi-tick), `DELIVER_TO_HOSPITAL`, `DELIVER_TO_SAFE_ZONE`, `WAIT`, `REPLAN` (hold for one tick while adopting a repaired route) |
| **Transition model** | `Simulation.execute(action)` = T(s, a). It checks adjacency and passability on the true map, seats, entrapment and location. It then updates positions, carried patients, victim status and hospital occupancy. The exogenous dynamics are applied in `Simulation.step()`. |
| **Goal test** | `WorldState.is_goal`: `remaining_victims` is empty, so every reported victim is `RESCUED` or `DECEASED`. The simulator reports `COMPLETE` when no known victim is active, no mission is open and no scheduled event remains. |
| **Path cost** | Route level: `cost(n -> m) = terrain_cost(m) + DANGER_WEIGHT * danger(m)` with `DANGER_WEIGHT = 6.0`. Mission level: the performance measure (rescues, survival, rescue time, distance). The CSP approximates it with the utility `1000 + 20 * priority - ETA` (base 600 for a partial EXTRACT_ONLY plan). |

### Route-finding sub-problem (`backend/app/search/base.py`)

| Element | Definition |
|---|---|
| State | Cell `(row, col)` occupied by the moving unit |
| Initial state | The unit's current cell |
| Actions | Move N / E / S / W into a cell that the unit's `MobilityProfile` can enter |
| Transition | The neighbouring cell |
| Goal test | `state == goal` |
| Step cost | `terrain_cost(m) + 6.0 * danger(m)`; every passable terrain costs at least `MIN_STEP_COST = 1.0` |

Terrain costs (`backend/app/environment/mobility.py`). A dash means the cell is impassable.

| Cell type | Ground vehicle (ambulance) | URBAN_SAR team | FIREFIGHTING team | WATER_RESCUE team |
|---|---|---|---|---|
| ROAD, HOSPITAL, RESCUE_BASE | 1.0 | 1.0 | 1.0 | 1.0 |
| SAFE_ZONE | 1.5 | 1.5 | 1.5 | 1.5 |
| OBSTACLE (debris) | - | 4.0 | 4.0 | - |
| FIRE | - | - | 4.0 | - |
| WATER | - | - | - | 2.0 |
| BUILDING | - | - | - | - |

Danger model (`backend/app/environment/grid.py`). Each cell takes the maximum of all contributions:

* Fire: danger by BFS distance to the nearest fire cell is `{0: 1.0, 1: 0.6, 2: 0.3}`.
* Water: a water cell has danger 0.5 and a cell next to water has 0.2.
* Debris: a cell next to debris has danger 0.1.
* Hospitals, rescue bases and safe zones are capped at 0.1.

---

## Breadth-First Search

`backend/app/search/bfs.py`. BFS expands the shallowest node first from a FIFO queue. It applies the goal test when a node is *generated* and keeps one `parents` dictionary that serves as both frontier and explored set.

* Complete on the finite grid.
* Returns the path with the fewest **steps**. It ignores step costs, so with danger-aware costs (or SAFE_ZONE cells at 1.5) its path is not always the cheapest.
* Time and space O(V + E) on a grid with V cells (E <= 4V).

## Greedy Best-First Search

`backend/app/search/greedy_best_first.py`. Greedy best-first search orders the frontier by `f(n) = h(n)` only, using a binary heap with an insertion counter to break ties. The goal test is applied when a node is popped. A node is never added twice, because the explored set plus an in-frontier set prevent it.

* Complete on the finite grid (graph search). Not optimal.
* Usually expands the fewest nodes. In the benchmark below it finds the optimal path in only 55-74% of the queries, and its worst path cost is 2.9 times the optimum.

## A* Search

`backend/app/search/astar.py`. A* orders the frontier by `f(n) = g(n) + h(n)`, where `g` is the exact danger-aware cost. Heap entries are `(f, h, counter, node)`, so ties on `f` go to the smaller `h`, which is the same as the larger `g`. This tie-breaking pushes the search towards the goal. Stale heap entries are skipped lazily through a closed set, and the goal test is applied when the goal is popped.

* Complete. Optimal, because the heuristic is admissible and consistent (next section).
* `zero` as the heuristic turns A* into uniform-cost search (Dijkstra). `algorithm_lab.compare()` uses it as the certified optimum.

## Heuristic function

`backend/app/search/heuristics.py` provides three heuristics:

```python
def manhattan(a, b): return MIN_STEP_COST * (abs(a[0] - b[0]) + abs(a[1] - b[1]))   # default
def euclidean(a, b): return MIN_STEP_COST * math.hypot(a[0] - b[0], a[1] - b[1])
def zero(a, b):      return 0.0                                                    # UCS / Dijkstra
```

**Admissibility.** Every 4-connected move changes the row or the column by exactly 1, so any path from `n` to the goal needs at least `|dr| + |dc|` moves. Every passable cell costs `terrain_cost >= 1.0`, and danger adds `6.0 * danger >= 0`, so each move costs at least `MIN_STEP_COST = 1`. The true remaining cost is therefore at least `|dr| + |dc| = h(n)`.

**Consistency.** For neighbours `n` and `n'`, `|h(n) - h(n')| = 1 <= c(n, n')`, so `h(n) <= c(n, n') + h(n')`. With a consistent heuristic, A* with a closed set never needs to reopen a node. The first time it pops the goal, the path is optimal.

**Weakness.** The heuristic ignores the danger term. It stays admissible, but it is less informed when danger matters. In URBAN_FIRE, A* expands 35.8 nodes on average with danger-aware costs against 21.2 without them (see Results).

The test-suite checks admissibility and consistency on random maps (`test_manhattan_is_admissible_and_consistent`).

---

## Constraint satisfaction problem

Resource allocation is formulated as a CSP in `backend/app/csp/allocation.py` (`build_allocation_problem`).

**Variables.** There is one variable per waiting victim inside the agent's attention window, ordered highest priority first. The window holds `ATTENTION_WINDOW = 6` victims.

**Domains.** Each domain is the full Cartesian product of rescue method, resources and destination, plus `DEFER` (not served this round):

| Method | Value |
|---|---|
| `AMBULANCE_DIRECT` | (ambulance, hospital) |
| `EXTRACT_AND_TRANSPORT` | (rescue team, ambulance, hospital) |
| `TEAM_EVACUATE` | (rescue team, hospital or safe zone) |
| `EXTRACT_ONLY` | (rescue team): a partial plan that frees a trapped victim now, with transport planned in a later round. Allowed only as a fallback (see `partial-plan-fallback`). |
| `DEFER` | not served this round |

The domain size is `|A||H| + |A||T||H| + |T|(|H| + |S|) + |T| + 1`. For EARTHQUAKE (3 ambulances, 3 teams, 2 hospitals, 1 safe zone) this is 6 + 18 + 9 + 3 + 1 = **37 values per variable**. URBAN_FIRE has 64 + 3 = **67**.

**Constraints.**

| Constraint | Kind | Meaning |
|---|---|---|
| `method-applicability` | unary | The method must match the victim's needs (extraction, hospital, road access). `EXTRACT_ONLY` has the same conditions as `EXTRACT_AND_TRANSPORT`: the victim needs extraction and a hospital and is reachable by road. |
| `resource-availability` | unary | Unavailable or busy units cannot be assigned |
| `medical-capability` | unary | Critical victims require an ALS ambulance |
| `icu-capacity` | unary | ICU patients require a hospital with a free ICU bed |
| `hospital-capacity` | unary | Non-ICU patients require a free ER bed |
| `hazard-capability` | unary | Victims in fire danger zones (on fire or danger >= `HAZARD_DANGER_THRESHOLD = 0.6`) require a FIREFIGHTING team |
| `reachability` | unary | Every assigned unit must have a route to the victim, and the carrier must have a route to the destination (checked with the agent's search algorithm) |
| `partial-plan-fallback` | unary | `EXTRACT_ONLY` is allowed only if the victim has no feasible complete plan on its own (`complete_possible[v]`, computed with all the other unary predicates, including the currently idle units) |
| `critical-coverage` | unary | A critical victim with `complete_possible[v]` must receive a complete plan: neither `DEFER` nor `EXTRACT_ONLY`. It is hard at first. If the CSP is unsatisfiable, coverage is dropped one critical victim at a time, lowest priority first, until it becomes satisfiable (minimal relaxation). |
| `resource-conflict(Vi, Vj)` | binary | Two victims must not over-subscribe a shared resource, and patients sharing an ambulance must go to the same hospital |
| `ambulance-capacity[A]` | global | Seats used <= free seats. A critical patient uses all of `A.capacity` (rides alone). |
| `team-exclusive[T]` | global | A team performs at most one task |
| `er-beds[H]`, `icu-beds[H]` | global | Free ER / ICU beds in hospital H |

**Objective.** The solver maximises the sum of `utility(var, value)`:

* `utility = 1000 + 20 * priority - ETA` for a complete plan (`SERVE_BASE_UTILITY = 1000`, `PRIORITY_WEIGHT = 20`).
* `600 + 20 * priority - ETA` for `EXTRACT_ONLY` (`PARTIAL_BASE_UTILITY = 600`), because the goal is only partly achieved.
* `DEFER = 0`.

ETA is estimated from search costs: travel to the victim, plus on-scene time, plus transport to the destination (no transport for EXTRACT_ONLY). The base constants mean that serving a victim always beats deferring it, and a complete plan beats a partial one for the same victim. Among served victims, higher priority and shorter rescue time win.

Because of `partial-plan-fallback`, a partial plan is a genuine fallback: it only appears for a trapped victim that no idle combination of units can serve completely. For example, at DEMO tick 34 the new critical victim V10 gets `T1 extract only` (utility 1874) because no ALS ambulance is free.

A second CSP (`build_destination_problem`) re-assigns hospitals when capacity drops or a transport route is lost. Its domain is the hospitals plus `HOLD`. Its constraints are bed availability, reachability, deliver-loaded-patient (hard first, then relaxed), ER and ICU capacity, and same-carrier-same-hospital.

## Backtracking

`BacktrackingSolver._backtrack` in `backend/app/csp/solver.py` is a depth-first search over partial assignments:

* **Variable ordering.** MRV (smallest current domain) first, with ties broken by the degree heuristic (most unassigned neighbours) and then by priority order.
* **Value ordering.** With a utility, values are tried in descending utility (optimisation). Without one, the least-constraining value (LCV) is tried first (satisfaction).
* **Consistency check.** Every binary and global constraint involving the variable is checked against the partial assignment. Capacity sums only grow, so a partial violation is final.
* **Branch-and-bound.** Once an incumbent exists, a branch is pruned if `score + bound <= best`. The allocation CSP supplies a capacity-aware bound, the minimum of two admissible bounds. The first, "pooled", counts free ambulance seats and free teams separately. The second, "plain", takes the best value per variable. The proof is in `ALGORITHMS.md`.
* **Budget.** The agent runs the solver with `CSP_NODE_LIMIT = 5000`. If the budget is exhausted, the best assignment found so far is returned and marked as not proven optimal.

The generic solver is also tested on Australia map colouring, unsatisfiable 2-colouring, 8-queens and capacity problems. Branch-and-bound is checked against a brute-force optimum on 25 random instances.

## Constraint propagation

The solver propagates constraints in three stages. Each stage reports its removals to the UI.

1. **Node consistency** (`enforce_node_consistency`). Every unary constraint prunes its variable's domain before search. This stage removes most of the Cartesian domain. On the first EARTHQUAKE/DEMO round, 166 of 6 x 37 = 222 values are removed: 150 by `method-applicability`, 8 by `medical-capability`, 6 by `partial-plan-fallback` and 2 by `critical-coverage`.
2. **AC-3** (`ac3`, `_revise`). Arc consistency is enforced over all binary constraints. In the allocation CSP, `DEFER` is compatible with every value, so an arc `(Xi, Xj)` can only lose values when `Xj` has no `DEFER`, which means `Xj` is a critical-coverage variable. AC-3 then removes the options of other victims that would take a resource every remaining option of the critical victim needs. For example, at EARTHQUAKE tick 47, just after A2 was pre-empted, critical V10 had a single remaining option, `A2 -> H2`. AC-3 removed the A2 options of V06 and V05 (4 values). Across the five scenario runs AC-3 removed 5 values in total: 4 in EARTHQUAKE and 1 in DEMO. In the generic tests it also proves inconsistency without any search.
3. **Forward checking** (`_forward_check`). After each assignment, values of unassigned variables that became inconsistent are pruned. This works for binary constraints and also for the n-ary `CapacityConstraint`. It removes every value whose resource usage exceeds the remaining capacity, so a domain wipe-out is detected one level early.

---

## Planning

`backend/app/planning/planner.py` implements goal-based hierarchical (HTN-style) planning. The top-level goal **MISSION** ("rescue all reported victims, critical first, and deliver them to suitable care") is decomposed into one compound task `RESCUE_VICTIM(v)` per victim. The CSP chooses the *method* and its parameters:

| Method | Decomposition |
|---|---|
| `AMBULANCE_DIRECT(v, A, H)` | Assign -> Navigate(A->v) -> Rescue (stabilise & load) -> Select hospital -> Transport(A->H) -> Deliver -> Update resources |
| `EXTRACT_AND_TRANSPORT(v, T, A, H)` | Assign -> Navigate(T->v) -> Extract(T) -> Release T; Navigate(A->v) -> Load (depends on Extract) -> Select hospital -> Transport(A->H) -> Deliver -> Update resources |
| `TEAM_EVACUATE(v, T, D)` | Assign -> Navigate(T->v) -> Rescue (extract & carry) -> Select destination -> Transport (escort) -> Deliver -> Update resources |
| `EXTRACT_ONLY(v, T)` (partial, fallback only) | Assign -> Navigate(T->v) -> Extract -> Release T. When the extraction finishes, the agent closes the mission (`_complete_extraction`, logged "Sub-goal achieved: ... transport will be allocated in the next round"). The victim returns to `WAITING` with `extracted = True`, and the next CSP round plans its transport. |

**Shared trips.** Non-critical patients assigned to the same multi-seat ambulance are merged into one shared trip. The pick-up order is chosen exhaustively over all permutations to minimise total route cost. The shared Transport, Deliver and Update tasks appear as *mirrors* in every victim's sub-tree.

**Detour rule.** A merge is rejected when the first patient's on-board cost exceeds `TRIP_DETOUR_RATIO x direct + TRIP_DETOUR_MARGIN` (2.0 and 12.0). The on-board cost covers the remaining pick-up legs plus the transport; `direct` is the cost straight to the hospital. When this happens, the highest-priority patient of the group keeps the ambulance and is planned alone. The others get a failed plan, logged at INFO level ("shared trip rejected: ... - A takes Vxx (highest priority) alone; the other pick-up waits for the next round"), and go back to the goal queue. No merge is rejected in the five default runs; `tests/test_planning.py::test_shared_trip_is_rejected_when_the_first_patient_would_ride_a_long_detour` exercises the rule.

Primitive tasks are also queued in execution order on each unit's **agenda**, and movement tasks get concrete paths from the selected search algorithm.

Decomposition produced at tick 1 of the EARTHQUAKE and DEMO scenarios. The labels are copied from the agent's Mission Plan:

```
MISSION: Rescue all reported victims (critical first) and deliver them to suitable care
 ├── Identify & prioritise victims
 ├── Rescue Victim V01 [CRITICAL]                        (EXTRACT_AND_TRANSPORT)
 │    ├── Assign Ambulance A1 (ALS) + Team T3 (FIREFIGHTING)
 │    ├── Navigate T3 -> V01
 │    ├── Extract V01 (T3)
 │    ├── Release T3
 │    ├── Navigate A1 -> V01
 │    ├── Load V01 into A1                               (waits for Extract V01)
 │    ├── Select hospital H1 (St. Mary's General)
 │    ├── Transport V01 -> H1
 │    ├── Deliver V01 to St. Mary's General
 │    └── Release A1 · update H1 beds
 ├── Rescue Victim V02 [CRITICAL]                        (AMBULANCE_DIRECT)
 │    ├── Assign Ambulance A2 (ALS)
 │    ├── Navigate A2 -> V02
 │    ├── Stabilise & load V02
 │    ├── Select hospital H1 (St. Mary's General)
 │    ├── Transport V02 -> H1
 │    ├── Deliver V02 to St. Mary's General
 │    └── Release A2 · update H1 beds
 ├── Rescue Victim V04 [HIGH]                            (shared trip V04+V03)
 │    ├── Assign Ambulance A3 (BLS, shared trip)
 │    ├── Navigate A3 -> V04
 │    ├── Stabilise & load V04
 │    ├── Select hospital H1 (St. Mary's General)
 │    ├── Transport V04+V03 -> H1                        (mirror)
 │    ├── Deliver V04+V03 to St. Mary's General          (mirror)
 │    └── Release A3 · update H1 beds                    (mirror)
 ├── Rescue Victim V03 [HIGH]                            (shared trip V04+V03)
 │    ├── Assign Ambulance A3 (BLS, shared trip)
 │    ├── Navigate T1 -> V03
 │    ├── Extract V03 (T1)
 │    ├── Release T1
 │    ├── Navigate A3 -> V03
 │    ├── Load V03 into A3
 │    ├── Select hospital H1 (St. Mary's General)
 │    ├── Transport V04+V03 -> H1                        (mirror)
 │    ├── Deliver V04+V03 to St. Mary's General          (mirror)
 │    └── Release A3 · update H1 beds                    (mirror)
 ├── Rescue Victim V07 [LOW]                             (TEAM_EVACUATE)
 │    ├── Assign Team T2 (URBAN_SAR)
 │    ├── Navigate T2 -> V07
 │    ├── Rescue V07 (extract & carry)
 │    ├── Select safe zone S1 (Central Park)
 │    ├── Escort V07 -> S1
 │    ├── Deliver V07 to Central Park
 │    └── Release T2
 ├── Check remaining goals
 └── Replan if required
```

The resulting agenda of A3 is `[Navigate A3 -> V04, Stabilise & load V04, Navigate A3 -> V03, Load V03 into A3, Transport V04+V03 -> H1, Deliver V04+V03 to St. Mary's General, Release A3 · update H1 beds]`.

A partial plan, from DEMO tick 34. A new trapped critical victim appears while both ALS ambulances are busy, so no complete plan exists:

```
 ├── Rescue Victim V10 [CRITICAL]                        (EXTRACT_ONLY)
 │    ├── Assign Team T1 (URBAN_SAR) - extraction only
 │    ├── Navigate T1 -> V10
 │    ├── Extract V10 (T1)
 │    └── Release T1 · V10 awaits an ambulance
```

T1 frees V10 at tick 47. At tick 48 the agent pre-empts ALS ambulance A1 for V10 (see "Dynamic replanning" below), and a second root, `Rescue Victim V10 [CRITICAL] (attempt 2)`, plans the transport.

The agent also re-checks shared trips while they run. If an ambulance with patients on board faces a pick-up detour above the same threshold, `_check_trip_detours` raises a `TRIP_DETOUR` issue and the pending pick-ups are aborted. See "Dynamic replanning" below.

---

## Online search

Online search happens at two levels.

**1. In the live agent.** The agent starts from the situation report: its belief map is the true map with every hidden hazard set to `ROAD`. This is the free-space assumption for unreported damage. It plans offline on this belief map. Every tick, each available unit senses a diamond of radius `SENSOR_RADIUS = 2`, and any difference from the belief map is written into it. `check_constraints` then re-validates every open movement task with `first_blocked_index`, and a blocked route triggers a fresh search from the unit's current cell. The result is repeated A* on a belief map. The agent also re-checks the cost of active routes. When the cost of the remaining route exceeds the planned cost x `DEGRADE_RATIO = 1.35` + `DEGRADE_MARGIN = 2.0`, it searches again and switches only if the new route is cheaper.

**2. In the Algorithm Lab** (`backend/app/search/online.py`). Two classic online agents start with no map knowledge at all. Every unknown cell, buildings included, is assumed to be open road.

* `repeated_astar`: plans with A* under the free-space assumption, executes one step, senses within the sensor radius, and replans when the remaining plan is contradicted. With sensor radius 0 it learns only by bumping into cells.
* `lrta_star`: Learning Real-Time A* (Korf 1990; AIMA Fig. 4.24). It uses one-step look-ahead, the update `H(s) <- min_a [c(s, a, s') + H(s')]` initialised with Manhattan distance, and moves to the best neighbour.

`algorithm_lab.online_comparison` compares both against offline A* on the fully known map.

## Dynamic replanning

The agent handles changes autonomously during `CHECK_CONSTRAINTS` and `PLAN`. These issue kinds are detected:

| Issue | Trigger | Repair |
|---|---|---|
| `ROUTE_BLOCKED` | The remaining path crosses a cell the unit can no longer enter (belief map) | Re-search from the unit's position (or from the start of an upcoming leg). If there is no route: a navigation leg aborts the mission and re-queues the victim; a transport leg runs the destination CSP. |
| `ROUTE_DEGRADED` | Active-leg cost now > planned x 1.35 + 2.0 | Re-search; the new route is adopted only if it is cheaper |
| `NEEDS_ROUTE` | A leg that previously had no route | Retry the search when the map changes |
| `TRIP_DETOUR` | An ambulance carries patients, and its remaining pick-up legs plus transport cost more than 2.0 x the direct cost to the hospital + 12.0 (logged "Rationality check failed: ..."). If any leg is blocked, the check is skipped and route repair handles it. | Abort the pending pick-ups and re-queue those victims, so the patients on board are delivered first |
| `UNIT_UNAVAILABLE` | Ambulance taken out of service | Abort the affected missions, re-queue the victims and re-solve the allocation CSP. A team that was extracting can continue through an EXTRACT_ONLY plan. |
| `VICTIM_LOST` | Victim died | Abort the mission and free its units |
| `CAPABILITY_VIOLATION` | Victim now in a fire zone without a FIREFIGHTING team, or now needs extraction under `AMBULANCE_DIRECT` | Abort and re-allocate through the CSP |
| `HOSPITAL_OVERBOOKED` | Inbound ER/ICU patients > free beds | Destination re-allocation CSP |

**Replanning inside a tick.** Real decision-log excerpt from the DEMO scenario at tick 9, when the scripted aftershock blocks a road on A1's active route. Messages are verbatim; the timings are machine-dependent. Because the change arrives inside a simulation tick, the repaired unit spends that tick on the `REPLAN` action and resumes on the next one:

```
tick 9   [PERCEIVE]          [SCENARIO] Aftershock: Road (12, 8) blocked
tick 9   [PERCEIVE]          ENVIRONMENT CHANGE DETECTED
                               (12, 8): ROAD -> OBSTACLE (field report)
tick 9   [UPDATE_STATE]      Belief state updated (map v2): 1 cell(s) changed
tick 9   [CHECK_CONSTRAINTS] Mission affected: Ambulance A1 -> Victim V01
                               Previous plan invalid: route 'Navigate A1 -> V01' crosses OBSTACLE at (12, 8) (8 step(s) ahead)
tick 9   [PLAN]              Stopping current plan for A1. Replanning...
tick 9   [PLAN]              A* Search started: A1 (19, 7) -> Victim V01 (7, 15)
tick 9   [PLAN]              A* Search: replan Navigate A1 -> V01 - 20 steps, cost 20.0, 21 nodes expanded, 0.04 ms
tick 9   [PLAN]              New path generated for A1 (21 nodes expanded, 0.04 ms)
                               Previous route: 20 steps (blocked)
                               New route: 20 steps, cost 20.0
tick 9   [CHECK_CONSTRAINTS] Checking constraints for revised plan... satisfied
                               A1 available and assigned to a single task
                               route valid on belief map v2
tick 9   [SELECT_ACTION]     Action selected: REPLAN - A1 adopts the new route; mission resumes next tick
tick 10  [SELECT_ACTION]     Mission resumed: MOVE - Navigate A1 -> V01
```

**Replanning between ticks.** A user event is injected through `Simulation.inject()`. The agent runs its decision cycle with `reactive=True` and does not advance time. No REPLAN action is needed, so the log says "Mission resumed" immediately. Below, **Block road** (auto-target) is triggered in EARTHQUAKE after tick 10 (abridged):

```
tick 10  [PERCEIVE]          [USER] Road (12, 8) blocked
tick 10  [PERCEIVE]          ENVIRONMENT CHANGE DETECTED
tick 10  [UPDATE_STATE]      Belief state updated (map v2): 1 cell(s) changed
tick 10  [CHECK_CONSTRAINTS] Mission affected: Ambulance A1 -> Victim V01
                               Previous plan invalid: route 'Navigate A1 -> V01' crosses OBSTACLE at (12, 8) (6 step(s) ahead)
tick 10  [PLAN]              Stopping current plan for A1. Replanning...
tick 10  [PLAN]              A* Search started: A1 (17, 7) -> Victim V01 (7, 15)
tick 10  [PLAN]              New path generated for A1 (19 nodes expanded, 0.03 ms)
tick 10  [CHECK_CONSTRAINTS] Checking constraints for revised plan... satisfied
tick 10  [SELECT_ACTION]     Mission resumed: MOVE - Navigate A1 -> V01
```

A sensor discovery produces the same sequence. In EARTHQUAKE at tick 15 it starts with `ENVIRONMENT CHANGE DETECTED` (`(12, 9): ROAD -> OBSTACLE (sensor T1)`), followed by `Unknown terrain revealed by sensors: ...`. A1 then spends tick 15 on REPLAN.

Before each repair, `plan()` calls `_issue_resolved` to skip an issue that an earlier repair in the same cycle has already fixed. An example is a transport leg that a destination change has just re-routed.

**Critical pre-emption.** After allocation, `_preempt_for_critical` looks for a `WAITING` critical victim that no idle unit can serve. It acts only when all of these hold:

* no ALS ambulance is idle;
* the victim is reachable by road;
* an ICU bed is free if the victim needs one;
* an idle team able to extract it exists, if extraction is needed (a FIREFIGHTING team for a fire zone).

It then takes the nearest available ALS ambulance that has no patient on board and is serving a non-critical mission. It aborts that ambulance's missions, re-queuing their victims, and runs the allocation again in the same cycle. DEMO tick 48:

```
tick 48  [PLAN]  Pre-emption: A1 diverted from V05 (MEDIUM) to critical victim V10 (12 away)
tick 48  [PLAN]  Mission for V05 aborted: pre-empted: A1 reassigned to critical victim V10. Victim returned to the goal queue for re-assignment.
tick 48  [PLAN]  Assign V10 (CRITICAL, priority 63.9) -> A1 -> H2
tick 49  [PLAN]  Assign V05 (MEDIUM, priority 31.4) -> A3 -> H2
```

V10 is delivered at tick 95 with 34% health. Pre-emption covers only critical victims and ALS ambulances; other committed missions are never re-optimised.

---

## Results

All numbers below were measured by running the backend code directly, with the default seeds and A* unless stated otherwise. **Timings are machine-dependent.** They were measured with Python 3.14 on the developer's machine and are meant only for relative comparison.

### Test suite

`.venv/bin/python -m pytest` reports **69 passed** in about 1 s:

| File | Tests |
|---|---|
| `tests/test_agent.py` | 23 |
| `tests/test_csp.py` | 19 |
| `tests/test_search.py` | 16 |
| `tests/test_planning.py` | 7 |
| `tests/test_api.py` | 4 |

### Full scenario runs

Each run calls `Simulation(scenario)` and steps until the status is `COMPLETE` or `STALLED`. All five runs ended `COMPLETE` ("all known victims resolved") with every known victim rescued. Metrics come from `sim.statistics()` and `sim.agent.metrics`.

| Metric | EARTHQUAKE | URBAN_FIRE | FLOOD | DEMO | CUSTOM |
|---|---|---|---|---|---|
| Ticks to completion | 93 | 63 | 89 | 97 | 198 |
| Rescued / total known victims | 10 / 10 | 9 / 9 | 8 / 8 | 10 / 10 | 8 / 8 |
| Deceased | 0 | 0 | 0 | 0 | 0 |
| Replans (total) | 3 | 3 | 0 | 6 | 2 |
| Route replans | 2 | 1 | 0 | 3 | 0 |
| Reassignments | 1 | 2 | 0 | 1 | 1 |
| Destination changes | 0 | 0 | 0 | 2 | 1 |
| REPLAN actions executed | 2 | 1 | 0 | 3 | 0 |
| Critical pre-emptions | 1 | 0 | 0 | 1 | 0 |
| Hidden hazards discovered | 2 | 0 | 0 | 3 | 1 |
| Unreported victims discovered | 1 | 0 | 0 | 1 | 0 |
| Searches | 259 | 219 | 270 | 267 | 232 |
| Nodes expanded (all searches) | 10,281 | 12,090 | 21,384 | 11,049 | 15,522 |
| CSP runs | 14 | 8 | 6 | 15 | 14 |
| CSP nodes (all runs) | 108 | 132 | 57 | 109 | 81 |
| Largest single CSP solve (nodes) | 42 | 90 | 42 | 42 | 32 |
| Missions created / completed / aborted | 12 / 11 / 1 | 12 / 10 / 2 | 8 / 8 / 0 | 12 / 11 / 1 | 9 / 8 / 1 |
| of which EXTRACT_ONLY (partial) missions | 1 | 1 | 0 | 1 | 0 |
| Total distance (cells moved) | 318 | 230 | 318 | 348 | 438 |
| Average rescue time (ticks, report -> delivery) | 50.3 | 31.8 | 56.8 | 52.6 | 89.0 |
| Failed actions | 0 | 0 | 0 | 0 | 0 |

`Replans` is the sum of route replans, reassignments and destination changes; a pre-emption counts as a reassignment. A completed EXTRACT_ONLY mission counts as a completed mission, and the same victim then gets a second mission for transport. Over a whole scenario, cumulative search time was about 15-31 ms and cumulative CSP time about 5-13 ms. No CSP solve was truncated.

These runs show each kind of adaptation:

* **EARTHQUAKE.**
  * Tick 30: a trapped critical victim (V10) is reported while no ALS ambulance is idle. Its only feasible plan is partial: `T1 extract only (ambulance later)`.
  * Tick 46: T1 frees V10.
  * Tick 47: the agent logs "Pre-emption: A2 diverted from V05 (MEDIUM) to critical victim V10 (14 away)". V10 is assigned `A2 -> H2`, and V05 is re-assigned later.
* **URBAN_FIRE.**
  * Tick 5: V02 enters a fire danger zone while assigned to a URBAN_SAR team. A `CAPABILITY_VIOLATION` aborts the mission.
  * Tick 12: with no complete plan available, V02 gets `T1 extract only` from FIREFIGHTING team T1. A2 takes V02 to H1 after the extraction.
  * Tick 15: A3 carries V03 when the agent logs "Rationality check failed: A3 carries V03 but the pickup detour via V06 costs 42 vs 15 straight to H1". The pending pick-up of V06 is aborted, and V06 is re-assigned to T2 and A4.
* **DEMO.**
  * Tick 34: the new critical victim V10 gets `T1 extract only` because no ALS ambulance is free.
  * Tick 48: the power failure leaves H1 overbooked (2 free ER beds, 4 ER patients inbound). The destination CSP moves V05 and V06 to H2. ALS ambulance A1 is then pre-empted from V05 for V10, which reaches H2 at tick 95 with 34% health.
* **CUSTOM.** Spreading fire cuts off ambulance A2. Its navigation leg to V07 fails, the mission is aborted and re-queued, and the patient already on board (V05) is re-routed from H2 to H1.

### Search algorithm comparison: 100 random queries

`algorithm_lab.benchmark(grid, trials=100, seed=1)` runs on the ground-truth grid of each scenario with a ground-vehicle profile, danger-aware costs and the Manhattan heuristic. Each query has an optimal path of at least 6 steps. The optimum is certified with uniform-cost search (A* with `h = 0`).

**EARTHQUAKE**

| Algorithm | Avg nodes expanded | Avg cost ratio | Max cost ratio | Optimal rate | Avg time (ms) |
|---|---|---|---|---|---|
| BFS | 124.5 | 1.001 | 1.042 | 0.95 | 0.1285 |
| Greedy Best-First | 28.9 | 1.071 | 2.907 | 0.74 | 0.0456 |
| **A\*** | 36.4 | **1.000** | **1.000** | **1.00** | 0.0555 |

**URBAN_FIRE**

| Algorithm | Avg nodes expanded | Avg cost ratio | Max cost ratio | Optimal rate | Avg time (ms) |
|---|---|---|---|---|---|
| BFS | 146.9 | 1.158 | 1.848 | 0.54 | 0.1523 |
| Greedy Best-First | 20.5 | 1.168 | 2.022 | 0.55 | 0.0347 |
| **A\*** | 35.8 | **1.000** | **1.000** | **1.00** | 0.0569 |

Observations:

* A* was optimal in all 200 queries. It expanded 3.4x (EARTHQUAKE) and 4.1x (URBAN_FIRE) fewer nodes than BFS.
* Greedy expanded the fewest nodes but returned paths up to 2.9x the optimal cost.
* BFS minimises steps, not cost. It is near-optimal on EARTHQUAKE, where there is little danger (95%), but optimal in only 54% of the URBAN_FIRE queries, where fire danger dominates path cost.
* With `danger_aware=False` (terrain cost only), the same 100 queries need only 34.3 (EARTHQUAKE) and 21.2 (URBAN_FIRE) A* expansions on average. This is the price of a heuristic that ignores danger. Even in this mode BFS is not always optimal (0.98 / 0.95), because SAFE_ZONE cells cost 1.5.

### Single-query example (`compare()` with the scenario's suggested endpoints)

`lab_map()` suggests a long query from the first ambulance to the farthest reachable victim.

| Scenario, query | Algorithm | Steps | Cost | Nodes expanded | Optimal |
|---|---|---|---|---|---|
| EARTHQUAKE (23, 3) -> (17, 20); UCS reference 213 nodes, cost 33.0 | BFS | 33 | 33.0 | 203 | yes |
| | Greedy | 33 | 33.0 | 45 | yes |
| | A* | 33 | 33.0 | 78 | yes |
| URBAN_FIRE (23, 3) -> (2, 17); UCS reference 258 nodes, cost 37.0 | BFS | 35 | 54.8 | 257 | no (x1.481) |
| | Greedy | 35 | 54.8 | 35 | no (x1.481) |
| | A* | 37 | 37.0 | 40 | yes |

In URBAN_FIRE, A* takes 2 extra steps to avoid the fire. Its path has summed danger 0.0, against 3.3 for the BFS and Greedy paths.

### Online search (EARTHQUAKE ground-truth grid, (23, 3) -> (17, 20), ground vehicle)

| Agent | Sensor radius | Steps | Path cost | Replans | Heuristic updates | Nodes expanded | Cells revealed |
|---|---|---|---|---|---|---|---|
| A* with the full map known (offline) | - | 33 | 33.0 | - | - | 78 | - |
| Repeated A* (free-space assumption) | 1 | 43 | 44.2 | 12 | 0 | 205 | 113 |
| LRTA* | 1 | 45 | 46.2 | 0 | 11 | 45 | 109 |
| Repeated A* | 0 | 47 | 48.2 | 18 | 0 | 268 | 59 |
| LRTA* | 0 | 45 | 46.2 | 0 | 11 | 65 | 60 |
| Repeated A* | 2 | 35 | 35.0 | 11 | 0 | 222 | 160 |
| LRTA* | 2 | 45 | 46.2 | 0 | 13 | 45 | 170 |

Knowing nothing about the map costs repeated A* 34% (radius 1) of extra path cost. A larger sensor radius brings it close to the offline optimum: 35.0 against 33.0 at radius 2. LRTA* does almost no deliberation, with one look-ahead per move, but it never re-plans globally and its trajectory is longer.

### Navigation algorithm inside the full mission

The same scenarios were run with the agent's search algorithm switched. DEMO and CUSTOM were also run under BFS and Greedy. Every one of the 15 scenario/algorithm combinations completed with all known victims rescued and none deceased.

| Scenario | Algorithm | Ticks | Rescued | Replans | Nodes expanded | Distance | Avg rescue time |
|---|---|---|---|---|---|---|---|
| EARTHQUAKE | BFS | 93 | 10 / 10 | 3 | 27,260 | 308 | 49.8 |
| | Greedy | 116 | 10 / 10 | 5 | 10,799 | 354 | 62.3 |
| | A* | 93 | 10 / 10 | 3 | 10,281 | 318 | 50.3 |
| URBAN_FIRE | BFS | 60 | 9 / 9 | 1 | 30,291 | 250 | 33.3 |
| | Greedy | 72 | 9 / 9 | 1 | 4,679 | 262 | 34.7 |
| | A* | 63 | 9 / 9 | 3 | 12,090 | 230 | 31.8 |
| FLOOD | BFS | 85 | 8 / 8 | 0 | 38,047 | 314 | 55.8 |
| | Greedy | 89 | 8 / 8 | 0 | 22,939 | 322 | 57.2 |
| | A* | 89 | 8 / 8 | 0 | 21,384 | 318 | 56.8 |

A* always expands far fewer nodes than BFS. Greedy expands the fewest nodes in URBAN_FIRE, but in EARTHQUAKE its mission is 23 ticks longer. **Mission-level outcomes are still not a controlled comparison of the algorithms**, because runs diverge after the first different route:

* Events without a fixed target are placed on currently active routes. In EARTHQUAKE the tick-16 aftershock blocks (14, 11) under BFS and A* but (12, 12) under Greedy. In URBAN_FIRE the tick-18 fire starts at (11, 23), (11, 18) or (9, 13) depending on the algorithm.
* Fire spread and new-victim placement draw from the same seeded random number generator, so a different history produces different draws.
* Allocation is myopic, and missions are commitments.

Optimal routes per query therefore do not guarantee a shorter mission. See Limitations.

---

## Limitations

* **Telemetry is fully observable.** Partial observability covers only terrain (hidden hazards) and unreported victims. Once a victim is known, the agent reads its exact health and position every tick. Unit positions and hospital beds are also exact.
* **Movement is simplified, and route cost stands in for time.** Every unit moves exactly one cell per tick whatever the terrain. Debris (cost 4.0) or a danger penalty changes route *preference*, not travel time. The CSP's ETA nevertheless adds up route costs, danger penalties included, as if they were ticks. ETAs in dangerous areas are therefore overestimates. There is no traffic, there are no collisions (several units may share a cell), and movement is 4-connected with no diagonals.
* **Bounded rationality.** The CSP sees only an attention window of `ATTENTION_WINDOW = 6` victims at a time, and windows are solved one after another (greedy across windows). Each solve is capped at `CSP_NODE_LIMIT = 5000` nodes. A truncated search returns the best assignment found and labels it "best found within budget". A phase that ends without any solution, even only because the budget ran out, triggers the next relaxation step. The largest solve in the five runs needed 90 nodes.
* **Only limited re-optimisation.** Committed missions are revised only when an issue is detected, plus two targeted mechanisms:
  * Critical pre-emption: a waiting critical victim can take an ALS ambulance that has no patient on board from a non-critical mission.
  * The shared-trip detour rule, at planning time and while running.

  There is no general re-optimisation. For example, a closer BLS ambulance or rescue team that becomes free later will not take over a running mission. The CSP itself does not model the detour rule; it can propose a merge that the planner splits afterwards, keeping the highest-priority patient.
* **The heuristic ignores danger.** Manhattan distance stays admissible, but it is weak when danger dominates. A* expands more nodes in danger-aware mode (35.8 vs. 21.2 in URBAN_FIRE).
* **AC-3 rarely prunes.** `DEFER` supports every value in the binary resource-conflict constraints, so AC-3 can only prune around critical-coverage variables. Over the five scenario runs it removed 5 values. Most pruning comes from node consistency and forward checking.
* **Simple models.**
  * Fire spread is a per-neighbour probability, and flood rise selects random flood-prone cells.
  * Hospitals model only ER and ICU bed counts. There are no treatment times and no discharges.
  * Critical patients always ride alone.
* **Low-severity and trapped victims need rescue teams.** With 0 teams (allowed in CUSTOM), these victims can never be served. This is intended behaviour, and the simulation reports `STALLED`. With `custom={"teams": 0}` it stalls at tick 145 with 5 of 8 victims rescued.
* **Completion counts known victims only.** An unreported victim that no sensor ever passes does not prevent `COMPLETE`. The UI's final report lists such "Victims never discovered". EARTHQUAKE and DEMO are the only scenarios with an unreported victim (V09), and it was found at tick 4 in both.
* **Runs are path-dependent.** Auto-targeted events follow the active routes, and all stochastic processes share one seeded random number generator. Runs with different search algorithms or different user actions are therefore not controlled experiments.
* **Deployment is single-process.** Sessions live in memory (`MAX_SESSIONS = 32`, least-recently-used eviction) and are lost on restart. The API cannot be scaled horizontally. The UI drives the simulation by request/response, not push.
* **Scenarios are synthetic.** They are hand-made 25x25 cities that are deterministic for a given seed, not real map data.

## Future scope

* Incremental search such as D* Lite or Lifelong Planning A* (LPA*) instead of searching again from scratch after every map change.
* A danger-informed admissible heuristic (for example, precomputed lower bounds per region) to recover node efficiency in hazardous maps.
* Travel time that depends on terrain, so that ETA and path cost are separate, and multi-agent path finding with collision and congestion avoidance (for example, conflict-based search).
* General periodic re-optimisation of committed missions, beyond critical pre-emption. Modelling the shared-trip detour rule inside the CSP.
* A probabilistic belief over hazards, so that routes avoid likely-but-unconfirmed damage and sensing is planned actively.
* Richer hospital models (treatment time, discharge, transfers) and evacuation of the safe zones.
* Persistent sessions and push updates (WebSocket) for multi-user command centres. Import of real road networks.

---

## Installation

Requirements: **Python 3.11+** (developed on 3.14) and **Node.js 18+** (developed on 24).

```bash
# Backend (from the project root)
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
# requirements-dev.txt = backend/requirements.txt (fastapi, uvicorn[standard], pydantic) + pytest + httpx

# Frontend
cd frontend && npm install
```

## How to run

**Both servers with one command:**

```bash
./run.sh            # starts the API on :8000 and the UI on :5173
```

On its first run, `run.sh` also creates `.venv`, installs `requirements-dev.txt` and runs `npm install` if these are missing.

**Or separately:**

```bash
# API (http://localhost:8000; interactive API docs at /docs)
cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000

# UI in development mode (http://localhost:5173; Vite proxies /api to port 8000)
cd frontend && npm install && npm run dev
```

**Production-style single server:**

```bash
cd frontend && npm run build          # produces frontend/dist
cd ../backend && ../.venv/bin/uvicorn app.main:app --port 8000
# open http://localhost:8000          (FastAPI serves frontend/dist)
```

**Tests (from the project root):**

```bash
.venv/bin/python -m pytest
```

**Quick tour.**

1. Open the Command Center and press **Demo Mode**, or choose a scenario and press Play.
2. Pause and use **DISASTER EVENT -> Block road** to watch the agent detect the change and replan.
3. Open the **Algorithm Lab** to compare BFS, Greedy and A* on the same map and to run the benchmark and online-search comparisons.

---

## Project structure

```
ai mini project/
├── README.md                     this file
├── ARCHITECTURE.md               system design, data flow, API
├── ALGORITHMS.md                 algorithms, pseudo-code, proofs
├── SYLLABUS_MAPPING.md           syllabus -> code -> UI mapping
├── run.sh                        starts API (:8000) and UI (:5173)
├── requirements-dev.txt          backend requirements + pytest + httpx
├── pytest.ini                    testpaths = tests, pythonpath = backend
├── backend/
│   ├── requirements.txt          fastapi, uvicorn[standard], pydantic
│   └── app/
│       ├── main.py               FastAPI app: REST API + static UI
│       ├── models/
│       │   ├── entities.py       cell types, Victim, Ambulance, RescueTeam, Hospital, SafeZone
│       │   ├── actions.py        ActionType, Action, ActionResult
│       │   ├── state.py          WorldState (state-space state, goal test)
│       │   └── schemas.py        pydantic request bodies
│       ├── environment/
│       │   ├── grid.py           Grid, danger model
│       │   ├── mobility.py       mobility profiles, danger-aware step cost
│       │   ├── events.py         disaster events, auto-targeting, fire spread, flood rise
│       │   ├── scenarios.py      EARTHQUAKE, URBAN_FIRE, FLOOD, DEMO, CUSTOM
│       │   ├── simulator.py      Simulation: tick loop, transition model, statistics
│       │   └── world.py          World (ground truth), Dynamics
│       ├── agents/
│       │   ├── disaster_agent.py DisasterResponseAgent (8-phase cycle, replanning)
│       │   ├── priority.py       victim priority function
│       │   └── decision_log.py   DecisionLog
│       ├── search/
│       │   ├── base.py           GridSearchProblem, SearchResult
│       │   ├── bfs.py
│       │   ├── greedy_best_first.py
│       │   ├── astar.py
│       │   ├── heuristics.py     manhattan, euclidean, zero
│       │   └── online.py         repeated A*, LRTA*, path validation
│       ├── csp/
│       │   ├── constraints.py    Unary/Binary/Capacity constraints
│       │   ├── solver.py         CSP, BacktrackingSolver
│       │   └── allocation.py     resource-allocation and destination CSPs
│       ├── planning/
│       │   └── planner.py        HierarchicalPlanner (HTN), PlanTask
│       └── services/
│           ├── algorithm_lab.py  compare, benchmark, online comparison
│           ├── serializers.py    JSON snapshot of a simulation
│           └── session_manager.py in-memory sessions
├── frontend/                     React 19 + TypeScript + Vite + Tailwind CSS v4
│   ├── package.json
│   ├── vite.config.ts            dev server :5173, /api proxy -> :8000
│   └── src/
│       ├── App.tsx, main.tsx     app shell and page switching
│       ├── pages/                CommandCenter, AlgorithmLab, ConceptsPage
│       ├── components/           MapCanvas, DecisionLog, MissionTree, CspPanel, SearchPanel,
│       │                         SidePanels, StatusBar, ControlBar, Overlays
│       ├── hooks/                useSimulation, useDemoMode
│       ├── lab/                  LabGrid, BarChart
│       ├── services/api.ts       typed REST client
│       ├── simulation/           canvas renderer, theme
│       └── types/api.ts          TypeScript types of the API JSON
└── tests/
    ├── test_search.py
    ├── test_csp.py
    ├── test_planning.py
    ├── test_agent.py
    ├── test_api.py
    ├── helpers.py
    └── conftest.py
```
# aiminiproject
