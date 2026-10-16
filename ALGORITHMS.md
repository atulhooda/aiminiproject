# Algorithms

This document gives pseudo-code, complexity and properties for every algorithm in the project. The pseudo-code follows the Python implementation closely; function names are the real ones. All constants are copied from the source files.

Notation: the grid has `R x C` cells, `V = R*C` and `E <= 4V` (4-connected moves). `n` is the number of CSP variables, `d` the maximum domain size and `e` the number of binary constraints.

---

## 1. Route-finding problem and cost function

### 1.1 Problem (`backend/app/search/base.py`)

`GridSearchProblem(grid, start, goal, profile, danger_aware=True)`:

* `successors(s)`: for each 4-neighbour `m` of `s` (order N, E, S, W from `DIRECTIONS`), yield `(m, step_cost(m))` if the profile can enter `m`.
* `is_goal(s)`: `s == goal`.
* `path_cost(path)`: the sum of step costs, or `None` if a step is not adjacent or not passable.

### 1.2 Danger model (`backend/app/environment/grid.py`, `Grid.recompute_danger`)

```
danger ← 0 everywhere
# fire: multi-source BFS from all FIRE cells, up to distance 2 (through any terrain)
for cell p at BFS distance d ∈ {0,1,2} from the nearest fire:
    danger[p] ← max(danger[p], FIRE_DANGER_BY_DISTANCE[d])     # {0: 1.0, 1: 0.6, 2: 0.3}
for every WATER cell w:
    danger[w] ← max(danger[w], WATER_CELL_DANGER = 0.5)
    for each non-water neighbour n: danger[n] ← max(danger[n], WATER_ADJACENT_DANGER = 0.2)
for every OBSTACLE cell o:
    for each neighbour n: danger[n] ← max(danger[n], DEBRIS_ADJACENT_DANGER = 0.1)
for every HOSPITAL, RESCUE_BASE, SAFE_ZONE cell p:
    danger[p] ← min(danger[p], 0.1)                              # hardened shelters
```

The danger matrix is recomputed whenever terrain changes, in O(V). The agent keeps its own danger matrix on the belief map.

### 1.3 Danger-aware step cost (`backend/app/environment/mobility.py`)

```
cost(n -> m) = terrain_cost_profile(type(m)) + DANGER_WEIGHT * danger(m)        DANGER_WEIGHT = 6.0
```

| Terrain | GROUND_VEHICLE | URBAN_SAR | FIREFIGHTING | WATER_RESCUE |
|---|---|---|---|---|
| ROAD, VICTIM, HOSPITAL, RESCUE_BASE | 1.0 | 1.0 | 1.0 | 1.0 |
| SAFE_ZONE | 1.5 | 1.5 | 1.5 | 1.5 |
| OBSTACLE | impassable | 4.0 | 4.0 | impassable |
| FIRE | impassable | impassable | 4.0 | impassable |
| WATER | impassable | impassable | impassable | 2.0 |
| BUILDING | impassable | impassable | impassable | impassable |

With `danger_aware=False` the cost is the terrain cost alone. This is used only by the Algorithm Lab toggle and some tests. Every passable terrain costs at least `MIN_STEP_COST = 1.0`, and danger is non-negative, so **every step costs at least 1**. The heuristic proofs below depend on this fact.

For example, a road cell next to a fire costs 1.0 + 6.0 x 0.6 = 4.6 for an ambulance. A burning cell costs 4.0 + 6.0 x 1.0 = 10.0 for a firefighting team.

---

## 2. Breadth-First Search (`backend/app/search/bfs.py`)

```
function BFS(problem):
    parents ← {start: None}                      # doubles as "reached" set
    frontier ← FIFO queue [start]
    if is_goal(start): return [start]
    while frontier not empty:
        node ← frontier.popleft();  expanded += 1
        for (child, _) in successors(node):
            if child ∈ parents: continue         # already in frontier or explored
            parents[child] ← node
            if is_goal(child):                   # early goal test on generation
                return reconstruct_path(parents, child), cost = path_cost(path)
            frontier.append(child)
    return failure
```

* **Complete**: yes, on a finite graph.
* **Optimal**: for the number of steps only. It is optimal in cost only when all step costs are equal. With danger-aware costs, or SAFE_ZONE cells at 1.5, it can return a more expensive path. Measured on 100 URBAN_FIRE queries, it was optimal 54% of the time.
* **Time / space**: O(b^d) in general; on the grid O(V + E) = O(V), each cell being enqueued at most once.

## 3. Greedy Best-First Search (`backend/app/search/greedy_best_first.py`)

```
function GREEDY(problem, h):
    frontier ← min-heap [(h(start, goal), counter, start)]
    in_frontier ← {start};  explored ← ∅;  parents ← {start: None}
    while frontier not empty:
        (_, _, node) ← heappop(frontier);  in_frontier.discard(node)
        if is_goal(node): return reconstruct_path(parents, node)
        explored.add(node);  expanded += 1
        for (child, _) in successors(node):
            if child ∈ explored or child ∈ in_frontier: continue
            parents[child] ← node
            heappush(frontier, (h(child, goal), counter, child));  in_frontier.add(child)
    return failure
```

* Evaluation function `f(n) = h(n)`. Ties are broken by insertion order (FIFO counter).
* **Complete**: yes on a finite grid. As a graph search, it never re-adds explored or frontier nodes.
* **Optimal**: no. The worst measured cost ratio was 2.907 (EARTHQUAKE benchmark).
* **Time / space**: O(b^m) in general (m = maximum depth); on the grid O(V log V), each cell being pushed at most once.

## 4. A* Search (`backend/app/search/astar.py`)

```
function A*(problem, h):
    frontier ← min-heap [(h0, h0, counter, start)]          # (f, h, tie counter, node)
    g ← {start: 0};  parents ← {start: None};  closed ← ∅
    while frontier not empty:
        (_, _, _, node) ← heappop(frontier)
        if node ∈ closed: continue                            # stale entry (lazy deletion)
        if is_goal(node): return reconstruct_path(parents, node), cost = g[node]
        closed.add(node);  expanded += 1
        for (child, c) in successors(node):
            if child ∈ closed: continue
            t ← g[node] + c
            if t < g.get(child, ∞):
                g[child] ← t;  parents[child] ← node
                heappush(frontier, (t + h(child), h(child), counter, child))
    return failure
```

