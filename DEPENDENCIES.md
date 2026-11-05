# Dependencies

Brief §0: pure Python 3.11+, standard library plus `pytest`. The offline run and the tests need nothing else. A live run also needs the official `anthropic` SDK and the packages it pulls in (second table).

| Dependency | Version (as installed) | Licence | Why |
|---|---|---|---|
| CPython | 3.14.7 (any 3.11+ works; `tomllib` is needed) | PSF-2.0 | runtime |
| pytest | 9.2.0 | MIT | test runner for the harness's tests, the agent's tests and the held-out suite |
| iniconfig | 2.3.1 | MIT | pulled in by pytest |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | pulled in by pytest |
| pluggy | 1.7.0 | MIT | pulled in by pytest |
| Pygments | 2.21.0 | BSD-2-Clause | pulled in by pytest |

Licences were read from each installed package's metadata (`License-Expression` / classifiers).

**Only for a live run** (installed 2026-11-04 with `pip install anthropic`):

| Dependency | Version | Licence |
|---|---|---|
| anthropic | 2.4.0 | Apache-2.0 |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.16.0 | MIT |
| docstring_parser | 0.18.0 | MIT |
| h11 | 0.16.0 | MIT |
| httpcore2 | 2.16.0 | BSD-3-Clause |
| httpx2 | 2.16.0 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| jiter | 0.18.0 | MIT |
| opentelemetry-api | 1.45.2 | Apache-2.0 |
| pydantic | 2.14.2 | MIT |
| pydantic_core | 2.50.2 | MIT |
| sniffio | 1.3.1 | MIT OR Apache-2.0 |
| truststore | 0.10.5 | MIT |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |

All are permissive licences; none requires the project to use a particular licence.

The Anthropic provider imports the SDK only when a live run starts; its tests pass a fake client.
(An earlier version of this file guessed the SDK's licence as "MIT"; its package metadata says
Apache-2.0.)

Deliberately **not** used:

- No other HTTP client library. The optional OpenAI-compatible provider uses `urllib.request` from
  the standard library behind an injectable transport (its tests use a fake transport).
- Nothing in this repository has called a live model.
- No `scipy`. Spearman's ρ and its bootstrap CI are implemented in `repro/stats.py` (average ranks
  for ties, Pearson on ranks).
- No `tomli`: Python ≥ 3.11 ships `tomllib`.

Install: `python3 -m venv .venv && .venv/bin/pip install pytest` (the `.venv/` folder is gitignored).
