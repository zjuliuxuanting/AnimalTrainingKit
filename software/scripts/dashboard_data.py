#!/usr/bin/env python3
"""
Dashboard 数据生成器 — 读取项目实时状态，输出 JSON

用法：
    python3 scripts/dashboard_data.py

输出：
    标准输出打印 JSON，前端 /api/dashboard/data 端点调用此脚本
"""

import json
import os
import subprocess
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

# === 路径 ===
# scripts/ 在 behavior_box/software/scripts/ 下
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOFTWARE_DIR = os.path.join(PROJECT_ROOT, "software")
TEST_DIR = os.path.join(SOFTWARE_DIR, "tests")
DOCS_DIR = os.path.join(PROJECT_ROOT, "项目")
DATA_STORE = os.path.join(SOFTWARE_DIR, "data_store")


def _git_log(lines: int = 20) -> List[Dict[str, str]]:
    """读取最近 git 提交记录"""
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={lines}", "--format=%H|%ai|%s"],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=5
        )
        commits = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({
                    "hash": parts[0][:8],
                    "date": parts[1],
                    "message": parts[2],
                })
        return commits
    except Exception:
        return []


def _git_diff_stat() -> Dict[str, Any]:
    """读取当前未提交的改动统计"""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=5
        )
        # Parse last line for total
        lines = result.stdout.strip().split("\n")
        total_changed = 0
        total_insertions = 0
        total_deletions = 0
        for line in lines:
            if not line.strip():
                continue
            parts = line.rsplit("|", 1)
            if len(parts) == 2:
                total_changed += 1
                changes = parts[1].strip()
                ins = changes.count("+")
                dels = changes.count("-")
                total_insertions += ins
                total_deletions += dels

        # Untracked files
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=5
        )
        untracked_count = len([f for f in untracked.stdout.strip().split("\n") if f])

        return {
            "changed_files": total_changed,
            "insertions": total_insertions,
            "deletions": total_deletions,
            "untracked": untracked_count,
        }
    except Exception:
        return {"changed_files": 0, "insertions": 0, "deletions": 0, "untracked": 0}


def _count_tests() -> Dict[str, Any]:
    """统计测试文件和测试函数数量（不运行测试，避免依赖问题）"""
    test_files = []
    total_functions = 0
    for f in os.listdir(TEST_DIR):
        if f.startswith("test_") and f.endswith(".py"):
            test_files.append(f)
            try:
                with open(os.path.join(TEST_DIR, f), "r", encoding="utf-8") as fh:
                    content = fh.read()
                    # Count def test_*
                    functions = re.findall(r"^\s*def test_\w+", content, re.MULTILINE)
                    total_functions += len(functions)
            except Exception:
                pass
    return {
        "test_files": len(test_files),
        "test_functions": total_functions,
    }


def _count_experiments() -> int:
    """统计已有实验数量"""
    exp_dir = os.path.join(DATA_STORE, "experiments")
    if not os.path.isdir(exp_dir):
        return 0
    try:
        return len([d for d in os.listdir(exp_dir) if os.path.isdir(os.path.join(exp_dir, d))])
    except Exception:
        return 0


def _read_doc(path: str) -> str:
    """读取文档文件内容（截取前 50 行）"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return "\n".join(f.readlines()[:50])
    except Exception:
        return ""


def _extract_blockers() -> List[Dict[str, str]]:
    """从项目文档中提取阻塞项"""
    blockers = []
    # 读取推进看板
    boards = [
        os.path.join(DOCS_DIR, "01_阶段规划", "推进看板.md"),
        os.path.join(DOCS_DIR, "01_阶段规划", "软件推进看板.md"),
        os.path.join(DOCS_DIR, "07_会议与沟通", "本次任务单.md"),
    ]
    for board in boards:
        content = _read_doc(board)
        for line in content.split("\n"):
            if "阻塞" in line or "blocker" in line.lower() or "🔴" in line:
                if line.strip():
                    blockers.append({"source": os.path.basename(board), "text": line.strip()[:120]})
    return blockers[:10]


def _read_version() -> str:
    """从 server.py 读取版本号"""
    try:
        with open(os.path.join(SOFTWARE_DIR, "server.py"), "r") as f:
            content = f.read()
            m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', content)
            if m:
                return m.group(1)
    except Exception:
        pass
    return "v1.x"


def _file_modification_stats() -> Dict[str, Any]:
    """统计 software/ 目录下各类型文件的修改次数（近 30 天）"""
    since = datetime.now().timestamp() - 30 * 86400
    try:
        result = subprocess.run(
            ["git", "log", "--since=30.days", "--name-only", "--pretty=format:"],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=5
        )
        files = {}
        for f in result.stdout.strip().split("\n"):
            f = f.strip()
            if not f:
                continue
            if f not in files:
                files[f] = 0
            files[f] += 1

        # 按目录归类
        dirs = {}
        for f, count in files.items():
            parts = f.split("/")
            if len(parts) >= 2:
                top_dir = parts[0]
                dirs[top_dir] = dirs.get(top_dir, 0) + count
        return dict(sorted(dirs.items(), key=lambda x: -x[1])[:10])
    except Exception:
        return {}


def _git_commits_last_7_days() -> int:
    """近 7 天提交次数"""
    try:
        result = subprocess.run(
            ["git", "log", "--since=7.days", "--oneline"],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=5
        )
        return len([l for l in result.stdout.strip().split("\n") if l])
    except Exception:
        return 0


def _read_today_summary() -> Dict[str, Any]:
    """读取今日总结数据"""
    summary_path = os.path.join(DATA_STORE, "dashboard_today_summary.json")
    default = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "last_updated": "—",
        "summary": "今日暂无记录",
        "updates": [],
        "most_recent_activity": "—",
    }
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 如果日期不是今天，重置
            if data.get("date") != datetime.now().strftime("%Y-%m-%d"):
                data = default
                data["date"] = datetime.now().strftime("%Y-%m-%d")
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def generate() -> Dict[str, Any]:
    """生成完整的仪表盘数据"""
    now = datetime.now(timezone.utc).astimezone()
    test_stats = _count_tests()
    diff = _git_diff_stat()

    return {
        "meta": {
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": now.strftime("%z"),
        },
        "version": _read_version(),
        "gates": {
            "G1": {"label": "模拟信号→CSV", "status": "done", "progress": 100},
            "G1.5": {"label": "实验管理页面", "status": "done", "progress": 100},
            "G2": {"label": "摄像头事件→CSV", "status": "done", "progress": 100},
            "G3": {"label": "流程编辑器(13节点)", "status": "active", "progress": 90},
            "G4": {"label": "数据图表功能", "status": "pending", "progress": 0},
        },
        "tests": {
            "total_files": test_stats["test_files"],
            "total_functions": test_stats["test_functions"],
            "experiments": _count_experiments(),
            "commits_7d": _git_commits_last_7_days(),
        },
        "git": diff,
        "recent_commits": _git_log(10),
        "blockers": _extract_blockers(),
        "file_changes": _file_modification_stats(),
        "today_summary": _read_today_summary(),
    }


def main():
    data = generate()
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
