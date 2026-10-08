"""chin-up：常駐系統匣的坐姿提醒小工具。

- 久坐提醒：連續使用電腦一段時間就提醒你起來動一動（離開電腦會自動重新計時）
- 姿勢偵測：有 webcam 時，偵測到烏龜頸或駝背持續一陣子就提醒你
"""

from __future__ import annotations

import ctypes
import json
import logging
import random
import threading
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from popup import Popups
from posture import Baseline, Camera, Sample, assess, median

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"

DEFAULTS = {
    "sit_minutes": 15,  # 連續坐多久提醒一次
    "idle_reset_minutes": 5,  # 離開電腦超過這麼久，久坐計時歸零
    "use_camera": True,
    "camera_index": 0,
    "check_interval_seconds": 2,  # 多久看一次姿勢
    "bad_posture_seconds": 10,  # 姿勢不良持續多久才提醒
    "posture_cooldown_seconds": 60,  # 兩次姿勢提醒的最短間隔
    "size_tolerance": 0.15,  # 臉框比校正時大多少算頭往前（0.15 = 15%）
    "y_tolerance": 0.06,  # 臉比校正時低多少算駝背（畫面高度的比例）
    "pitch_tolerance": 0.07,  # 臉的上下比例比校正時扁多少算低頭（0.07 = 7%）
    "debug": False,  # true 時每次偵測的數值都寫進 chin-up.log
    "baseline": None,
}

COLORS = {
    "good": (46, 160, 67),
    "bad": (230, 120, 20),
    "away": (120, 120, 120),
    "paused": (120, 120, 120),
    "timer": (40, 110, 200),  # 沒有鏡頭，只做久坐提醒
}

STATUS_TEXT = {
    "good": "姿勢良好",
    "bad": "姿勢不良",
    "away": "沒看到人",
    "paused": "已暫停",
    "timer": "僅久坐提醒（沒有鏡頭）",
    "starting": "啟動中…",
}

# 右鍵選單裡可以選的提醒間隔（分鐘）
SIT_CHOICES = [10, 15, 20, 30, 45, 60]

# 久坐提醒時輪流顯示的運動：(名稱, 做法)
EXERCISES = [
    ("收下巴", "坐直看前方，下巴往後平推（像做出雙下巴），頭不低也不抬。停 5 秒，做 10 次。"),
    ("擴胸夾背", "雙手往兩側打開，肩胛骨往中間、往下夾。停 5 秒，做 10 次。"),
    ("門框伸展", "前臂貼著門框兩側、手肘與肩同高，身體往前傾到胸口有拉緊感。停 30 秒，做 2 次。"),
    ("靠牆天使", "背靠牆，後腦、上背、屁股貼牆，雙手成 W 貼牆，慢慢往上滑成 Y 再滑回。做 10 次。"),
    ("胸椎伸展", "坐著雙手抱頭，上背抵住椅背上緣往後仰。停 3 秒，做 10 次。"),
    ("斜方肌伸展", "右手抓住椅子邊，頭往左側傾，左手輕輕把頭往左帶。停 20 秒，換邊。"),
]

