"""Multi-objective Pareto-front optimisation over recipe composition.

Complements :mod:`.optimiser` (single-objective weighted-sum).  Instead
of collapsing multiple targets into one loss we run a small NSGA-II
loop and return the non-dominated set so the formulator can inspect
trade-offs directly (e.g. gloss ↑ vs VOC ↓).

Kept dependency-light: the algorithm uses only NumPy + our existing
candidate builder from ``optimiser.py``.  For serious industrial
workloads users can plug in ``pymoo`` — the API stays compatible
because :class:`ParetoPoint` is what the endpoint returns anyway.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...domain.entities.recipe import Recipe
    from .optimiser import ComponentBounds, PropertyTarget

logger = logging.getLogger(__name__)


PredictFn = Callable[["Recipe", str], float | None]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ParetoPoint:
    """One non-dominated candidate on the Pareto front."""

    mass_percent: dict[str, float]
    objectives: dict[str, float]  # property_code → objective value
    rank: int  # 0 for the front, >0 for further layers
    crowding_distance: float


@dataclass(frozen=True, slots=True)
class ParetoResult:
    base_recipe_id: str
    front: tuple[ParetoPoint, ...]  # rank 0 only
    all_points: tuple[ParetoPoint, ...] = field(default_factory=tuple)
    generations: int = 0


# ---------------------------------------------------------------------------
# Core NSGA-II primitives
# ---------------------------------------------------------------------------
def _dominates(obj_a: list[float], obj_b: list[float], directions: list[int]) -> bool:
    """Return True iff ``a`` weakly dominates ``b`` with strict inequality."""
    strictly_better = False
    for a, b, d in zip(obj_a, obj_b, directions, strict=True):
        # d = +1 → maximise, d = -1 → minimise, d = 0 → match (converted upstream).
        if d > 0:
            if a < b:
                return False
            if a > b:
                strictly_better = True
        else:  # minimise or match
            if a > b:
                return False
            if a < b:
                strictly_better = True
    return strictly_better


def _fast_nondominated_sort(
    objectives: list[list[float]], directions: list[int]
) -> list[list[int]]:
    """Deb's fast non-dominated sort — returns lists of indices per rank."""
    n = len(objectives)
    dominates_map: list[list[int]] = [[] for _ in range(n)]
    dominated_count = [0] * n
    fronts: list[list[int]] = [[]]

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if _dominates(objectives[i], objectives[j], directions):
                dominates_map[i].append(j)
            elif _dominates(objectives[j], objectives[i], directions):
                dominated_count[i] += 1
        if dominated_count[i] == 0:
            fronts[0].append(i)

    front_index = 0
    while fronts[front_index]:
        next_front: list[int] = []
        for i in fronts[front_index]:
            for j in dominates_map[i]:
                dominated_count[j] -= 1
                if dominated_count[j] == 0:
                    next_front.append(j)
        front_index += 1
        fronts.append(next_front)
    return [f for f in fronts if f]


def _crowding_distance(objectives: list[list[float]], front: Iterable[int]) -> dict[int, float]:
    """Compute crowding distance for the members of one front."""
    idxs = list(front)
    if not idxs:
        return {}
    dist = dict.fromkeys(idxs, 0.0)
    m = len(objectives[0])
    for obj_i in range(m):
        idxs.sort(key=lambda i: objectives[i][obj_i])
        dist[idxs[0]] = float("inf")
        dist[idxs[-1]] = float("inf")
        obj_min = objectives[idxs[0]][obj_i]
        obj_max = objectives[idxs[-1]][obj_i]
        span = obj_max - obj_min
        if span <= 0:
            continue
        for k in range(1, len(idxs) - 1):
            dist[idxs[k]] += (
                objectives[idxs[k + 1]][obj_i] - objectives[idxs[k - 1]][obj_i]
            ) / span
    return dist


# ---------------------------------------------------------------------------
# Optimiser
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ParetoRequest:
    targets: tuple[PropertyTarget, ...]
    bounds: tuple[ComponentBounds, ...] = field(default_factory=tuple)
    population_size: int = 24
    generations: int = 20
    mutation_std: float = 0.5  # in mass %
    seed: int | None = 42


