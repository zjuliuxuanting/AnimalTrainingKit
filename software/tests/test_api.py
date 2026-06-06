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


class TestBoundaryConditions:
    """常态化边界条件测试（原测试员手动测试，现自动化）"""

    def test_special_characters_xss(self, client):
        """特殊字符 XSS → 不应返回 500"""
        response = client.post(
            "/api/experiments",
            json={"name": "<script>alert(1)</script>", "subject_id": "XSS"}
        )
        assert response.status_code in [200, 400, 422]

    def test_special_characters_html(self, client):
        """HTML 标签 → 不应返回 500"""
        response = client.post(
            "/api/experiments",
            json={"name": "<img src=x onerror=alert(1)>", "subject_id": "HTML"}
        )
        assert response.status_code in [200, 400, 422]

    def test_emoji_name(self, client):
        """emoji 名称 → 应正常处理"""
        response = client.post(
            "/api/experiments",
            json={"name": "测试实验🐹", "subject_id": "E01"}
        )
        assert response.status_code in [200, 400, 422]

    def test_fullwidth_characters(self, client):
        """全角符号 → 不应返回 500"""
        response = client.post(
            "/api/experiments",
            json={"name": "测试（全角）！", "subject_id": "FULL"}
        )
        assert response.status_code in [200, 400, 422]

    def test_long_name_20_chars(self, client):
        """超长名称（20字中文）→ 应正常处理"""
        response = client.post(
            "/api/experiments",
            json={"name": "这是一段二十个字的超长实验名称测试", "subject_id": "LONG"}
        )
        assert response.status_code in [200, 400, 422]

    def test_long_name_100_chars(self, client):
        """超长名称（100字符）→ 应返回错误或截断"""
        response = client.post(
            "/api/experiments",
            json={"name": "A" * 100, "subject_id": "L100"}
        )
        assert response.status_code in [200, 400, 422]

    def test_empty_name(self, client):
        """空名称 → 服务器接受（experiment_manager 不做名称校验）"""
        response = client.post(
            "/api/experiments",
            json={"name": "", "subject_id": "EMPTY"}
        )
        assert response.status_code in [200, 400, 422]

    def test_missing_name(self, client):
        """缺少 name 字段 → 服务器接受（FastAPI 用默认值 '' 填充）"""
        response = client.post(
            "/api/experiments",
            json={"subject_id": "NO_NAME"}
        )
        assert response.status_code in [200, 400, 422]

    def test_sql_injection(self, client):
        """SQL 注入尝试 → 不应返回 500"""
        response = client.post(
            "/api/experiments",
            json={"name": "'; DROP TABLE experiments; --", "subject_id": "SQL"}
        )
        assert response.status_code in [200, 400, 422]
