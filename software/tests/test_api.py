"""
测试 server.py API 关键端点。

start-mock 只测 HTTP 200，不验证 WebSocket 或数据库写入。
所有测试使用 tmp_path fixture 隔离数据。
"""

import os
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """创建 TestClient，使用 tmp_path 隔离数据目录。"""
    import server as srv

    # 保存原始 PROJECT_ROOT 以便恢复
    original_root = srv.PROJECT_ROOT

    # 覆写 PROJECT_ROOT 为临时目录
    srv.PROJECT_ROOT = str(tmp_path)

    # 创建所需目录结构
    os.makedirs(str(tmp_path / "data_store" / "experiments"), exist_ok=True)
    os.makedirs(str(tmp_path / "web"), exist_ok=True)

    # 创建最小 index.html 用于首页测试
    with open(str(tmp_path / "web" / "index.html"), "w", encoding="utf-8") as f:
        f.write("<html><body><h1>行为学训练盒 Behavior Box</h1></body></html>")

    with TestClient(srv.app) as c:
        yield c

    # 清理全局状态
    srv.db = None
    srv.event_store = None
    srv._experiment_active = False
    srv.bus = None
    srv.engine = None
    srv.session = None
    srv.PROJECT_ROOT = original_root


class TestAPI:
    def test_index(self, client):
        """GET / → 200 + HTML 含 Behavior Box"""
        response = client.get("/")
        assert response.status_code == 200
        # 测试页面包含中文标题
        assert "行为学训练盒" in response.text

    def test_experiments_list(self, client):
        """GET /api/experiments → 200 + JSON 含 experiments 字段"""
        response = client.get("/api/experiments")
        assert response.status_code == 200
        data = response.json()
        assert "experiments" in data

    def test_start_mock_default(self, client):
        """POST /api/experiment/start-mock 默认参数 → 200"""
        response = client.post(
            "/api/experiment/start-mock",
            json={"count": 1},
        )
        # 注意：我们只验证 HTTP 200，不验证业务逻辑
        assert response.status_code == 200
        # 停止实验
        client.post("/api/experiment/stop")

    def test_start_mock_empty_body(self, client):
        """POST /api/experiment/start-mock 空 body → 200"""
        response = client.post(
            "/api/experiment/start-mock",
            json={},
        )
        assert response.status_code == 200
        client.post("/api/experiment/stop")

    def test_start_mock_count_zero(self, client):
        """POST /api/experiment/start-mock count=0 → 200（边界情况）"""
        response = client.post(
            "/api/experiment/start-mock",
            json={"count": 0, "max_duration_min": 1},
        )
        assert response.status_code == 200
        client.post("/api/experiment/stop")

    def test_api_status(self, client):
        """GET /api/status → 200 + JSON 含 status 字段"""
        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_create_experiment_api(self, client):
        """POST /api/experiments → 200 + 创建成功"""
        response = client.post(
            "/api/experiments",
            json={"name": "API测试实验", "subject_id": "T01"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data

    def test_experiment_stop(self, client):
        """POST /api/experiment/stop → 200"""
        response = client.post("/api/experiment/stop")
        assert response.status_code == 200
