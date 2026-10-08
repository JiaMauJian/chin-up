"""用 webcam 偵測臉部位置，判斷是否烏龜頸 / 駝背。

原理：坐正時先校正一次，記下臉在畫面中的大小、高度與角度。
- 頭往前伸 → 臉離鏡頭變近 → 臉框變大
- 駝背 → 臉在畫面中往下掉
- 低頭 → 從鏡頭看，臉被壓扁：眼睛到嘴巴的距離變短，兩眼距離不變
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, fields
from pathlib import Path

import cv2

# OpenCV 官方的 YuNet 人臉偵測模型，來源：github.com/opencv/opencv_zoo
MODEL_PATH = Path(__file__).resolve().parent / "models" / "face_detection_yunet_2023mar.onnx"
DETECT_WIDTH = 320  # 縮小後再偵測，省電

cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)


@dataclass
class Sample:
    size: float  # 臉框寬度 / 畫面寬度
    y: float  # 臉框中心高度 / 畫面高度（0 = 最上面）
    pitch: float  # 眼睛到嘴巴的垂直距離 / 兩眼距離，低頭時變小


# 標準坐姿就是校正時的一個 Sample
Baseline = Sample


def median(samples: list[Sample]) -> Sample:
    return Sample(**{f.name: statistics.median(getattr(s, f.name) for s in samples) for f in fields(Sample)})


def assess(sample: Sample, baseline: Baseline, size_tol: float, y_tol: float, pitch_tol: float) -> str | None:
    """回傳姿勢問題的描述，姿勢正常則回傳 None。"""
    if sample.pitch < baseline.pitch * (1 - pitch_tol):
        return "低頭太久了，把頭抬起來、螢幕拉高一點"
    if sample.size > baseline.size * (1 + size_tol):
        return "頭往前伸了，把下巴收回來"
    if sample.y > baseline.y + y_tol:
        return "身體往下滑了，坐直一點"
    return None


class Camera:
    def __init__(self, index: int = 0):
        self.index = index
        self.cap: cv2.VideoCapture | None = None
        self.detector = cv2.FaceDetectorYN.create(
            str(MODEL_PATH), "", (DETECT_WIDTH, DETECT_WIDTH), score_threshold=0.7
        )

    def open(self) -> bool:
        cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            return False
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        ok, _ = cap.read()
        if not ok:
            cap.release()
            return False
        self.cap = cap
        return True

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def sample(self) -> Sample | None:
        """拍一張，回傳最大那張臉的位置；沒看到臉則回傳 None。"""
        if self.cap is None:
            return None
        # 丟掉緩衝區裡的舊畫面，拿最新的
        for _ in range(2):
            self.cap.grab()
        ok, frame = self.cap.read()
        if not ok:
            return None
        return self.find_face(frame)

    def find_face(self, frame) -> Sample | None:
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (DETECT_WIDTH, round(h * DETECT_WIDTH / w)))
        sh, sw = small.shape[:2]
        self.detector.setInputSize((sw, sh))
        _, faces = self.detector.detect(small)
        if faces is None or len(faces) == 0:
            return None
        # 每列：臉框 x, y, w, h，接著右眼、左眼、鼻尖、右嘴角、左嘴角的 (x, y)，最後是信心分數
        f = max(faces, key=lambda f: f[2] * f[3])
        x, y, fw, fh = f[:4]
        eye_y = (f[5] + f[7]) / 2
        eye_dist = max(abs(f[6] - f[4]), 1e-6)
        mouth_y = (f[11] + f[13]) / 2
        return Sample(
            size=float(fw / sw),
            y=float((y + fh / 2) / sh),
            pitch=float((mouth_y - eye_y) / eye_dist),
        )

    def calibrate(self, seconds: float = 3.0) -> Baseline | None:
        """連續取樣幾秒，用中位數當作標準坐姿。"""
        samples: list[Sample] = []
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            s = self.sample()
            if s is not None:
                samples.append(s)
            time.sleep(0.1)
        if len(samples) < 5:
            return None
        return median(samples)