* **Tie-breaking.** Entries with equal `f` are ordered by smaller `h`, which equals larger `g`, and then by insertion order. Preferring deeper nodes on the same `f`-contour drives the search towards the goal. This keeps the explored set small on open grids with many equal-cost paths.
* **Lazy deletion.** Instead of a decrease-key operation, a better entry is pushed again and stale entries are skipped once the node is closed. Each node can be pushed at most once per incoming edge, so at most 4 times.
* **Complete**: yes (finite graph, step costs >= 1 > 0).
* **Optimal**: yes, when `h` is consistent (Section 6), because the first time a node is popped its `g` is optimal. Closing it without re-opening is therefore safe.
* **Time / space**: O(b^d) worst case in general, exponential in the heuristic error; on the grid O(E log E) = O(V log V) time and O(V) space.
* With `h = zero`, A* is uniform-cost search (Dijkstra). `algorithm_lab.compare()` and `benchmark()` use it to certify the optimum.

## 5. Properties comparison

| Property | BFS | Greedy Best-First | A* (Manhattan) |
|---|---|---|---|
| Frontier order | FIFO (depth) | `h(n)` | `g(n) + h(n)`, ties: smaller `h` |
| Goal test | On generation | On expansion | On expansion |
| Complete | Yes | Yes (finite graph search) | Yes |
| Optimal | Fewest steps only | No | Yes (admissible + consistent `h`) |
| Time (general) | O(b^d) | O(b^m) | O(b^d), depends on heuristic accuracy |
| Space (general) | O(b^d) | O(b^m) | O(b^d) |
| Time on R x C grid | O(V) | O(V log V) | O(V log V) |
| Measured avg nodes, EARTHQUAKE (100 queries) | 124.5 | 28.9 | 36.4 |
| Measured optimal rate, EARTHQUAKE / URBAN_FIRE | 0.95 / 0.54 | 0.74 / 0.55 | 1.00 / 1.00 |

---

## 6. Heuristics (`backend/app/search/heuristics.py`)

```
manhattan(a, b) = MIN_STEP_COST * (|a.row - b.row| + |a.col - b.col|)          MIN_STEP_COST = 1.0
euclidean(a, b) = MIN_STEP_COST * sqrt((a.row - b.row)^2 + (a.col - b.col)^2)
zero(a, b)      = 0
```

**Theorem 1 (admissibility).** For every cell `n`, `manhattan(n, goal) <= h*(n)`, where `h*` is the cost of the cheapest path to the goal.

*Proof.* A 4-connected move changes exactly one coordinate by exactly 1, so it changes `|Δrow| + |Δcol|` by at most 1. Any path from `n` to the goal therefore has at least `k = |Δrow| + |Δcol|` moves. Every move enters a passable cell, and its cost `terrain_cost + 6.0 * danger` is at least `MIN_STEP_COST = 1`, since every passable terrain costs at least 1.0 and danger >= 0. Hence `h*(n) >= k * 1 = manhattan(n, goal)`. ∎

**Theorem 2 (consistency).** For every edge `n -> n'` with cost `c(n, n')`: `h(n) <= c(n, n') + h(n')`.

*Proof.* `n` and `n'` differ by one unit in one coordinate, so `|h(n) - h(n')| <= 1` (it is exactly 1). And `c(n, n') >= 1`. Then `h(n) <= h(n') + 1 <= h(n') + c(n, n')`. ∎

**Corollary.** A* with a closed set and Manhattan (or Euclidean, since `euclidean <= manhattan`) returns optimal paths. `tests/test_search.py::test_manhattan_is_admissible_and_consistent` checks both inequalities on random maps. `test_astar_is_optimal_and_dominates_uniform_cost_on_random_maps` checks that A* equals UCS in cost and never expands more nodes.

**Informedness.** The heuristic ignores the danger term. Danger makes true costs larger without changing `h`, so the gap `h* - h` grows and A* expands more nodes. On the same 100 URBAN_FIRE queries, A* expands 35.8 nodes with danger-aware costs against 21.2 with terrain costs only.

---

## 7. Online search

### 7.1 Plan validation (`backend/app/search/online.py`)

```
function first_blocked_index(path, grid, profile):
    for i = 1 .. len(path)-1:
        if not profile.passable(grid.type_at(path[i])): return i
    return None

function path_cost_on(grid, path, profile):        # None if any cell is impassable
    return Σ profile.step_cost(grid, p) for p in path[1:]
```

The agent calls both on its belief map for every open movement task. See Section 13.

### 7.2 Repeated A* with the free-space assumption (`repeated_astar`)

```
function REPEATED-A*(truth, start, goal, profile, r, max_steps = 2000):
    belief ← grid with every cell ROAD                    # free-space assumption
    SENSE(start)                                          # reveal Manhattan ball of radius r
    pos ← start;  plan ← A*(belief, pos, goal)
    if plan = failure: return failure
    while pos ≠ goal and |trajectory| ≤ max_steps:
        next ← plan[1]
        if truth[next] impassable:                         # only with r = 0: learn by bumping
            belief[next] ← truth[next]
            plan ← A*(belief, pos, goal); replans += 1;  if failure: break
            continue
        pos ← next;  cost += step_cost(truth, next);  plan ← plan[1:]
        surprises ← SENSE(pos)
        if surprises ≠ ∅ and pos ≠ goal and first_blocked_index(plan, belief) ≠ None:
            plan ← A*(belief, pos, goal); replans += 1;  if failure: break
    return trajectory, cost, replans, nodes_expanded (summed over all A* calls)
```

* A replan is triggered only when the remaining plan is contradicted, that is, when it crosses a cell discovered to be impassable. Cost surprises alone do not trigger one.
* **Complete** in a finite, static world. Unknown cells are believed passable, so the believed map is never more restrictive than the truth: if a true path exists, A* on the belief finds one. Every replan follows at least one newly revealed cell, so there are at most V replans. A step cap of `max_steps` also applies.
* **Not optimal.** The executed path is optimal only with respect to what was known at each step. Measured on EARTHQUAKE (23, 3) -> (17, 20): cost 44.2 at radius 1 and 35.0 at radius 2, against 33.0 for offline A*.

### 7.3 LRTA* (`lrta_star`; Korf 1990, AIMA Fig. 4.24)

```
function LRTA*(truth, start, goal, profile, r, max_steps = 3000):
    belief ← all-ROAD grid;  H ← {} (default H(s) = manhattan(s, goal))
    pos ← start;  SENSE(pos)
    while pos ≠ goal and |trajectory| ≤ max_steps:
        options ← [(c(pos, s') + H(s'), s', c) for passable neighbours s' on belief]
        expanded += 1
        if options = ∅: break                              # dead end
        (best_f, best_next, _) ← min(options)              # ties: lexicographic on the cell
        if best_f ≠ H(pos): heuristic_updates += 1
        H[pos] ← best_f                                     # learning step
        if truth[best_next] impassable:                     # only with r = 0
            belief[best_next] ← truth[best_next]; continue
        pos ← best_next;  cost += step_cost(truth, pos);  SENSE(pos)
```

