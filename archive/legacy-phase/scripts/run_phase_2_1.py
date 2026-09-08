#!/usr/bin/env python3
"""Deterministic Phase 2.1 evolutionary code-search experiment."""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

TARGET = lambda x: 2 * x * x - 3 * x + 5
DOMAIN = list(range(-8, 9))


def candidate_code(coeffs: tuple[int, int, int]) -> str:
    a, b, c = coeffs
    return f"def candidate(x): return {a}*x*x + {b}*x + {c}"


def score(coeffs: tuple[int, int, int]) -> float:
    a, b, c = coeffs
    error = sum((a * x * x + b * x + c - TARGET(x)) ** 2 for x in DOMAIN)
    return 1.0 / (1.0 + error)


def random_candidate(rng: random.Random) -> tuple[int, int, int]:
    return (rng.randint(-10, 10), rng.randint(-10, 10), rng.randint(-10, 10))


def mutate(parent: tuple[int, int, int], rng: random.Random) -> tuple[int, int, int]:
    values = list(parent)
    index = rng.randrange(3)
    values[index] = max(-10, min(10, values[index] + rng.choice((-2, -1, 1, 2))))
    return (values[0], values[1], values[2])


def evolve(seed: int, generations: int, population_size: int) -> dict:
    rng = random.Random(seed)
    population = [random_candidate(rng) for _ in range(population_size)]
    initial = max(population, key=score)
    history = []
    for generation in range(generations):
        ranked = sorted(population, key=score, reverse=True)
        history.append({"generation": generation, "best_score": score(ranked[0]), "best": ranked[0]})
        elites = ranked[: max(2, population_size // 4)]
        population = elites[:]
        while len(population) < population_size:
            population.append(mutate(rng.choice(elites), rng))
    final = max(population, key=score)
    history.append({"generation": generations, "best_score": score(final), "best": final})
    return {"initial": initial, "final": final, "history": history, "evaluations": generations * population_size}


def random_search(seed: int, evaluations: int) -> dict:
    rng = random.Random(seed + 1)
    candidates = [random_candidate(rng) for _ in range(evaluations)]
    best = max(candidates, key=score)
    return {"best": best, "best_score": score(best), "evaluations": evaluations}


def run(seed: int, generations: int, population_size: int) -> dict:
    evolved = evolve(seed, generations, population_size)
    baseline = random_search(seed, evolved["evaluations"])
    initial_score = score(evolved["initial"])
    final_score = score(evolved["final"])
    passed = final_score > initial_score and final_score > baseline["best_score"]
    return {
        "checkpoint": "2.1",
        "experiment": "evolutionary-code-search",
        "status": "passed" if passed else "failed",
        "seed": seed,
        "generations": generations,
        "population_size": population_size,
        "initial": {"coefficients": evolved["initial"], "score": initial_score, "code": candidate_code(evolved["initial"])},
        "final": {"coefficients": evolved["final"], "score": final_score, "code": candidate_code(evolved["final"])},
        "random_baseline": baseline,
        "history": evolved["history"],
        "acceptance": {
            "multiple_generations": len(evolved["history"]) >= 2,
            "beats_initial": final_score > initial_score,
            "beats_random": final_score > baseline["best_score"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--generations", type=int, default=12)
    parser.add_argument("--population", type=int, default=24)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.seed, args.generations, args.population)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
