"""A scripted scenario that shows the depot works."""
from inventory import Depot

d = Depot(["A", "B"], {"A": 500, "B": 500}, 50_000, rounding_mode="ROUND_HALF_EVEN")
d.add_item("BOLT", 12, 50)
d.add_item("GLUE", 240, 5, shelf_life_days=7)
d.receive("BOLT", 100, "A")
d.ship("BOLT", 60, "A", 16)
d.transfer("BOLT", 10, "A", "B")
print("stock", d.stock("BOLT"), "cash", d.cash)
print(d.report())
print(d.notifications())