* One-step look-ahead, O(1) work per move. `H` converges towards the true cost-to-go along visited states.
* **Complete** in finite, safely explorable state spaces, which a grid with reversible moves is. The step cap is 3000.
* **Not optimal** on a single trial. Measured: 45 steps, cost 46.2, 11 heuristic updates at radius 1.

### 7.4 How the live agent searches online

The agent's belief map is the situation-report map. Every hidden hazard is believed to be `ROAD`, which is the free-space assumption for unreported damage. Each cycle it senses a diamond of radius `SENSOR_RADIUS = 2` around every available unit. It validates every open movement task with `first_blocked_index` and `path_cost_on`, and re-searches from the unit's current cell when a task is invalid. This is repeated A* with the agent's selected algorithm (`BFS`, `GREEDY` or `ASTAR`), applied to a multi-unit plan. Within a simulation tick, a unit whose route has just been repaired spends that tick on the `REPLAN` action and moves again on the next tick.

---

## 8. CSP framework (`backend/app/csp/`)

A `CSP` has `variables`, `domains` and `constraints`. Constraints come in three kinds:

* `UnaryConstraint(var, predicate)`
* `BinaryConstraint(x, y, predicate)`
* `CapacityConstraint(scope, capacity, usage)`: an n-ary global constraint `Σ usage(v, value(v)) <= capacity` over the assigned variables of the scope

Every constraint can test a partial assignment (`is_consistent`) and prune a neighbour's domain (`prune`).

`BacktrackingSolver.solve()` runs node consistency, then AC-3 if `use_ac3`, then backtracking. It records domain sizes after each stage and every removal (stage `NODE`, `AC3` or `FC`).

### 8.1 Node consistency

```
function ENFORCE-NODE-CONSISTENCY():
    for each unary constraint c on X:
        remove from D(X) every value v with not c.predicate(v)        # recorded as NODE
        if D(X) = ∅: return failure("domain of X emptied by node consistency (c)")
```

Cost: O(n·d) predicate calls. In the allocation CSP some predicates (reachability) call the search algorithm, and those calls are memoised by the `RouteOracle`.

### 8.2 AC-3 with REVISE

```
function AC-3():
    queue ← [(X, c), (Y, c) for every binary constraint c over (X, Y)]
    while queue not empty:
        (Xi, c) ← queue.popleft();  Xj ← c.other(Xi)
        if REVISE(Xi, Xj, c):
            if D(Xi) = ∅: return failure("AC-3 emptied the domain of Xi")
            for each binary constraint c2 ≠ c on Xi:
                queue.append((c2.other(Xi), c2))          # re-check the neighbours of Xi
    return success

function REVISE(Xi, Xj, c):
    revised ← false
    for x in D(Xi):
        if no y ∈ D(Xj) with c.satisfied_by(Xi, x, y):
            remove x from D(Xi)                           # recorded as AC3
            revised ← true
    return revised
```

* Complexity O(e·d³): each arc is re-queued at most d times, and each REVISE costs O(d²).
* AC-3 only removes values that cannot appear in any solution, so it never loses solutions. If it empties a domain, the CSP is unsatisfiable without any search (`test_ac3_detects_inconsistency_without_search`).
* **Behaviour in the allocation CSP.** `DEFER` satisfies every `resource-conflict` constraint. A value of `Xi` therefore always has support while `DEFER ∈ D(Xj)`. AC-3 can only prune when `Xj` is a critical-coverage variable whose `DEFER` (and `EXTRACT_ONLY`) values were removed. At EARTHQUAKE tick 47, right after A2 was pre-empted, critical V10 had the single option `A2 -> H2`. AC-3 removed the A2 options of V06 and V05 (4 values). Over the five scenario runs AC-3 removed 5 values in total.

### 8.3 Backtracking search

```
function BACKTRACK(assignment, score):
    if stopped: return false
    nodes += 1
    if nodes > node_limit: truncated ← true; stopped ← true; return false
    if |assignment| = n:
        solutions_found += 1
        if no utility: best ← assignment; return true                 # satisfaction
        if score > best_score: best ← copy(assignment); best_score ← score
        return false                                                   # optimisation continues
    if utility and best exists:                                        # branch-and-bound
        if score + BOUND(assignment, D, unassigned) ≤ best_score + 1e-9:
            bound_prunings += 1; return false
    var ← SELECT-VARIABLE(assignment)
    for value in ORDER-VALUES(var, assignment):
        assignment[var] ← value
        if every non-unary constraint of var is consistent with assignment:
            removals ← []
            if FORWARD-CHECK(var, value, assignment, removals):
                if BACKTRACK(assignment, score + utility(var, value)): return true
            restore every (v, x) in removals
        delete assignment[var]
        if stopped: return false
    backtracks += 1
    return false
```

**Variable ordering** (`_select_variable`):

```
argmin over unassigned v of ( |D(v)|,                                  # MRV
                              -#{unassigned neighbours of v},          # degree heuristic
                              position of v in the priority order )    # stable tie-break
```

In the allocation CSP every pair of variables shares a `resource-conflict` constraint, so all degrees are equal. MRV ties therefore fall back to victim priority.

**Value ordering** (`_order_values`):

* With a utility (all agent CSPs), values are tried in descending `utility(var, value)`. Good incumbents are found early, which makes branch-and-bound effective.
* Without one (pure satisfaction, used in the tests), the least-constraining value comes first: it minimises the number of values it would prune from unassigned neighbours.

**Termination and result.** The search space is finite and explored depth-first, so the solver terminates. `CSPSolution.optimal` is `True` only if the search finished within `node_limit`. The agent uses `CSP_NODE_LIMIT = 5000`. The largest solve measured in the five scenario runs used 90 nodes (URBAN_FIRE tick 1), and none was truncated.

### 8.4 Forward checking generalised to n-ary capacity constraints

```
function FORWARD-CHECK(var, value, assignment, removals):
    for each non-unary constraint c on var with c.relevant(var, value):
        for each unassigned other ∈ scope(c), other ≠ var:
            for bad in c.prune(other, D(other), assignment):
                remove bad from D(other); removals.append((other, bad))       # recorded as FC
            if D(other) = ∅: return false                                    # wipe-out
    return true
```

Each constraint type prunes in its own way:

| Constraint | `relevant(var, value)` | `prune(other, D, assignment)` |
|---|---|---|
| `BinaryConstraint` | always | `{y ∈ D : not predicate(value(var), y)}` (only if the partner is assigned) |
| `CapacityConstraint` | `usage(var, value) > 0` | `remaining ← capacity - Σ_{assigned v} usage(v, value(v))`; prune `{y ∈ D : usage(other, y) > remaining}` |
| generic `Constraint` | always | values `y` for which `is_consistent(assignment ∪ {other: y})` is false |

*Soundness for capacity constraints.* Usage is non-negative, so the used amount can only grow as the assignment is extended. A value whose usage exceeds the remaining capacity can never be part of a consistent extension. Pruning it loses no solution, and an empty domain proves that the current branch has none.

### 8.5 Branch-and-bound bounds

The solver maximises `Σ utility(v, value(v))`. A bound must be **optimistic**: it must never be less than the best utility still obtainable from the unassigned variables. Otherwise an optimal branch could be pruned.

**Default bound** (when no problem-specific bound is given; used by the destination CSP and the generic tests):

```
BOUND = Σ_{v unassigned} max_{x ∈ D(v)} utility(v, x)           # -∞ if some D(v) is empty
```

It is admissible because each variable takes exactly one value from its current domain, and the pruned values are inconsistent. `test_branch_and_bound_matches_brute_force_optimum` checks the optimum against brute force on 25 random instances.

**Capacity-aware bound** for the resource-allocation CSP (`bound` inside `build_allocation_problem`):

```
seats_left ← Σ_{ambulance k} max(0, capacity[k] - used[k])     # free seats still unused
teams_left ← Σ_{team k}      max(0, 1 - used[k])                # free teams still unused
for each unassigned v:
    a_v ← max utility over remaining non-DEFER options WITH an ambulance      (DIRECT, EXTRACT_AND_TRANSPORT)
    t_v ← max utility over remaining non-DEFER options WITHOUT an ambulance   (TEAM_EVACUATE, EXTRACT_ONLY)
pooled ← (sum of the seats_left largest positive a_v) + (sum of the teams_left largest positive t_v)
plain  ← Σ_{v unassigned} max_{x ∈ D(v)} utility(v, x)          # the default bound
BOUND  ← min(pooled, plain)
```

*Theorem 3 (admissibility).* For every consistent completion `x` of the current partial assignment, `Σ_{v unassigned} utility(v, x_v) <= BOUND`.

*Proof.* We show that `pooled` and `plain` are both upper bounds. The minimum of two upper bounds is then also an upper bound.

`plain` is the default bound, which is admissible as shown above.

For `pooled`, split the unassigned variables of the completion into three groups:

* `A`: assigned an option with an ambulance.
* `T`: assigned a team-only option, `TEAM_EVACUATE` or `EXTRACT_ONLY`.
* `D`: assigned `DEFER`, with utility 0.

Every option in `A` uses at least one seat of some ambulance: usage is 1, or `capacity` for a critical patient. The `ambulance-capacity[*]` constraints therefore give `|A| <= seats_left`. Every option in `T` uses one team, and the `team-exclusive[*]` constraints give `|T| <= teams_left`.

For `v ∈ A`, `utility(v, x_v) <= a_v`, so `Σ_{A} utility <=` the sum of the `|A|` largest `a_v`. This is at most the sum of the `seats_left` largest *positive* `a_v`: dropping negative terms and adding non-negative ones can only increase the sum. The same argument applies to `T`, and `D` contributes 0. ∎

`pooled` is a relaxation: it ignores the team that an `EXTRACT_AND_TRANSPORT` option also uses, the hospital bed limits and the same-hospital rule. A victim can also contribute to both pools. That is why it is capped by `plain`.

When victims outnumber free seats and teams, `pooled` is much tighter. With 6 victims and 2 free seats, `plain` counts up to 6 gains of about 1000 + 20·priority, while `pooled` counts at most 2 ambulance gains plus the free teams.

Measured on the first allocation round, for the same problem and the same optimum:

| Problem | Complete assignments | Default bound only | `min(pooled, plain)` |
|---|---|---|---|
| EARTHQUAKE/DEMO tick 1: 6 variables x 37 values | 37^6 ≈ 2.6 x 10^9 | 240 nodes | 42 nodes, 13 backtracks, 295 forward-checking prunings, 24 bound prunings |
| URBAN_FIRE tick 1: 6 variables x 67 values | 67^6 ≈ 9.0 x 10^10 | 5,326 nodes | 90 nodes, 16 backtracks, 1,283 forward-checking prunings, 73 bound prunings |

`tests/test_csp.py::test_capacity_aware_bound_is_admissible` checks that the bounded solver reaches the same optimum as the unbounded one, with no more nodes.

---

## 9. Resource-allocation CSP (`build_allocation_problem`)

**Variables.** The waiting victims of one attention window (`ATTENTION_WINDOW = 6`), in priority order.

**Domains.** The full Cartesian product of methods and resources, plus `DEFER`:

```
{AMBULANCE_DIRECT(a, h)          : a ∈ ambulances, h ∈ hospitals}
∪ {EXTRACT_AND_TRANSPORT(t, a, h): t ∈ teams, a ∈ ambulances, h ∈ hospitals}
∪ {TEAM_EVACUATE(t, d)           : t ∈ teams, d ∈ hospitals ∪ safe zones}
∪ {EXTRACT_ONLY(t)               : t ∈ teams}                 # partial plan, no destination
∪ {DEFER}
|D| = |A||H| + |A||T||H| + |T|(|H|+|S|) + |T| + 1        (EARTHQUAKE: 37, URBAN_FIRE: 67)
```

**Victim needs** (`assess_needs`, computed on the belief map):

* `hazard`: the victim stands on fire, or its danger is at least `HAZARD_DANGER_THRESHOLD = 0.6`.
* `needs_extraction`: the victim is not yet extracted, and is trapped or in a hazard.
* `needs_hospital`: the severity is not LOW.
* `needs_als`: the victim is CRITICAL.
* `needs_icu`: copied from the victim.
* `ground_accessible`: a ground vehicle has a route to the victim from some hospital or rescue base.

**Unary constraints** (enforced by node consistency):