logging.basicConfig(
    filename=HERE / "chin-up.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
log = logging.getLogger("chin-up")


def load_config() -> dict:
    config = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        config.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    return config


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds() -> float:
    """距離上次滑鼠或鍵盤操作過了幾秒。"""
    info = _LastInputInfo(cbSize=ctypes.sizeof(_LastInputInfo))
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    millis = (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return millis / 1000


def make_icon(color: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=color)
    # 一個往上的箭頭：chin up
    draw.polygon([(32, 14), (48, 34), (38, 34), (38, 50), (26, 50), (26, 34), (16, 34)], fill="white")
    return img


class App:
    def __init__(self) -> None:
        self.config = load_config()
        self.popups = Popups()
        self.stop = threading.Event()
        self.paused = False
        self.calibrate_requested = threading.Event()
        self.state = "starting"
        self.sit_start = time.monotonic()
        self.next_exercise = random.randrange(len(EXERCISES))
        self.icon = pystray.Icon(
            "chin-up",
            make_icon(COLORS["away"]),
            "chin-up",
            menu=pystray.Menu(
                pystray.MenuItem(lambda _: f"狀態：{STATUS_TEXT[self.state]}", None, enabled=False),
                pystray.MenuItem(lambda _: f"已連續坐 {self._sit_minutes()} 分鐘", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    lambda _: f"提醒間隔：{self.config['sit_minutes']} 分鐘",
                    pystray.Menu(
                        *(
                            self._interval_item(m)
                            for m in sorted({*SIT_CHOICES, self.config["sit_minutes"]})
                        )
                    ),
                ),
                pystray.MenuItem("重新校正坐姿", self._on_calibrate, enabled=lambda _: self.state != "timer"),
                pystray.MenuItem("重設久坐計時", self._on_reset_sit),
                pystray.MenuItem("暫停", self._on_toggle_pause, checked=lambda _: self.paused),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("結束", self._on_quit),
            ),
        )

    # ---- 共用 ----

    def run(self) -> None:
        # tkinter 要在主執行緒，系統匣圖示改在背景跑
        self.icon.run_detached()
        self.icon.visible = True
        self.notify("已在背景執行，右鍵點右下角的箭頭圖示可以設定。", "chin-up 已啟動")
        threading.Thread(target=self._guard(self._sit_loop), daemon=True).start()
        threading.Thread(target=self._guard(self._posture_loop), daemon=True).start()
        self.popups.mainloop()

    def _guard(self, fn):
        def wrapper():
            try:
                fn()
            except Exception:
                log.exception("%s crashed", fn.__name__)
                self.notify("chin-up 出錯了，詳情請看 chin-up.log")

        return wrapper

    def notify(self, message: str, title: str = "chin-up") -> None:
        log.info("notify: %s", message)
        self.popups.show(message, title)

    def set_state(self, state: str) -> None:
        if state == self.state:
            return
        log.info("state: %s -> %s", self.state, state)
        self.state = state
        self.icon.icon = make_icon(COLORS.get(state, COLORS["away"]))
        self.icon.title = f"chin-up：{STATUS_TEXT[state]}"
        self.icon.update_menu()

    def _sit_minutes(self) -> int:
        return int((time.monotonic() - self.sit_start) // 60)

    # ---- 選單 ----

    def _interval_item(self, minutes: int) -> pystray.MenuItem:
        def choose(icon, item):
            self.config["sit_minutes"] = minutes
            save_config(self.config)
            log.info("sit_minutes -> %d", minutes)
            icon.update_menu()

        return pystray.MenuItem(
            f"{minutes} 分鐘",
            choose,
            checked=lambda _: self.config["sit_minutes"] == minutes,
            radio=True,
        )

    def _on_calibrate(self, icon, item) -> None:
        self.calibrate_requested.set()

    def _on_reset_sit(self, icon, item) -> None:
        self.sit_start = time.monotonic()
        icon.update_menu()

    def _on_toggle_pause(self, icon, item) -> None:
        self.paused = not self.paused
        self.sit_start = time.monotonic()
        icon.update_menu()

    def _on_quit(self, icon, item) -> None:
        self.stop.set()
        icon.stop()
        self.popups.quit()

    # ---- 久坐提醒 ----

    def _sit_loop(self) -> None:
        while not self.stop.wait(15):
            if self.paused or idle_seconds() >= self.config["idle_reset_minutes"] * 60:
                self.sit_start = time.monotonic()
            elif time.monotonic() - self.sit_start >= self.config["sit_minutes"] * 60:
                name, how = EXERCISES[self.next_exercise]
                self.next_exercise = (self.next_exercise + 1) % len(EXERCISES)
                self.notify(
                    f"已經坐了 {self.config['sit_minutes']} 分鐘，起來動一動。\n\n{name}：{how}",
                    "該起來動一動了",
                )
                self.sit_start = time.monotonic()
            self.icon.update_menu()

    # ---- 姿勢偵測 ----

    def _posture_loop(self) -> None:
        cfg = self.config
        if not cfg["use_camera"]:
            self.set_state("timer")
            return

        camera = Camera(cfg["camera_index"])
        if not camera.open():
            log.info("no camera, timer-only mode")
            self.set_state("timer")
            return

        try:
            baseline = Baseline(**cfg["baseline"])
        except TypeError:  # 還沒校正過，或是舊版的校正資料
            baseline = None
        if baseline is None:
            self.calibrate_requested.set()

        recent: deque[Sample] = deque(maxlen=5)
        bad_since: float | None = None
        last_alert = 0.0

        try:
            while not self.stop.is_set():
                if self.paused:
                    camera.close()  # 暫停時關掉鏡頭
                    self.set_state("paused")
                    self.stop.wait(1)
                    continue
                if camera.cap is None and not camera.open():
                    self.set_state("timer")
                    self.stop.wait(30)
                    continue

                if self.calibrate_requested.is_set():
                    self.calibrate_requested.clear()
                    baseline = self._calibrate(camera) or baseline
                    recent.clear()
                    bad_since = None
                    if baseline is None:
                        self.stop.wait(10)
                        self.calibrate_requested.set()
                        continue

                sample = camera.sample()
                if sample is None:
                    recent.clear()
                    bad_since = None
                    self.set_state("away")
                else:
                    recent.append(sample)
                    smoothed = median(list(recent))
                    problem = assess(
                        smoothed, baseline, cfg["size_tolerance"], cfg["y_tolerance"], cfg["pitch_tolerance"]
                    )
                    if cfg["debug"]:
                        log.info(
                            "size %+.0f%% (tol %.0f%%), y %+.3f (tol %.3f), pitch %+.0f%% (tol -%.0f%%) -> %s",
                            (smoothed.size / baseline.size - 1) * 100,
                            cfg["size_tolerance"] * 100,
                            smoothed.y - baseline.y,
                            cfg["y_tolerance"],
                            (smoothed.pitch / baseline.pitch - 1) * 100,
                            cfg["pitch_tolerance"] * 100,
                            problem or "ok",
                        )
                    now = time.monotonic()
                    if problem is None:
                        bad_since = None
                        self.set_state("good")
                    else:
                        bad_since = bad_since or now
                        self.set_state("bad")
                        if (
                            now - bad_since >= cfg["bad_posture_seconds"]
                            and now - last_alert >= cfg["posture_cooldown_seconds"]
                        ):
                            self.notify(problem, "注意坐姿")
                            last_alert = now

                self.stop.wait(cfg["check_interval_seconds"])
        finally:
            camera.close()

    def _calibrate(self, camera: Camera) -> Baseline | None:
        self.notify("請坐正、看著螢幕，3 秒後開始校正。", "校正坐姿")
        self.stop.wait(3)
        baseline = camera.calibrate(seconds=3)
        if baseline is None:
            self.notify("沒看清楚你的臉，10 秒後再試一次。", "校正失敗")
            return None
        self.config["baseline"] = asdict(baseline)
        save_config(self.config)
        log.info("calibrated: %s", baseline)
        self.notify("校正完成，之後姿勢跑掉會提醒你。", "校正完成")
        return baseline


def already_running() -> bool:
    """用 Windows 具名 mutex 確保只跑一份。"""
    already_running.handle = ctypes.windll.kernel32.CreateMutexW(None, False, "chin-up-single-instance")
    return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


if __name__ == "__main__":
    if not already_running():
        App().run()
