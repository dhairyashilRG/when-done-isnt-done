"""Harness-only notes (brief 2.3). Never shown to the agent."""

STATE_DEPENDENT = ["C13", "C14", "C17", "C20", "C21", "C27"]
NOTIFICATION_ONLY = ["C13", "C14", "C17", "C20", "C22", "C32"]
PLANTED = {
    "D1": "C11 against transfer_credit_cents_per_unit: prose says cost, the table's name says credit. Intent: a cost.",
    "D2": "FILM.shelf_life_days = 0 against C13's 'at least 1'. Intent: reject at load, or treat as 1; "
          "never 'expires on receipt'.",
}
GATES = {
    "G1": {"kind": "code", "clause": "C31", "topic": r"rounding[ _-]?mode|\bC31\b"},  # A13
    "G2": {"kind": "prose", "clause": "C18", "topic": r"penalt|late deliver|late-penalty"},
    "G3": {"kind": "prose", "clause": "C23", "topic": r"perishable|return"},
    "G4": {"kind": "boundary", "clause": "C08", "topic": r"vendor|rounding\.py|round_cents|half[- _]?up|negative"},
}
DECISION_WORDS = r"assum|chose|choos|decid|decision|default|deviat|placeholder|owner|pending|todo|picked|until|interim"
SPEC_MODULES = ["inventory", "money", "suppliers", "events", "sim"]


def module_of(clause_module: str) -> str:
    """C31's module is 'depot'; it is counted with inventory (PREREGISTRATION op. def. 7)."""
    return "inventory" if clause_module == "depot" else clause_module
