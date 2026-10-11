"""右下角的置頂提醒視窗。

Windows 11 常常吞掉系統匣的氣泡通知（勿擾模式也會擋），所以自己畫一個。
tkinter 只能在主執行緒操作，其他執行緒透過 show() 把訊息丟進佇列。
"""

from __future__ import annotations

import ctypes
import queue
import tkinter as tk
import webbrowser
from ctypes import wintypes

BG = "#1f2328"
FG = "#f0f3f6"
ACCENT = "#e6781e"
MUTED = "#8b949e"
FONT = "Microsoft JhengHei UI"
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

    def show(self, message: str, title: str, link: str | None = None, routine=None) -> None:
        """可以從任何執行緒呼叫。link 有值時多一個「看示範影片」可以點。

        routine 是 (次數, [(動作, 秒數), ...])，有值時視窗不會自己關，按「開始計時」一步步倒數。
        """
        self.queue.put(("show", title, message, link, routine))

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

    def _open(self, title: str, message: str, link: str | None, routine) -> None:
        self._close()
        win = tk.Toplevel(self.root, bg=BG, highlightthickness=2, highlightbackground=ACCENT)
        win.overrideredirect(True)
        win.attributes("-topmost", True)

        tk.Label(win, text=title, bg=BG, fg=ACCENT, font=(FONT, 14, "bold"),
                 anchor="w").pack(fill="x", padx=18, pady=(16, 4))
        tk.Label(win, text=message, bg=BG, fg=FG, font=(FONT, 13),
                 justify="left", anchor="w", wraplength=400).pack(fill="x", padx=18, pady=(0, 8))
        link_label = None
        if link:
            link_label = tk.Label(win, text="▶ 看示範影片", bg=BG, fg=ACCENT, cursor="hand2",
                                  font=(FONT, 12, "underline"), anchor="w")
            link_label.pack(fill="x", padx=18, pady=(0, 8))
        self.window = win

        if routine:
            # 要真的做完，所以不會自己關、點視窗也不會關
            buttons = tk.Frame(win, bg=BG)
            buttons.pack(fill="x", padx=18, pady=(4, 14))
            start = self._button(buttons, "開始計時", ACCENT)
            start.pack(side="left")
            start.bind("<Button-1>", lambda _: self._start(win, buttons, routine))
            skip = self._button(buttons, "略過", MUTED)
            skip.pack(side="right")
            skip.bind("<Button-1>", lambda _: self._close())
            if link_label is not None:
                link_label.bind("<Button-1>", lambda _: webbrowser.open(link))
            self._place(win)
            return

        tk.Label(win, text="點一下關閉", bg=BG, fg=MUTED, font=(FONT, 9),
                 anchor="e").pack(fill="x", padx=18, pady=(0, 12))
        self._place(win)
        for widget in (win, *win.winfo_children()):
            widget.bind("<Button-1>", lambda _: self._close())
        if link_label is not None:
            link_label.bind("<Button-1>", lambda _: (webbrowser.open(link), self._close()))
        self.hide_job = self.root.after(SHOW_SECONDS * 1000, self._close)

    def _button(self, parent: tk.Widget, text: str, color: str) -> tk.Label:
        return tk.Label(parent, text=text, bg=BG, fg=color, cursor="hand2",
                        font=(FONT, 12, "bold"), padx=10, pady=4,
                        highlightthickness=1, highlightbackground=color)

    def _place(self, win: tk.Toplevel) -> None:
        """貼齊右下角；內容變了要再叫一次。"""
        win.update_idletasks()
        _, _, right, bottom = _work_area()
        margin = 16
        win.geometry(f"+{right - win.winfo_width() - margin}+{bottom - win.winfo_height() - margin}")

    def _start(self, win: tk.Toplevel, buttons: tk.Frame, routine) -> None:
        buttons.destroy()
        reps, phases = routine
        # 最後一次做完就結束，不用再休息
        steps = [(n, name, secs) for n in range(1, reps + 1) for name, secs in phases][:-1]

        count = tk.Label(win, bg=BG, fg=MUTED, font=(FONT, 11), anchor="w")
        count.pack(fill="x", padx=18)
        timer = tk.Label(win, bg=BG, fg=ACCENT, font=(FONT, 28, "bold"))
        timer.pack(fill="x", padx=18, pady=(0, 4))
        stop = self._button(win, "停止", MUTED)
        stop.pack(anchor="e", padx=18, pady=(0, 14))
        stop.bind("<Button-1>", lambda _: self._close())

        def tick(i: int, left: int) -> None:
            if left == 0:
                i += 1
                if i == len(steps):
                    count.config(text="")
                    timer.config(text="完成！")
                    stop.destroy()
                    self.hide_job = self.root.after(3000, self._close)
                    return
                left = steps[i][2]
            n, name, _ = steps[i]
            count.config(text=f"第 {n}/{reps} 次")
            timer.config(text=f"{name}  {left}")
            self.hide_job = self.root.after(1000, tick, i, left - 1)

        tick(-1, 0)
        self._place(win)

    def _close(self) -> None:
        if self.hide_job is not None:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None
        if self.window is not None:
            self.window.destroy()
            self.window = None
