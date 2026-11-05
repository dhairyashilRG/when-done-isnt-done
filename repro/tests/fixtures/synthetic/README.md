# Synthetic plumbing fixtures (origin: synthetic)

Hand-written "agent responses". Their only job is to drive every path of the harness end to end
offline. They are **not** model output and are not tuned to make any hypothesis reproduce. Every
response built from them is recorded with `origin: synthetic`, every results row that depends on one
is labelled `SYNTHETIC`, and such rows are excluded from all summary statistics.

The implementation in `impl/` is a variant of a straightforward Depot with a handful of gaps, so
that held-out failures, review comments, differential mismatches and gate classifications all have
something to process.
