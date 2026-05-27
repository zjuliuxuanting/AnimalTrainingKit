"""
模拟测试: 验证质心点判断 (center-point based) 区域进出状态机

精确复现 camera.js 中 startCameraDetection() 的状态机逻辑:
- has = best && best.count > 10 && pointInPolygon(best.cx, best.cy, z.points)
- 3帧防抖 + dwellFired标志 + 累计去重
"""

import pytest


class ZoneStateMachine:
    """精确复现 camera.js 中质心点判断的区域进出状态机"""

    def __init__(self, dwell_seconds=3, accumulate_n=5):
        self.dwell_seconds = dwell_seconds
        self.accumulate_n = accumulate_n
        self.DEBOUNCE_FRAMES = 3

        self.in_zone = {}
        self.dwell_timers = {}
        self.dwell_fired = {}
        self.accumulate_counts = {}
        self.accumulate_last_fired = {}
        self.enter_debounce = {}
        self.leave_debounce = {}

        self.events = []

    def _zone_id(self, z):
        return z["id"]

    def _point_in_polygon(self, px, py, points):
        """复现 camera.js 中 pointInPolygon() 的射线法"""
        inside = False
        j = len(points) - 1
        for i in range(len(points)):
            xi, yi = points[i]["x"], points[i]["y"]
            xj, yj = points[j]["x"], points[j]["y"]
            if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside

    def step(self, zone, blob_cx, blob_cy, blob_count, ts_ms):
        """
        每帧调用。blob_cx/cy 为检测到的物体质心，blob_count 为 blob 像素数。
        传 (None, None, 0) 表示未检测到物体。
        """
        zid = self._zone_id(zone)
        had = self.in_zone.get(zid, False)
        has = (
            blob_cx is not None
            and blob_cy is not None
            and blob_count > 10
            and self._point_in_polygon(blob_cx, blob_cy, zone["points"])
        )

        if has:
            self.enter_debounce[zid] = self.enter_debounce.get(zid, 0) + 1
            self.leave_debounce[zid] = 0
        else:
            self.leave_debounce[zid] = self.leave_debounce.get(zid, 0) + 1
            self.enter_debounce[zid] = 0

        if self.enter_debounce[zid] >= self.DEBOUNCE_FRAMES and not had:
            self.in_zone[zid] = True
            self.dwell_timers[zid] = ts_ms
            self.dwell_fired[zid] = False
            self.accumulate_counts[zid] = self.accumulate_counts.get(zid, 0) + 1
            self.events.append(("enter", zone["name"], self.accumulate_counts[zid], ts_ms))

        elif self.enter_debounce[zid] >= self.DEBOUNCE_FRAMES and had:
            if (self.dwell_timers.get(zid) and not self.dwell_fired.get(zid)
                    and (ts_ms - self.dwell_timers[zid]) > self.dwell_seconds * 1000):
                self.events.append(("dwell", zone["name"], self.dwell_seconds, ts_ms))
                self.dwell_fired[zid] = True

            acc_count = self.accumulate_counts.get(zid, 0)
            if (acc_count >= self.accumulate_n
                    and acc_count > self.accumulate_last_fired.get(zid, 0)
                    and acc_count % self.accumulate_n == 0):
                self.events.append(("accumulate", zone["name"], acc_count, ts_ms))
                self.accumulate_last_fired[zid] = acc_count

        elif self.leave_debounce[zid] >= self.DEBOUNCE_FRAMES and had:
            self.in_zone[zid] = False
            self.dwell_timers[zid] = 0
            self.dwell_fired[zid] = False
            self.events.append(("leave", zone["name"], None, ts_ms))


