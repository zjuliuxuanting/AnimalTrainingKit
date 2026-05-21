"""
ECharts 可视化图表

基于 QWebEngineView 嵌入 ECharts，提供统一美观的图表风格。
V1 重点：事件时间序列图、跨天实验对比视图。
"""

from __future__ import annotations

import json
import os
from typing import Optional, Dict, List, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QComboBox, QLabel, QSplitter,
)
from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtWebEngineWidgets import QWebEngineView

# ECharts CDN
ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"

# 统一配色方案
CHART_COLORS = [
    "#5470C6", "#91CC75", "#FAC858", "#EE6666",
    "#73C0DE", "#3BA272", "#FC8452", "#9A60B4",
    "#EA7CCC", "#48B8D0",
]

BASE_STYLE = """
<style>
  body { margin: 0; padding: 0; background: #fff; font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; }
  #chart { width: 100%; height: 100vh; }
</style>
"""

CHART_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="{echarts_cdn}"></script>
{style}
</head>
<body>
<div id="chart"></div>
<script>
const chart = echarts.init(document.getElementById('chart'), null, {{ locale: 'ZH' }});
function renderChart(option) {{
    chart.setOption(JSON.parse(option), true);
}}
window.addEventListener('resize', function() {{ chart.resize(); }});
</script>
</body>
</html>
"""


def _build_time_series_option(
    title: str,
    x_data: List[str],
    series_list: List[Dict[str, Any]],
    y_label: str = "事件数",
) -> str:
    option = {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": [s["name"] for s in series_list], "bottom": 0},
        "grid": {"left": "3%", "right": "4%", "bottom": "10%", "containLabel": True},
        "xAxis": {
            "type": "category",
            "boundaryGap": False,
            "data": x_data,
        },
        "yAxis": {"type": "value", "name": y_label},
        "series": [],
        "color": CHART_COLORS,
    }
    for s in series_list:
        option["series"].append({
            "name": s["name"],
            "type": "line",
            "data": s["data"],
            "smooth": True,
            "symbol": "emptyCircle",
            "symbolSize": 6,
        })
    return json.dumps(option, ensure_ascii=False)


def _build_daily_bar_option(
    title: str,
    categories: List[str],
    series_list: List[Dict[str, Any]],
    y_label: str = "事件数",
) -> str:
    option = {
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "legend": {"data": [s["name"] for s in series_list], "bottom": 0},
        "grid": {"left": "3%", "right": "4%", "bottom": "10%", "containLabel": True},
        "xAxis": {"type": "category", "data": categories},
        "yAxis": {"type": "value", "name": y_label},
        "series": [],
        "color": CHART_COLORS,
    }
    for s in series_list:
        option["series"].append({
            "name": s["name"],
            "type": "bar",
            "data": s["data"],
            "barMaxWidth": 40,
            "itemStyle": {
                "borderRadius": [4, 4, 0, 0],
            },
        })
    return json.dumps(option, ensure_ascii=False)


def _build_cross_day_option(
    days: List[str],
    sessions_data: Dict[str, List[int]],
    labels: List[str],
    title: str = "跨天实验对比",
) -> str:
    series_list = []
    for label, data in sessions_data.items():
        series_list.append({"name": label, "data": data})

    option = {
        "title": {"text": title, "left": "center", "textStyle": {"fontSize": 14}},
        "tooltip": {"trigger": "axis"},
        "legend": {"data": list(sessions_data.keys()), "bottom": 0, "type": "scroll"},
        "grid": {"left": "3%", "right": "4%", "bottom": "15%", "containLabel": True},
        "xAxis": {"type": "category", "data": days},
        "yAxis": {"type": "value", "name": "事件数"},
        "series": [],
        "color": CHART_COLORS,
        "dataZoom": [
            {"type": "slider", "start": 0, "end": 100, "bottom": 40},
        ],
    }
    for s in series_list:
        option["series"].append({
            "name": s["name"],
            "type": "bar",
            "data": s["data"],
            "barGap": "20%",
            "itemStyle": {"borderRadius": [4, 4, 0, 0]},
        })
    return json.dumps(option, ensure_ascii=False)


class ChartView(QWebEngineView):
    """ECharts 图表视图"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ready = False
        self._pending_option: Optional[str] = None

        html = CHART_HTML_TEMPLATE.format(
            echarts_cdn=ECHARTS_CDN,
            style=BASE_STYLE,
        )
        self.setHtml(html)
        self.loadFinished.connect(self._on_load_finished)

    def _on_load_finished(self, ok: bool):
        if ok:
            self._ready = True
            if self._pending_option:
                self.set_option(self._pending_option)
                self._pending_option = None

    def set_option(self, option_json: str):
        if not self._ready:
            self._pending_option = option_json
            return
        escaped = option_json.replace("\\", "\\\\").replace("'", "\\'")
        script = f"renderChart('{escaped}')"
        self.page().runJavaScript(script)

    def render_time_series(
        self,
        title: str,
        x_data: List[str],
        series_list: List[Dict[str, Any]],
        y_label: str = "事件数",
    ):
        option = _build_time_series_option(title, x_data, series_list, y_label)
        self.set_option(option)

    def render_daily_bar(
        self,
        title: str,
        categories: List[str],
        series_list: List[Dict[str, Any]],
        y_label: str = "事件数",
    ):
        option = _build_daily_bar_option(title, categories, series_list, y_label)
        self.set_option(option)

    def render_cross_day(
        self,
        days: List[str],
        sessions_data: Dict[str, List[int]],
        labels: List[str],
        title: str = "跨天实验对比",
    ):
        option = _build_cross_day_option(days, sessions_data, labels, title)
        self.set_option(option)


