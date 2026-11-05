"""Supplier reliability and orders."""


class SupplierBook:
    def __init__(self):
        self.reliability = {}
        self.orders = {}
        self.next_id = 1

    def place(self, supplier, sku, qty, due_day):
        self.reliability.setdefault(supplier, 3)
        order_id = self.next_id
        self.next_id += 1
        self.orders[order_id] = {"supplier": supplier, "sku": sku, "qty": qty, "due_day": due_day, "done": False}
        return order_id

    def suspended(self, supplier):
        return self.reliability.get(supplier, 3) <= 1

    def record(self, supplier, late):
        before = self.reliability[supplier]
        after = max(0, before - 1) if late else min(5, before + 1)
        self.reliability[supplier] = after
        return before > 1 and after <= 1
