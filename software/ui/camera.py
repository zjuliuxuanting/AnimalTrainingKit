"""
CameraSource — 摄像头信号源

基于 OpenCV 接入 USB 摄像头，实现 SignalSource 接口。
支持基本运动检测，将视频帧分析结果作为信号输入投喂到实验引擎。

类 EthoVision XT 理念：
- 摄像头是实验信号的"第一公民"，与设备传感器地位平等
- 运动检测可触发实验流程节点（开始/结束/条件/记录）
- 帧时间戳纳入统一时间线，与所有其他事件对齐
"""

from __future__ import annotations

import asyncio
import threading
import time
import logging
from typing import Optional, Callable, List, Tuple, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger("BehaviorBox.CameraSource")

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from protocol.signal_source import SignalSource, SourceType, SourceState, SignalEvent


@dataclass
class MotionConfig:
    enabled: bool = True
    threshold: int = 25
    min_area: int = 500
    cooldown_ms: int = 500
    analysis_interval_frames: int = 3
    roi_x: float = 0.0
    roi_y: float = 0.0
    roi_w: float = 1.0
    roi_h: float = 1.0


class CameraSource(SignalSource):
    """摄像头信号源 — 实现 SignalSource 接口 + 运动检测"""

    def __init__(
        self,
        source_id: str = "camera:0",
        camera_index: int = 0,
        fps: int = 15,
        motion: Optional[MotionConfig] = None,
    ):
        super().__init__(source_id, SourceType.CAMERA)
        if not HAS_CV2:
            raise ImportError("opencv-python 未安装，请执行: pip install opencv-python")

        self._camera_index = camera_index
        self._fps = fps
        self._motion = motion or MotionConfig()

        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._frame_index: int = 0
        self._started_at: float = 0.0

        self._prev_gray: Optional["np.ndarray"] = None
        self._last_motion_emit_ms: int = 0
        self._motion_active: bool = False
        self._frame_buffer: List[Dict[str, Any]] = []
        self._max_buffer = 300

    def list_signals(self) -> List[str]:
        return [
            f"{self._source_id}:frame",
            f"{self._source_id}:motion_start",
            f"{self._source_id}:motion_stop",
            f"{self._source_id}:motion_active",
            f"{self._source_id}:motion_level",
        ]

    async def start(self) -> bool:
        self._set_state(SourceState.STARTING)

        loop = asyncio.get_event_loop()
        ready = loop.create_future()

        def _init():
            try:
                self._cap = cv2.VideoCapture(self._camera_index)
                if not self._cap.isOpened():
                    loop.call_soon_threadsafe(ready.set_result, False)
                    return
                self._cap.set(cv2.CAP_PROP_FPS, self._fps)
                self._frame_index = 0
                self._started_at = time.time()
                self._prev_gray = None
                self._motion_active = False
                self._last_motion_emit_ms = 0
                self._frame_buffer.clear()
                self._stop_event.clear()
                loop.call_soon_threadsafe(ready.set_result, True)
            except Exception as e:
                logger.exception("摄像头初始化失败")
                loop.call_soon_threadsafe(ready.set_result, False)

        t = threading.Thread(target=_init, daemon=True)
        t.start()

        ok = await ready
        if not ok:
            self._set_state(SourceState.ERROR)
            return False

        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        self._set_state(SourceState.RUNNING)
        logger.info(f"CameraSource 已启动: camera={self._camera_index}, fps={self._fps}, motion_threshold={self._motion.threshold}")
        return True

    async def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._thread.join, 3.0)
            self._thread = None
        if self._cap:
            self._cap.release()
            self._cap = None
        self._set_state(SourceState.STOPPED)
        logger.info(f"CameraSource 已停止: 共采集 {self._frame_index} 帧")

    def _capture_loop(self):
        interval = 1.0 / self._fps
        last_capture = 0.0
        analysis_counter = 0

        while not self._stop_event.is_set():
            now = time.time()
            if now - last_capture < interval:
                time.sleep(0.001)
                continue
            last_capture = now

            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            self._frame_index += 1
            ts_ms = int((now - self._started_at) * 1000)

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            if self._motion.enabled and self._prev_gray is not None:
                analysis_counter += 1
                if analysis_counter >= self._motion.analysis_interval_frames:
                    analysis_counter = 0
                    self._detect_motion(gray, ts_ms)

            self._prev_gray = gray

            if self._frame_index % self._fps == 0:
                self._emit(
                    f"{self._source_id}:frame",
                    self._frame_index,
                    {"ts_ms": ts_ms, "fps": self._fps},
                )

            self._frame_buffer.append({
                "index": self._frame_index,
                "ts_ms": ts_ms,
            })
            if len(self._frame_buffer) > self._max_buffer:
                self._frame_buffer = self._frame_buffer[-self._max_buffer:]

    def _detect_motion(self, gray: "np.ndarray", ts_ms: int):
        frame_delta = cv2.absdiff(self._prev_gray, gray)
        thresh = cv2.threshold(frame_delta, self._motion.threshold, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        motion_level = 0
        for contour in contours:
            area = cv2.contourArea(contour)
            if area >= self._motion.min_area:
                x, y, w, h = cv2.boundingRect(contour)
                rx = self._motion.roi_x * gray.shape[1]
                ry = self._motion.roi_y * gray.shape[0]
                rr = rx + self._motion.roi_w * gray.shape[1]
                rb = ry + self._motion.roi_h * gray.shape[0]
                cx = x + w / 2
                cy = y + h / 2
                if rx <= cx <= rr and ry <= cy <= rb:
                    motion_level += area

        self._emit(
            f"{self._source_id}:motion_level",
            motion_level,
            {"ts_ms": ts_ms, "frame_index": self._frame_index},
        )

        if motion_level >= self._motion.min_area:
            if not self._motion_active:
                cooldown_ok = (ts_ms - self._last_motion_emit_ms) >= self._motion.cooldown_ms
                if cooldown_ok:
                    self._motion_active = True
                    self._last_motion_emit_ms = ts_ms
                    self._emit(
                        f"{self._source_id}:motion_start",
                        motion_level,
                        {"ts_ms": ts_ms, "frame_index": self._frame_index},
                    )
                    logger.debug(f"运动开始: level={motion_level}, frame={self._frame_index}")
            self._emit(
                f"{self._source_id}:motion_active",
                motion_level,
                {"ts_ms": ts_ms},
            )
        else:
            if self._motion_active:
                self._motion_active = False
                self._last_motion_emit_ms = ts_ms
                self._emit(
                    f"{self._source_id}:motion_stop",
                    0,
                    {"ts_ms": ts_ms, "frame_index": self._frame_index},
                )
                logger.debug(f"运动停止: frame={self._frame_index}")

    @property
    def frame_count(self) -> int:
        return self._frame_index

    def get_frame_at(self, ts_ms: int, tolerance_ms: int = 50) -> Optional[Dict[str, Any]]:
        best = None
        best_diff = tolerance_ms + 1
        for f in self._frame_buffer:
            diff = abs(f["ts_ms"] - ts_ms)
            if diff < best_diff:
                best_diff = diff
                best = f
        return best

    @staticmethod
    def list_cameras() -> List[Tuple[int, str]]:
        if not HAS_CV2:
            return []
        cameras = []
        for i in range(5):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                cameras.append((i, f"Camera {i}"))
                cap.release()
        return cameras

    @staticmethod
    def available() -> bool:
        return HAS_CV2