class DataVisualizationTab(QWidget):
    """数据可视化标签页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._chart_view: Optional[ChartView] = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        control_bar = QHBoxLayout()

        control_bar.addWidget(QLabel("图表类型:"))

        self._chart_type_combo = QComboBox()
        self._chart_type_combo.addItems(["事件时间序列", "每日汇总柱状图", "跨天对比"])
        control_bar.addWidget(self._chart_type_combo)

        self._render_btn = QPushButton("刷新图表")
        control_bar.addWidget(self._render_btn)

        control_bar.addStretch()
        layout.addLayout(control_bar)

        self._chart_view = ChartView()
        layout.addWidget(self._chart_view, stretch=1)

        self._render_btn.clicked.connect(self._on_render)
        self._chart_type_combo.currentIndexChanged.connect(self._on_render)

    def _on_render(self):
        chart_type = self._chart_type_combo.currentText()
        if chart_type == "事件时间序列":
            self._chart_view.render_time_series(
                title="示例 - 事件时间序列",
                x_data=["00:00", "01:00", "02:00", "03:00", "04:00", "05:00"],
                series_list=[
                    {"name": "触发事件", "data": [5, 12, 8, 3, 15, 9]},
                    {"name": "执行事件", "data": [2, 8, 5, 1, 10, 6]},
                ],
            )
        elif chart_type == "每日汇总柱状图":
            self._chart_view.render_daily_bar(
                title="示例 - 每日事件汇总",
                categories=["周一", "周二", "周三", "周四", "周五"],
                series_list=[
                    {"name": "会话A", "data": [120, 200, 150, 80, 170]},
                    {"name": "会话B", "data": [90, 160, 130, 110, 140]},
                ],
            )
        elif chart_type == "跨天对比":
            self._chart_view.render_cross_day(
                days=["Day1", "Day2", "Day3", "Day4", "Day5"],
                sessions_data={
                    "实验组A": [45, 52, 38, 65, 48],
                    "实验组B": [35, 40, 42, 55, 50],
                    "对照组": [20, 22, 19, 25, 21],
                },
                labels=["实验组A", "实验组B", "对照组"],
            )

    def render_from_data(
        self,
        chart_type: str,
        x_data: List[str],
        series_list: List[Dict[str, Any]],
        title: str = "",
        y_label: str = "事件数",
    ):
        self._chart_type_combo.setCurrentText(chart_type)
        if chart_type == "事件时间序列":
            self._chart_view.render_time_series(title, x_data, series_list, y_label)
        elif chart_type == "每日汇总柱状图":
            self._chart_view.render_daily_bar(title, x_data, series_list, y_label)

    def render_cross_day_from_data(
        self,
        days: List[str],
        sessions_data: Dict[str, List[int]],
        title: str = "跨天实验对比",
    ):
        self._chart_type_combo.setCurrentText("跨天对比")
        self._chart_view.render_cross_day(
            days=days,
            sessions_data=sessions_data,
            labels=list(sessions_data.keys()),
            title=title,
        )
