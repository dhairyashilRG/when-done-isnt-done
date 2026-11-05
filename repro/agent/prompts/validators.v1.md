The harness collects outputs from depot runs. Write validators over those outputs in `validators.py`.

$form
$rule
The validators:

- V1 (`rows`): every report row's value matches units × cost. Each row: `{"sku": str, "wh": str, "units": int, "value_cents": int, "unit_cost": int}`.
- V2 (`runs`): all notification types in the spec were seen across a set of runs. Each run is a list of notifications; a notification is a tuple whose first element is its type.
- V3 (`pairs`): two runs with the same seed are identical. Each pair: `{"seed": int, "a": <run output>, "b": <run output>}`.
- V4 (`days`): storage cost stayed within a budget. Each day: `{"day": int, "storage_cost_cents": int, "budget_cents": int}`.
- V5 (`clauses`): every clause has at least one test. Each entry: `{"clause_id": str, "tests": [str, ...]}`.
- V6 (`pairs`): results from two implementations agree on every compared pair. Each pair: `{"key": str, "a": object, "b": object}`.

## The spec, for reference

$spec
