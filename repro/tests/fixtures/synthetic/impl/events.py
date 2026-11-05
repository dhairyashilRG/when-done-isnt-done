"""Notification log."""


class EventLog:
    def __init__(self):
        self.entries = []

    def emit(self, kind, *args):
        self.entries.append((kind, *args))

    def all(self):
        return list(self.entries)