class ParetoOptimiser:
    """NSGA-II style multi-objective search."""

    def __init__(self, predictor: PredictFn) -> None:
        self._predict = predictor

    def optimise(self, base_recipe: Recipe, request: ParetoRequest) -> ParetoResult:
        try:
            import numpy as np  # noqa: F401 — only ensures numeric availability
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("numpy is required for Pareto search") from exc

        from .optimiser import RecipeOptimiser

        rng = random.Random(request.seed)
        stub = RecipeOptimiser(predictor=self._predict)  # reuse candidate builder
        components = list(base_recipe.all_components)
        if not components:
            raise ValueError("Cannot optimise an empty recipe")

        # Prepare bounds (same rules as the single-objective optimiser).
        bounds_map = {b.component_name: b for b in request.bounds}
        search_bounds: list[tuple[float, float]] = []
        for comp in components:
            explicit = bounds_map.get(comp.name)
            if explicit is not None:
                low, high = explicit.min_percent, explicit.max_percent
            else:
                delta = comp.mass_percent * 0.2
                low = max(0.0, comp.mass_percent - delta)
                high = min(100.0, comp.mass_percent + delta)
            if high <= low:
                high = min(100.0, low + 0.5)
            search_bounds.append((low, high))

        # Direction vector for dominance:  +1 = maximise, -1 = minimise.
        directions: list[int] = []
        for t in request.targets:
            if t.direction == "maximise":
                directions.append(+1)
            elif t.direction == "minimise":
                directions.append(-1)
            else:
                # "match" collapses to minimise |predicted - target|.
                directions.append(-1)

        # Objective evaluation.
        def _objectives(vec: list[float]) -> tuple[list[float] | None, Recipe | None]:
            candidate = stub._build_candidate(base_recipe, components, vec)
            if candidate is None:
                return None, None
            out: list[float] = []
            for t in request.targets:
                predicted = self._predict(candidate, t.property_code)
                if predicted is None:
                    return None, None
                if t.direction == "match":
                    out.append(abs(predicted - t.target_value))
                else:
                    out.append(predicted)
            return out, candidate

        # Initial random population uniform in bounds.
        def _random_individual() -> list[float]:
            return [rng.uniform(lo, hi) for lo, hi in search_bounds]

        population: list[list[float]] = [
            _random_individual() for _ in range(request.population_size)
        ]

        def _clamp(vec: list[float]) -> list[float]:
            return [max(lo, min(hi, v)) for v, (lo, hi) in zip(vec, search_bounds, strict=True)]

        def _mutate(vec: list[float]) -> list[float]:
            return _clamp([v + rng.gauss(0.0, request.mutation_std) for v in vec])

        def _crossover(a: list[float], b: list[float]) -> list[float]:
            return _clamp([rng.choice((va, vb)) for va, vb in zip(a, b, strict=True)])

        for _ in range(request.generations):
            # Offspring generation.
            offspring: list[list[float]] = []
            while len(offspring) < len(population):
                a = rng.choice(population)
                b = rng.choice(population)
                child = _mutate(_crossover(a, b))
                offspring.append(child)
            combined = population + offspring
            # Evaluate.
            evaluated: list[tuple[list[float], list[float]]] = []
            for individual in combined:
                obj, _ = _objectives(individual)
                if obj is None:
                    continue
                evaluated.append((individual, obj))
            if not evaluated:
                logger.warning("pareto_no_valid_candidates_this_generation")
                continue
            vecs = [e[0] for e in evaluated]
            objs = [e[1] for e in evaluated]
            fronts = _fast_nondominated_sort(objs, directions)
            # Elitist truncation: fill the new population front-by-front.
            new_population: list[list[float]] = []
            for front in fronts:
                if len(new_population) + len(front) <= request.population_size:
                    new_population.extend(vecs[i] for i in front)
                else:
                    cd = _crowding_distance(objs, front)
                    ordered = sorted(front, key=lambda i: cd[i], reverse=True)
                    remaining = request.population_size - len(new_population)
                    new_population.extend(vecs[i] for i in ordered[:remaining])
                    break
            if new_population:
                population = new_population

        # Final evaluation for the returned front.
        final_eval: list[tuple[list[float], list[float]]] = []
        for individual in population:
            obj, _ = _objectives(individual)
            if obj is None:
                continue
            final_eval.append((individual, obj))
        if not final_eval:
            return ParetoResult(
                base_recipe_id=base_recipe.id, front=(), generations=request.generations
            )
        vecs = [e[0] for e in final_eval]
        objs = [e[1] for e in final_eval]
        fronts = _fast_nondominated_sort(objs, directions)
        cd_final = _crowding_distance(objs, fronts[0]) if fronts else {}

        points: list[ParetoPoint] = []
        for rank, layer in enumerate(fronts):
            for i in layer:
                mass = {c.name: v for c, v in zip(components, vecs[i], strict=True)}
                obj_dict = {t.property_code: objs[i][j] for j, t in enumerate(request.targets)}
                points.append(
                    ParetoPoint(
                        mass_percent=mass,
                        objectives=obj_dict,
                        rank=rank,
                        crowding_distance=cd_final.get(i, 0.0) if rank == 0 else 0.0,
                    )
                )

        front_points = tuple(p for p in points if p.rank == 0)
        return ParetoResult(
            base_recipe_id=base_recipe.id,
            front=front_points,
            all_points=tuple(points),
            generations=request.generations,
        )


__all__ = ["ParetoOptimiser", "ParetoPoint", "ParetoRequest", "ParetoResult"]
