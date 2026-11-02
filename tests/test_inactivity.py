import unittest
from unittest.mock import Mock

from relleno.inactivity import InactivityMinimizer


class FakeRoot:
    def __init__(self):
        self.bindings = {}
        self.callbacks = []

    def bind_all(self, sequence, callback, add=None):
        self.bindings[sequence] = callback

    def bind(self, sequence, callback, add=None):
        self.bindings[sequence] = callback

    def after(self, delay, callback):
        self.callbacks.append((delay, callback))


class InactivityTests(unittest.TestCase):
    def test_minimizes_tk_and_native_windows_after_one_minute(self):
        root = FakeRoot()
        now = [100.0]
        tk_minimizer = Mock()
        native_minimizer = Mock()
        idle = InactivityMinimizer(
            root,
            clock=lambda: now[0],
            tk_minimizer=tk_minimizer,
            native_minimizer=native_minimizer,
        )

        now[0] += 59
        idle.check()
        tk_minimizer.assert_not_called()

        now[0] += 1
        idle.check()
        tk_minimizer.assert_called_once_with(root)
        native_minimizer.assert_called_once_with()
        self.assertTrue(idle.minimized)

    def test_activity_restarts_timeout(self):
        root = FakeRoot()
        now = [10.0]
        tk_minimizer = Mock()
        idle = InactivityMinimizer(root, clock=lambda: now[0], tk_minimizer=tk_minimizer)

        now[0] += 50
        root.bindings['<ButtonPress>']()
        now[0] += 59
        idle.check()
        tk_minimizer.assert_not_called()

        now[0] += 1
        idle.check()
        tk_minimizer.assert_called_once_with(root)


if __name__ == '__main__':
    unittest.main()
