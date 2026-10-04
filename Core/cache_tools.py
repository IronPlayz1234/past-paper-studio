"""Bounded caches and synchronization for shared application services."""
from collections import OrderedDict
from functools import wraps
from threading import RLock

_STATE_LOCK = RLock()

def synchronized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _STATE_LOCK:
            return function(*args, **kwargs)
    return wrapped

class BudgetCache(OrderedDict):
    def __init__(self, budget=64 * 1024 * 1024):
        super().__init__()
        self.budget = budget
        self.sizes = {}
        self.used = 0

    def get(self, key, default=None):
        if key not in self:
            return default
        self.move_to_end(key)
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        size = max(1, value.width() * value.height() * 4)
        if key in self:
            self.used -= self.sizes.pop(key)
            super().__delitem__(key)
        if size > self.budget:
            return
        super().__setitem__(key, value)
        self.sizes[key] = size
        self.used += size
        while self.used > self.budget:
            old, _ = super().popitem(last=False)
            self.used -= self.sizes.pop(old)

    def clear(self):
        super().clear()
        self.sizes.clear()
        self.used = 0
