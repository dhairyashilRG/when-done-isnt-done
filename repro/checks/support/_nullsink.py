"""pytest plugin / bootstrap for E1b: disable the notification log (a null sink).

Every Depot-like class's ``notifications()`` returns an empty list, so nothing that reads the log
can see a notification.
"""
import _impl_lookup


def install():
    for cls in _impl_lookup.depot_classes(_impl_lookup.modules()):
        if hasattr(cls, "notifications"):
            cls.notifications = lambda self, *a, **k: []


def pytest_configure(config):
    install()
