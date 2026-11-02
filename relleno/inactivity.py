"""Automatic minimization for unattended desktop windows."""
from __future__ import annotations

import os
import time


IDLE_TIMEOUT_SECONDS = 60
CHECK_INTERVAL_MS = 1000


def minimize_process_windows() -> None:
    """Minimize every visible top-level window owned by this process on Windows."""
    if os.name != "nt":
        return

    import ctypes
    from ctypes import wintypes

    current_pid = os.getpid()
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def minimize(hwnd, _lparam):
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == current_pid and user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        return True

    user32.EnumWindows(minimize, 0)


def minimize_tk_windows(root) -> None:
    """Minimize Tk windows, including application-owned dialogs."""
    pending = list(root.winfo_children())
    while pending:
        widget = pending.pop()
        try:
            pending.extend(widget.winfo_children())
            if widget.winfo_toplevel() is widget:
                widget.iconify()
        except Exception:
            continue
    root.iconify()


class InactivityMinimizer:
    def __init__(
        self,
        root,
        *,
        timeout_seconds: int = IDLE_TIMEOUT_SECONDS,
        check_interval_ms: int = CHECK_INTERVAL_MS,
        clock=time.monotonic,
        tk_minimizer=minimize_tk_windows,
        native_minimizer=minimize_process_windows,
    ):
        self.root = root
        self.timeout_seconds = timeout_seconds
        self.check_interval_ms = check_interval_ms
        self.clock = clock
        self.tk_minimizer = tk_minimizer
        self.native_minimizer = native_minimizer
        self.last_activity = clock()
        self.minimized = False

        for sequence in ("<KeyPress>", "<ButtonPress>", "<ButtonRelease>", "<Motion>", "<MouseWheel>"):
            root.bind_all(sequence, self.touch, add="+")
        root.bind("<Map>", self._mapped, add="+")
        root.after(self.check_interval_ms, self.check)

    def touch(self, _event=None) -> None:
        self.last_activity = self.clock()
        self.minimized = False

    def _mapped(self, event=None) -> None:
        if self.minimized and (event is None or getattr(event, "widget", self.root) is self.root):
            self.touch()

    def check(self) -> None:
        if self.clock() - self.last_activity >= self.timeout_seconds:
            # Repeat while idle so alerts created after the first timeout are also minimized.
            self.tk_minimizer(self.root)
            self.native_minimizer()
            self.minimized = True
        self.root.after(self.check_interval_ms, self.check)