| Name | Predicate on option `o` for victim `v` (`DEFER` always passes) |
|---|---|
| `method-applicability` | DIRECT: needs hospital, no extraction, ground accessible. EXTRACT_AND_TRANSPORT and EXTRACT_ONLY: needs hospital, needs extraction, ground accessible. EVACUATE: if the victim needs a hospital, only to a hospital and only when there is no road access; otherwise only to a safe zone. |
| `resource-availability` | Every unit of `o` is available and idle |
| `medical-capability` | If `v` is critical and `o` uses an ambulance, it must be ALS |
| `icu-capacity` | ICU patient -> destination hospital has `icu_free >= 1` |
| `hospital-capacity` | Non-ICU patient -> destination hospital has `er_free >= 1` |
| `hazard-capability` | Hazard victim -> the team of `o` must be FIREFIGHTING |
| `reachability` | Every unit has a route to `v`, and the carrier has a route from `v` to the destination (search on the belief map with each unit's profile). EXTRACT_ONLY has no destination leg. |
| `partial-plan-fallback` | `o` is `EXTRACT_ONLY` only if `not complete_possible[v]`. Here `complete_possible[v]` holds when some option other than DEFER and EXTRACT_ONLY passes all seven predicates above, including `resource-availability`, so it reflects the currently idle units. |
| `critical-coverage` | `o ∉ {DEFER, EXTRACT_ONLY}`: a complete rescue plan. It is added only for critical victims with `complete_possible[v]`, and only for those in the `coverage` list when one is given. |

Free beds are computed after subtracting the beds already reserved by in-progress missions (`_free_beds`).

**Resource usage model:**

| Resource | Usage by an option |
|---|---|
| `amb:A` | `A.capacity` if the victim is CRITICAL (rides alone), else 1 |
| `team:T` | 1 |
| `icu:H` / `er:H` | 1, for the bed type the victim needs |

**Global constraints:** `ambulance-capacity[A]` (capacity = `A.free_seats`), `team-exclusive[T]` (capacity 1), `er-beds[H]` and `icu-beds[H]` (free beds). All are `CapacityConstraint`s over all variables.

**Binary constraints:** for every pair `(Vi, Vj)`, `resource-conflict`. For each resource they share, the two usages must not exceed its capacity, and if both use the same ambulance they must go to the same destination.

Constraint count for a window of n victims:

```
7n unary + (#coverage) + n(n-1)/2 binary + (|A| + |T| + 2|H|) global
```

For the first EARTHQUAKE round this is 48 + 2 + 15 + 10 = 75 constraints. Node consistency then removes 166 of the 6 x 37 = 222 values: 150 by `method-applicability`, 8 by `medical-capability`, 6 by `partial-plan-fallback` and 2 by `critical-coverage`.

**Utility (objective).** `DEFER` scores 0. Any other option scores:

```
utility(v, o) = base(o) + PRIORITY_WEIGHT * priority(v) - ETA(v, o)              (PRIORITY_WEIGHT = 20)
base(o)       = PARTIAL_BASE_UTILITY = 600   if o is EXTRACT_ONLY
              = SERVE_BASE_UTILITY  = 1000   otherwise

ETA(AMBULANCE_DIRECT)      = c(A -> v) + rescue_time + c(v -> H)
ETA(EXTRACT_AND_TRANSPORT) = max(c(T -> v) + rescue_time, c(A -> v)) + 1 + c(v -> H)
ETA(TEAM_EVACUATE)         = c(T -> v) + rescue_time + c(v -> D)
ETA(EXTRACT_ONLY)          = c(T -> v) + rescue_time
```

`c` is the search cost on the belief map with the unit's mobility profile; the transport leg uses the carrier's profile.

* The base of 1000 means serving any reachable victim beats deferring it.
* The reduced base of 600 means a complete plan beats a partial one for the *same* victim.
* The `20 * priority` term makes higher-priority victims win contested resources.
* Subtracting the ETA prefers fast assignments.

The objective is a sum. Without the `partial-plan-fallback` constraint, the solver could trade one complete plan for a partial plan plus another complete plan whenever that sum is higher. With it, a partial plan is only ever offered to a victim that no idle combination of units can serve completely. Example: DEMO tick 34, where V10 gets `T1 extract only` because both ALS ambulances are busy.

**Minimal relaxation of critical-coverage**, in `DisasterResponseAgent._allocate_window`:

```
problem  ← build_allocation_problem(window, ..., require_critical = True)   # coverage for all eligible critical victims
solution ← SOLVE(problem)
covered  ← problem.coverage_vars                                            # highest priority first
if not solution.satisfiable and covered ≠ ∅:
    log "Phase 1 (hard 'critical-coverage') has no solution: <reason>"
while not solution.satisfiable and covered ≠ ∅:
    dropped ← covered.pop()                                                 # lowest-priority critical victim
    log "Relaxing 'critical-coverage' for <dropped>; still required for <covered>"
    problem  ← build_allocation_problem(window, ..., require_critical = True, coverage = covered)
    solution ← SOLVE(problem)
```

Phase 1 asks every critical victim that could be served completely on its own to get a complete plan this round. If the critical victims together over-subscribe the resources, coverage is given up one victim at a time, lowest priority first, so the highest-priority critical victims stay covered. The utility function still favours the dropped victims. A dropped victim may be deferred, or may receive a partial plan only if `partial-plan-fallback` allows it. The CSP report shows the first failure (`relaxed`, `phase1`). A step also counts as failed when it found no solution only because the node budget ran out.

Three tests cover this:

* `test_critical_coverage_is_relaxed_when_unsatisfiable`
* `test_minimal_relaxation_keeps_coverage_for_the_highest_priority_critical_victim`
* `test_extract_only_is_a_fallback_never_a_substitute_for_full_service`: a critical victim with an available ALS ambulance gets a complete plan, while one without gets EXTRACT_ONLY.

Examples in EARTHQUAKE at tick 0, before any step:

* After **Remove ambulance**, only one ALS ambulance remains for critical V01 and V02. Phase 1 already fails in AC-3 ("AC-3 emptied the domain of V01 (resource-conflict with V02)"). The agent logs "Relaxing 'critical-coverage' for V02; still required for V01". V01 then gets `T3 extract + A2 -> H1`, and V02 is deferred.
* After **New emergency**, there are three critical victims (V10, V01, V02) for two ALS ambulances. Phase 1 fails in backtracking. Dropping V02 is enough: V10 gets `T1 extract + A1 -> H1` and V01 gets `T3 extract + A2 -> H1`.

**Attention windows** (`_allocate`). Waiting victims are sliced into windows of 6, highest priority first. Each window is solved in turn while idle units remain, and units used by one window are removed before the next. The whole allocation is skipped if the allocation signature has not changed since the last solve.

---

## 10. Destination re-allocation CSP (`build_destination_problem`)

It is used when a hospital is overbooked, when the agent tries to abort a mission whose patient is already on board, or when a transport leg has no route.

| Element | Definition |
|---|---|
| Variables | The affected victims that need a hospital and have an available carrier. Missions without a destination, such as `EXTRACT_ONLY`, are skipped. |
| Domain | All hospital ids + `HOLD` |
| Unary | `bed-availability` (ICU bed if `needs_icu`, else ER bed); `reachability` (route from the carrier's position if loaded, else from the victim); `deliver-loaded-patient` (loaded patient -> not `HOLD`; phase 1 only) |
| Global | `er-beds[H]`, `icu-beds[H]` (free beds excluding the variables' own reservations) |
| Binary | `same-carrier-same-hospital` (`a == b`) for patients in the same vehicle |
| Utility | `1000 - route cost` (500 if unreachable); `HOLD` = 0 |

If phase 1 is unsatisfiable, `deliver-loaded-patient` is relaxed. The outcome is applied as follows:

* A different hospital triggers `_retarget`: the transport leg is re-routed, the deliver and select tasks are relabelled, and `destination_changes` is incremented.
* `HOLD` with the patient on board sets `needs_route`, so the carrier holds position and retries.
* `HOLD` before loading aborts the mission and re-queues the victim.

---

## 11. Hierarchical (HTN) planning (`backend/app/planning/planner.py`)

```
function PLAN-ROUND(assignments):                       # (victim, AllocationOption) from the CSP
    trips   ← group by ambulance the pairs with opt.ambulance ≠ None and victim not CRITICAL
    singles ← all other pairs + every trip group of size 1
    for (v, opt) in singles: plans += SAFE(SINGLE(v, opt))
    for group in trips:      plans += SHARED-TRIP(group)   # one or more plans; errors -> failed plan
    return plans             # SAFE turns PlanningError into MissionPlan(failed = reason)

function SINGLE(v, opt):
    root ← RESCUE_VICTIM "Rescue Victim v [SEV]"
    if opt.method = EXTRACT_ONLY:                                       # partial plan
        root += ASSIGN "Assign Team T (CAP) - extraction only", NAVIGATE(T, T.pos -> v),
                EXTRACT(T, v, duration = rescue_time), UPDATE "Release T · v awaits an ambulance"
        agenda[T] ← [navigate, extract, release]
        return
    if opt.method ∈ {AMBULANCE_DIRECT, EXTRACT_AND_TRANSPORT}:
        root += ASSIGN "Assign Ambulance A (ALS|BLS) [+ Team T (CAP)]"   (DONE, chosen by CSP)
        if team T:
            navT ← NAVIGATE(T, T.pos -> v)       # path from the search algorithm
            ext  ← EXTRACT(T, v, duration = rescue_time)
            root += navT, ext, UPDATE "Release T"
            agenda[T] ← [navT, ext, UPDATE "Release T"]
        navA ← NAVIGATE(A, A.pos -> v)
        load ← RESCUE(A, v, duration = 1 if team else rescue_time, depends_on = [ext] if team)
        sel  ← SELECT_DESTINATION "Select hospital H (name)"            (DONE, bed reserved)
        tr   ← TRANSPORT(A, v -> H);  del ← DELIVER(A, v, H);  upd ← UPDATE "Release A · update H beds"
        agenda[A] ← [navA, load, tr, del, upd]
    else (TEAM_EVACUATE):
        nav ← NAVIGATE(T, T.pos -> v); res ← RESCUE "Rescue v (extract & carry)"
        sel ← SELECT_DESTINATION; tr ← TRANSPORT "Escort v -> D"; del ← DELIVER; upd ← "Release T"
        agenda[T] ← [nav, res, tr, del, upd]
    any movement leg without a route raises PlanningError("no route for ...")

function SHARED-TRIP(group on ambulance A, destination H):
    order ← argmin over permutations π of group of
            cost(A.pos -> v_π1) + Σ cost(v_πi -> v_πi+1) + cost(v_πk -> H)
    first   ← order[1]
    onboard ← cost of the legs after picking up first     # remaining pick-ups + transport to H
    if onboard > TRIP_DETOUR_RATIO * cost(first -> H) + TRIP_DETOUR_MARGIN:          # 2.0, 12.0
        keep ← the patient of the group with the highest priority
        return [SINGLE(keep, opt_keep)] +
               [failed plan "shared trip rejected: ... A takes keep (highest priority) alone ..." for the others]
    for v in order: root_v gets ASSIGN "(shared trip)", optional team NAVIGATE/EXTRACT/Release,
                    NAVIGATE(A, prev -> v), LOAD/STABILISE, SELECT_DESTINATION
                    agenda[A] += [navigate, load]
    tr ← TRANSPORT "Transport v1+...+vk -> H"; del ← DELIVER; upd ← UPDATE
    agenda[A] += [tr, del, upd]
    each root_v gets MIRRORS of tr, del, upd                      # shared tasks in every sub-tree
```

* **Methods.** There are three complete methods and one partial method (`EXTRACT_ONLY`). The CSP selects the method and binds its parameters. This is an HTN in which method choice is delegated to constraint optimisation instead of being searched by the planner. An EXTRACT_ONLY mission achieves a sub-goal: when the extraction completes, `_complete_extraction` closes the mission, and the victim, now extracted, goes back to the goal queue for a transport plan.
* **Detour rule.** When a shared trip is rejected, the highest-priority patient of the group keeps the ambulance and is planned alone; the others return to the goal queue. No merge is rejected in the five default runs; `test_shared_trip_is_rejected_when_the_first_patient_would_ride_a_long_detour` exercises the rule. The same threshold is re-checked during execution (`TRIP_DETOUR`, Section 14).
* **Ordering.** Ordering is total within a unit's agenda. The only constraint across units is `depends_on`: a load waits for its extraction.
* **Complexity.** `SINGLE` performs at most 3 route searches (team leg, ambulance leg, transport leg). `SHARED-TRIP` with `k` passengers evaluates `k!` orders with `k + 1` legs each. Routes are memoised, and `k` is bounded by the free seats (2 in the built-in scenarios).
* **Failure.** A `PlanningError` is caught and logged as `HTN decomposition for Vxx: <reason>`: at ALERT level, or INFO for a rejected shared trip. The victim stays in the goal queue.

---

## 12. Victim priority function (`backend/app/agents/priority.py`)

```
priority = Severity + Health deficit + Survival window + Hazard exposure + Waiting time + Entrapment
```

| Factor | Formula | Constants |
|---|---|---|
| Severity | `SEVERITY_POINTS[severity]` | CRITICAL 45.0, HIGH 32.0, MEDIUM 20.0, LOW 8.0 |
| Health deficit | `(100 - health) * HEALTH_WEIGHT` | `HEALTH_WEIGHT = 0.2` (up to 20 points) |
| Survival window | `clamp(URGENCY_MAX * (1 - window / URGENCY_HORIZON), 0, URGENCY_MAX)` with `window = health / (SEVERITY_DECAY[sev] * (1 + DANGER_DECAY_FACTOR * danger))` | `URGENCY_MAX = 15.0`, `URGENCY_HORIZON = 200.0`, `DANGER_DECAY_FACTOR = 1.5` |
| Hazard exposure | `HAZARD_MAX * danger(victim cell)` | `HAZARD_MAX = 12.0` |
| Waiting time | `min(WAIT_MAX, (tick - reported_tick) * WAIT_RATE)` | `WAIT_RATE = 0.1`, `WAIT_MAX = 8.0` |
| Entrapment | `TRAPPED_POINTS` if trapped and not extracted | `TRAPPED_POINTS = 4.0` |

`SEVERITY_DECAY` (health lost per tick while waiting, from `entities.py`) is CRITICAL 0.32, HIGH 0.18, MEDIUM 0.09 and LOW 0.03. The survival window uses the same formula as the simulator's deterioration model, so the estimate matches what actually happens to a waiting victim.

Each factor is returned separately (`priority_breakdown`) and shown in the UI and the decision log.

**Worked example: victim V01 in DEMO / EARTHQUAKE at tick 1.** V01 is CRITICAL, trapped, starts at health 44 and stands at (7, 15) with danger 0.0.

| Step | Computation | Points |
|---|---|---|
| Health after the tick-1 update | 44 - 0.32 x 1.0 x (1 + 1.5 x 0.0) = 43.68 | none |
| Severity | CRITICAL | 45.0 |
| Health deficit | (100 - 43.68) x 0.2 = 11.264 | 11.3 |
| Survival window | window = 43.68 / 0.32 = 136.5 ticks; 15 x (1 - 136.5 / 200) = 4.76 | 4.8 |
| Hazard exposure | 12 x 0.0 | 0.0 |
| Waiting time | min(8, 1 x 0.1) | 0.1 |
| Entrapment | trapped, not extracted | 4.0 |
| **Total** | 45 + 11.264 + 4.7625 + 0 + 0.1 + 4 = 65.13 | **65.1** |

This matches the decision log: `Most urgent unassigned goal: rescue V01 (priority 65.1)`, with `Survival window: +4.8 (~136 ticks before fatal without treatment)`.

The CSP utility for the option chosen for V01 (`T3 extract + A1 -> H1`) uses the A* route costs T3 -> V01 = 13.2 (firefighting profile), A1 -> V01 = 28.0 and V01 -> H1 = 8.0:

```
ETA     = max(13.2 + 4, 28.0) + 1 + 8.0 = 37.0
utility = 1000 + 20 x 65.1 - 37.0 = 2265.0         (logged: "utility 2265")
```

For comparison, consider a partial plan. At DEMO tick 34, V10 (CRITICAL, trapped, priority 64.6) has no feasible complete plan because no ALS ambulance is idle. It gets `T1 extract only`:

```
utility = 600 + 20 x 64.6 - ETA = 1874             (logged: "utility 1874"; ETA = c(T1 -> V10) + rescue_time = 18)
```

Before the first tick, `Simulation.reset()` calls `preview_priorities`, which scores the reported victims with the same function. For V01 at tick 0 (health 44, no wait) this gives 64.9.

---

## 13. Agent decision cycle (`DisasterResponseAgent.decide` / `observe`)

```
function DECIDE(world, reports, reactive = False):               # step: reactive=False; inject: True
    PERCEIVE:        changes ← {cells in reports or in a sensor diamond (radius 2) of an available
                                unit where truth ≠ belief};
                     discovered ← unreported victims within radius 2 of an available unit;
                     if changes or significant reports or discovered: log "ENVIRONMENT CHANGE DETECTED"
    UPDATE_STATE:    apply changes to belief, recompute danger, belief_version += 1, new RouteOracle;
                     add new / discovered victims to known_victims
    IDENTIFY_GOALS:  for each active known victim: priority ← compute_priority(v, belief, tick);
                                                   needs ← assess_needs(v, belief, oracle, anchors)
                     goals ← sort by (-priority, id); log most urgent unassigned goal (hysteresis 1.0)
    CHECK_CONSTRAINTS: issues ← validate missions, hospitals and (if map changed) all routes  (Section 14)
    PLAN:            repair issues (Section 14); then _allocate(): attention windows -> allocation CSP
                     -> HierarchicalPlanner.plan_round -> commit missions and agendas;
                     then _preempt_for_critical(); if it acted, _allocate() again
    SELECT_ACTION:   for each available unit: task ← _current_task()
                     if the unit's route was repaired this cycle and not reactive:
                         action ← REPLAN   ("Action selected: REPLAN - X adopts the new route; mission resumes next tick")
                     else: action ← _action_for(task)   ("Mission resumed: ..." on the first action after a repair)
    return actions

function OBSERVE(world, results):                                # EXECUTE + OBSERVE phases
    for each result: failed -> log + agenda dirty; MOVE/TRANSPORT -> advance path_index, finish on arrival;
                     RESCUE -> progress / DONE; an EXTRACT that completes an EXTRACT_ONLY mission
                     -> _complete_extraction (victim WAITING, extracted); DELIVER -> DONE, complete mission(s)
    complete instant tasks at the head of every agenda
    if no active known victim and no mission: "All known victims resolved - mission goal satisfied"
```

The agent is **rational** in the AIMA sense, given its percepts and knowledge. It ranks goals by a performance-oriented priority, chooses the allocation that maximises utility under hard constraints, and routes with minimum-cost search. It operates under **bounded rationality**: an attention window of 6, a CSP node budget of 5000, and repairs triggered by events instead of continuous re-optimisation.

---

## 14. Plan-repair strategy

`check_constraints` produces `Issue`s. `plan` repairs them in this order:

1. abort / re-queue issues
2. destination re-allocation for overbooked hospitals
3. route repairs
4. allocation of the remaining idle units

| Issue kind | Detection (CHECK_CONSTRAINTS) | Repair (PLAN) |
|---|---|---|
| `ROUTE_BLOCKED` | `first_blocked_index(remaining_path, belief, profile)` finds an impassable cell on an open movement task | `_repair_route`: log `Stopping current plan for X. Replanning...` (active leg) or `Upcoming leg '...' invalid. Replanning...`, then search again from the unit's position or the leg start. On success: new path, `route_replans` += 1, `Checking constraints for revised plan... satisfied`. The unit then gets the `REPLAN` action in a normal tick, followed by `Mission resumed` on the next tick; a reactive cycle logs `Mission resumed` immediately. On failure: `_escalate_route_failure`. |
| `ROUTE_DEGRADED` | Active leg: `path_cost_on(belief) > planned x DEGRADE_RATIO + DEGRADE_MARGIN` (1.35, 2.0) | Search again. Adopt the new route only if it is strictly cheaper; otherwise log `Current route of X is still the best option` and refresh the step costs. |
| `NEEDS_ROUTE` | A leg flagged `needs_route` after an earlier failure | Retry `_repair_route` (checked whenever the belief map changes or the agenda is dirty) |
| `TRIP_DETOUR` | `_check_trip_detours`: an ambulance carries patients and has pending pick-ups. The remaining pick-up legs plus transport cost, on the belief map, exceed `TRIP_DETOUR_RATIO x direct + TRIP_DETOUR_MARGIN` (2.0, 12.0). If any leg is blocked, the unit is skipped, because a blocked leg is a job for route repair. Logged as `Rationality check failed: ...`. | Abort every pending pick-up of that ambulance (`requeue=True`, reason "X delivers its patients first"), so the patients on board go straight to hospital |
| `UNIT_UNAVAILABLE` | A unit of a mission is out of service and still has open tasks for it | `_abort_mission(requeue=True)` for every mission using the unit. The victim returns to `WAITING`; `reassignments` += 1. The next allocation can keep the same team on an extraction through `EXTRACT_ONLY` (`test_ambulance_breakdown_keeps_the_team_on_a_trapped_critical_victim`). |
| `VICTIM_LOST` | Victim `DECEASED` | `_abort_mission(requeue=False)`: cancel tasks, free units |
| `CAPABILITY_VIOLATION` | A not-yet-extracted victim is now in a hazard without a FIREFIGHTING team, or now needs extraction under `AMBULANCE_DIRECT` | `_abort_mission(requeue=True)`, so the next allocation CSP picks a capable method or team |
| `HOSPITAL_OVERBOOKED` | Inbound ER or ICU patients > free beds of a hospital | `_reallocate_destinations` (destination CSP, Section 10) for the missions heading there |

Route issues are repaired only if they are still open. `_issue_resolved` skips a `ROUTE_BLOCKED` or `NEEDS_ROUTE` issue that an earlier repair in the same cycle has already fixed. An example is a transport leg that a destination change has just re-routed.

`_escalate_route_failure`:

* A `NAVIGATE` leg aborts its mission (re-queue).
* A `TRANSPORT` leg first runs the destination CSP for its patients. If still no route exists, the unit holds (`needs_route`) and retries when the map changes.

`_abort_mission` with `requeue=True` never abandons a patient who is already on board an available carrier; it re-routes the destination instead. Aborting a passenger of a shared trip removes it from the shared Transport and Deliver tasks and relabels them.

**Critical pre-emption** (`_preempt_for_critical`, run after allocation):

```
function PREEMPT-FOR-CRITICAL(world):
    W ← WAITING critical victims without a mission (in goal order)
    if W = ∅ or some ALS ambulance is available and idle: return false   # the CSP had an ALS to use
    for v in W:
        if not ground_accessible(v) or (needs_icu(v) and no hospital has a free ICU bed): continue
        if needs_extraction(v) and no idle team can extract v (FIREFIGHTING if v is in a hazard): continue
        C ← {(route cost A -> v, A, m) : mission m is not for a critical victim, its ambulance A is
              ALS, available and carries nobody}
        if C = ∅: continue
        (cost, A, m) ← min C
        log "Pre-emption: A diverted from m (SEV) to critical victim v (cost away)"
        abort every mission of A (requeue = True)
        return true                          # PLAN then calls _allocate again in the same cycle
    return false
```

The extractor check stops pre-emption from taking an ambulance that could not help yet. In DEMO, V10 is freed by its EXTRACT_ONLY mission at tick 47. At tick 48 the agent logs "Pre-emption: A1 diverted from V05 (MEDIUM) to critical victim V10 (12 away)", and the re-run allocation assigns `V10 -> A1 -> H2`. V10 reaches hospital at tick 95 with 34% health. `test_critical_victim_pre_empts_a_less_urgent_ambulance_mission` covers the mechanism.

---

## 15. Stall detection (`DisasterResponseAgent.is_stalled`, `Simulation._update_status`)

```
function IS-STALLED(world):
    if missions ≠ ∅:
        busy ← available units with an open non-instant task
        if busy = ∅ or some busy unit is not holding (its current task lacks a route): return false
        waiting ← waiting victims without a mission
        return waiting = ∅ or ALLOCATION-EXHAUSTED(world)       # everyone is stuck
    return ALLOCATION-EXHAUSTED(world)

function ALLOCATION-EXHAUSTED(world):
    waiting, idle ← _waiting_and_idle(world)
    if waiting = ∅: return false
    if idle = ∅: return true
    return allocation_signature(world, waiting, idle) = signature of the last allocation solve
```

The allocation signature is `(waiting victim ids, idle unit ids, belief_version, free beds per hospital, extracted waiting victims)`. If nothing the allocator depends on has changed since its last solve, which deferred everyone, solving again cannot help. The simulation declares `STALLED` only when there are active known victims, **no scheduled events remain** (a future event could change the situation) and `IS-STALLED` holds. A user event resets the status to `RUNNING`.

Example: a CUSTOM scenario with `teams = 0` stalls at tick 145 with 3 victims waiting. Two LOW victims cannot be escorted, and one trapped victim cannot be extracted without a team.

---

## 16. Simulation model (for reference)

* **Transition model** `Simulation.execute`. Moves are 1 cell per tick and must be adjacent and passable on the ground truth. `RESCUE/EXTRACT` increments `rescue_progress` until `duration`. `RESCUE/LOAD` fails for a trapped, unextracted victim if the unit is an ambulance, and fails when the carrier is full. Delivery updates hospital ER/ICU occupancy or safe-zone occupancy. `REPLAN` is a no-op: the unit holds position for the tick.
* **Deterioration.** Health loss per tick is `SEVERITY_DECAY[sev] * factor * (1 + 1.5 * danger)`:
  * `factor` = 0.15 in an ALS ambulance, 0.4 in a BLS ambulance, 0.5 carried by a team, `ON_SCENE_DECAY = 0.8` while being rescued, 1.0 waiting.
  * Danger is ignored while the victim is carried.
  * A `WAITING` victim escalates MEDIUM -> HIGH below 45 health and HIGH -> CRITICAL below 28.
* **Natural dynamics.**
  * Fire: every `fire_spread_interval` ticks, each building next to a fire ignites with probability `p`, and each road next to a fire with probability `0.4p`. At most 4 new cells are added per spread and the total never exceeds `max_fire_cells`.
  * Flood: every `flood_interval` ticks, `flood_cells_per_rise` random flood-prone cells next to water are submerged.
* **Termination.** `TIME_LIMIT = 600` ticks.