class TestZoneStateMachine:
    """验证质心点判断区域进出状态机"""

    @pytest.fixture
    def zone_a(self):
        """200x200 正方形区域，左上角 (100, 100)"""
        return {
            "id": "zone_0",
            "name": "区域 A",
            "points": [
                {"x": 100, "y": 100},
                {"x": 300, "y": 100},
                {"x": 300, "y": 300},
                {"x": 100, "y": 300},
            ],
        }

    @pytest.fixture
    def sm(self):
        return ZoneStateMachine()

    # --- helpers ---
    IN = (200, 200, 500)     # blob 在区域中心 (100,100)-(300,300)
    OUT = (50, 50, 500)      # blob 在区域外
    NONE = (None, None, 0)   # 未检测到物体

    def _run_frames(self, sm, zone, steps, ts_start):
        """steps: [(cx, cy, count, num_frames), ...]"""
        ts = ts_start
        for cx, cy, count, frames in steps:
            for _ in range(frames):
                sm.step(zone, cx, cy, count, ts)
                ts += 200
        return ts

    def test_single_enter_leave(self, sm, zone_a):
        """质心从外→内→外: 应检测1进1出"""
        ts = self._run_frames(sm, zone_a, [
            (*self.OUT, 5),    # 外 5帧
            (*self.IN, 10),    # 内 10帧 → 3帧后确认进入
            (*self.OUT, 10),   # 外 10帧 → 3帧后确认离开
        ], 1000000)

        enters = [e for e in sm.events if e[0] == "enter"]
        leaves = [e for e in sm.events if e[0] == "leave"]
        assert len(enters) == 1, f"应该是1次进入，实际{len(enters)}次"
        assert len(leaves) == 1, f"应该是1次离开，实际{len(leaves)}次"
        assert enters[0][2] == 1

    def test_five_consecutive_enter_leave(self, sm, zone_a):
        """质心进出 ×5: 应检测5进5出"""
        ts = self._run_frames(sm, zone_a, [(*self.OUT, 5)], 1000000)
        for _ in range(5):
            ts = self._run_frames(sm, zone_a, [
                (*self.IN, 10),
                (*self.OUT, 10),
            ], ts)

        enters = [e for e in sm.events if e[0] == "enter"]
        leaves = [e for e in sm.events if e[0] == "leave"]
        assert len(enters) == 5, (
            f"应该是5次进入, 实际{len(enters)}次: {[e[2] for e in enters]}"
        )
        assert len(leaves) == 5, f"应该是5次离开, 实际{len(leaves)}次"
        for i, (enter, leave) in enumerate(zip(enters, leaves)):
            assert enter[2] == i + 1
            assert enter[3] < leave[3]

    def test_dwell_event_per_cycle(self, sm, zone_a):
        """每次停留 >3s 触发驻留"""
        ts = self._run_frames(sm, zone_a, [(*self.OUT, 5)], 1000000)
        for _ in range(3):
            ts = self._run_frames(sm, zone_a, [
                (*self.IN, 5),    # 进入
                (*self.IN, 20),   # 停留 (20帧×200ms=4s > 3s)
                (*self.OUT, 10),  # 离开
            ], ts)

        dwells = [e for e in sm.events if e[0] == "dwell"]
        assert len(dwells) == 3, f"每个停留周期应触发1次驻留, 实际{len(dwells)}次"

    def test_noise_filtering_no_false_enter(self, sm, zone_a):
        """质心瞬时掠过区域边界不足3帧不触发"""
        ts = self._run_frames(sm, zone_a, [(*self.OUT, 10)], 1000000)

        # 1帧进入 + 2帧外出 → 不足DEBOUNCE_FRAMES
        sm.step(zone_a, *self.IN, ts); ts += 200
        sm.step(zone_a, *self.OUT, ts); ts += 200
        sm.step(zone_a, *self.OUT, ts); ts += 200

        enters = [e for e in sm.events if e[0] == "enter"]
        assert len(enters) == 0, f"瞬时掠过不应触发进入, 实际{len(enters)}次"

    def test_brief_exit_not_leave(self, sm, zone_a):
        """短暂离开不足3帧不应触发离开"""
        ts = self._run_frames(sm, zone_a, [
            (*self.OUT, 5),
            (*self.IN, 10),    # 确认进入
        ], 1000000)
        assert len([e for e in sm.events if e[0] == "enter"]) == 1

        # 离开2帧即返回
        sm.step(zone_a, *self.OUT, ts); ts += 200
        sm.step(zone_a, *self.OUT, ts); ts += 200
        self._run_frames(sm, zone_a, [(*self.IN, 10)], ts)

        leaves = [e for e in sm.events if e[0] == "leave"]
        assert len(leaves) == 0, f"短暂离开不足3帧不应触发离开, 实际{len(leaves)}次"

    def test_accumulate_fires_once_per_milestone(self, sm, zone_a):
        """累计每N次仅触发一次"""
        sm2 = ZoneStateMachine(accumulate_n=2)
        ts = 1000000
        for _ in range(4):
            ts = self._run_frames(sm2, zone_a, [
                (*self.IN, 10),
                (*self.OUT, 10),
            ], ts)

        acc_events = [e for e in sm2.events if e[0] == "accumulate"]
        assert len(acc_events) == 2, f"应为2次(第2/4次), 实际{len(acc_events)}次"
        assert acc_events[0][2] == 2
        assert acc_events[1][2] == 4

    def test_event_sequence_order(self, sm, zone_a):
        """进入→驻留→离开 序列有序"""
        ts = 1000000
        for _ in range(3):
            ts = self._run_frames(sm, zone_a, [
                (*self.IN, 10),   # 进入
                (*self.IN, 20),   # 停留触发驻留
            ], ts)
            ts = self._run_frames(sm, zone_a, [(*self.OUT, 10)], ts)

        sequence = [e[0] for e in sm.events]
        assert sequence == ["enter", "dwell", "leave"] * 3, (
            f"序列应为 enter/dwell/leave×3, 实际 {sequence}"
        )

    def test_dwell_not_refire_same_cycle(self, sm, zone_a):
        """同周期驻留仅触发1次"""
        ts = self._run_frames(sm, zone_a, [
            (*self.OUT, 5),
            (*self.IN, 10),
        ], 1000000)
        self._run_frames(sm, zone_a, [(*self.IN, 50)], ts)  # 10秒停留

        dwells = [e for e in sm.events if e[0] == "dwell"]
        assert len(dwells) == 1, f"同周期驻留仅1次, 实际{len(dwells)}次"

    def test_no_blob_all_zones_false(self, sm, zone_a):
        """未检测到物体时所有区域 has=false"""
        ts = self._run_frames(sm, zone_a, [(*self.NONE, 10)], 1000000)
        assert len(sm.events) == 0, "无物体时不应有任何事件"

    def test_blob_outside_all_zones_false(self, sm, zone_a):
        """物体在区域外时 has=false"""
        ts = self._run_frames(sm, zone_a, [(*self.OUT, 10)], 1000000)
        assert len(sm.events) == 0, "物体在区域外不应有任何事件"
