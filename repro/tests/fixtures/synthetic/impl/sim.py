"""Demand simulation."""
import random
import tomllib
from pathlib import Path


def simulate(days, seed):
    data = tomllib.loads(Path(__file__).with_name("data.toml").read_text())
    rng = random.Random(seed)
    demand = data["demand"]
    return [[(sku, rng.randint(demand[sku]["min"], demand[sku]["max"])) for sku in sorted(demand)]
            for _ in range(days)]
