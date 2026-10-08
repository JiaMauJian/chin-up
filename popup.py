"""右下角的置頂提醒視窗。

Windows 11 常常吞掉系統匣的氣泡通知（勿擾模式也會擋），所以自己畫一個。
tkinter 只能在主執行緒操作，其他執行緒透過 show() 把訊息丟進佇列。
"""

from __future__ import annotations

import ctypes
import queue
import tkinter as tk
from ctypes import wintypes

BG = "#1f2328"
FG = "#f0f3f6"
ACCENT = "#e6781e"
SHOW_SECONDS = 10


def _work_area() -> tuple[int, int, int, int]:
    """螢幕扣掉工作列的範圍：(left, top, right, bottom)。"""
    rect = wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
    return rect.left, rect.top, rect.right, rect.bottom


class Popups:
    def __init__(self) -> None:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 讓字在高解析度螢幕不糊
        self.root = tk.Tk()
        self.root.withdraw()
        self.queue: queue.Queue = queue.Queue()
        self.window: tk.Toplevel | None = None
        self.hide_job: str | None = None

    def show(self, message: str, title: str) -> None:
        """可以從任何執行緒呼叫。"""
        self.queue.put(("show", title, message))

    def quit(self) -> None:
        self.queue.put(("quit",))

    def mainloop(self) -> None:
        self._poll()
        self.root.mainloop()

    def _poll(self) -> None:
        while True:
            try:
                cmd = self.queue.get_nowait()
            except queue.Empty:
                break
            if cmd[0] == "quit":
                self.root.quit()
                return
            self._open(*cmd[1:])
        self.root.after(200, self._poll)

    def _open(self, title: str, message: str) -> None:
        self._close()
        win = tk.Toplevel(self.root, bg=BG, highlightthickness=2, highlightbackground=ACCENT)
        win.overrideredirect(True)
        win.attributes("-topmost", True)

        tk.Label(win, text=title, bg=BG, fg=ACCENT, font=("Microsoft JhengHei UI", 14, "bold"),
                 anchor="w").pack(fill="x", padx=18, pady=(16, 4))
        tk.Label(win, text=message, bg=BG, fg=FG, font=("Microsoft JhengHei UI", 13),
                 justify="left", anchor="w", wraplength=400).pack(fill="x", padx=18, pady=(0, 8))
        tk.Label(win, text="點一下關閉", bg=BG, fg="#8b949e", font=("Microsoft JhengHei UI", 9),
                 anchor="e").pack(fill="x", padx=18, pady=(0, 12))

        win.update_idletasks()
        _, _, right, bottom = _work_area()
        margin = 16
        win.geometry(f"+{right - win.winfo_width() - margin}+{bottom - win.winfo_height() - margin}")

        for widget in (win, *win.winfo_children()):
            widget.bind("<Button-1>", lambda _: self._close())
        self.window = win
        self.hide_job = self.root.after(SHOW_SECONDS * 1000, self._close)

    def _close(self) -> None:
        if self.hide_job is not None:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None
        if self.window is not None:
            self.window.destroy()
            self.window = None
