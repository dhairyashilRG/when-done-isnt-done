PY ?= .venv/bin/python

.PHONY: repro test estimate cold figure

repro:
	$(PY) -m repro run --offline

test:
	$(PY) -m pytest -q

estimate:
	$(PY) -m repro estimate

cold:
	rm -rf .cache && $(PY) -m repro run --offline --rebuild-synthetic

figure:
	$(PY) figures/make_summary_figure.py
