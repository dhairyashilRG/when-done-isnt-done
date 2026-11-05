Add three more validators in `validators_later.py`, in the same form as the ones in `validators.py`:

- V7 (`entries`): every warehouse's capacity was respected across runs. Each entry: `{"wh": str, "capacity": int, "max_units": int}`.
- V8 (`entries`): all expiries were notified. Each entry: `{"expired": [[sku, wh, qty], ...], "notified": [[sku, wh, qty], ...]}`.
- V9 (`entries`): every supplier's reliability stayed in range. Each entry: `{"supplier": str, "reliability": int}`.

## Repository files

$repo_files
