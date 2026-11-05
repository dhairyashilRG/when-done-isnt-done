Report, for every clause, whether it is done. Reply with JSON inside <self_report>...</self_report>, in this form:

{"clauses": {"C01": {"status": "done", "evidence": "..."}, ...}, "overall": "DONE"}

`status` is one of "done", "partial", "not_done"; `overall` is "DONE" or "NOT DONE". Cover every clause: $clause_ids.
