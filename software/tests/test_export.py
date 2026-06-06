"""
测试 CSV 导出功能。

所有测试使用 tmp_path fixture，不污染 data_store/。
"""

import csv
import os

import pytest


class TestExportCSV:
    def test_export_csv_format(self, tmp_path):
        """事件写入 → CSV 导出格式正确（表头与数据列对齐）"""
        from data.export import export_csv
        records = [
            {"session_id": "s1", "subject_id": "M01", "event_type": "click",
             "ts_ms": 1000, "session_name": "测试"},
            {"session_id": "s1", "subject_id": "M01", "event_type": "hold",
             "ts_ms": 2000, "session_name": "测试"},
        ]
        csv_path = str(tmp_path / "output.csv")
        export_csv(records, csv_path)
        assert os.path.exists(csv_path)

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 2
        # 验证表头是中文
        assert "实验编号" in reader.fieldnames
        assert "事件类型" in reader.fieldnames
        assert rows[0]["实验编号"] == "s1"
        assert rows[0]["事件类型"] == "click"

    def test_empty_export(self, tmp_path):
        """空事件列表 → CSV 包含表头无数据行"""
        from data.export import export_csv
        csv_path = str(tmp_path / "empty.csv")
        export_csv([], csv_path)
        assert os.path.exists(csv_path)

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 0
        # 表头仍存在
        assert "实验编号" in reader.fieldnames
        assert "事件类型" in reader.fieldnames

    def test_export_with_raw_payload(self, tmp_path):
        """包含 raw_payload 的导出"""
        from data.export import export_csv
        records = [
            {"session_id": "s1", "event_type": "click", "ts_ms": 1000,
             "session_name": "测试", "raw_payload": {"zone": "zone1", "value": 42}},
        ]
        csv_path = str(tmp_path / "with_raw.csv")
        export_csv(records, csv_path, include_raw=True)
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert "原始数据" in rows[0]

    def test_export_filename_format(self, tmp_path):
        """文件名格式 {subject_id}_{exp_name}_{date}.csv"""
        from data.export import export_session_csv
        session_id = "test-session-123"
        output_dir = str(tmp_path / "exports")
        path = export_session_csv(
            [], session_id, output_dir,
            subject_id="M01", session_name="测试实验",
        )
        filename = os.path.basename(path)
        assert filename.startswith("M01_测试实验_")
        assert filename.endswith(".csv")

    def test_export_empty_subject_id(self, tmp_path):
        """动物编号为空时使用"未命名动物"""
        from data.export import export_session_csv
        output_dir = str(tmp_path / "exports_no_subject")
        path = export_session_csv(
            [], "session-1", output_dir,
            subject_id="", session_name="空动物实验",
        )
        filename = os.path.basename(path)
        assert filename.startswith("未命名动物_空动物实验_")
        assert filename.endswith(".csv")

    def test_export_session_csv_records(self, tmp_path):
        """export_session_csv 写入数据后进行验证"""
        from data.export import export_session_csv
        records = [
            {"session_id": "s1", "event_type": "click", "ts_ms": 100,
             "session_name": "验证导出"},
            {"session_id": "s1", "event_type": "release", "ts_ms": 200,
             "session_name": "验证导出"},
        ]
        output_dir = str(tmp_path / "session_exports")
        path = export_session_csv(
            records, "s1", output_dir,
            subject_id="A01", session_name="验证导出",
        )
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["事件类型"] == "click"
        assert rows[1]["事件类型"] == "release"


class TestCSVColumnNamesChinese:
    """回归测试 R5：CSV 列名必须是中文（自动化替代手动检查）"""

    def test_all_required_columns_chinese(self, tmp_path):
        """所有必需列名都是中文"""
        from data.export import export_csv
        records = [
            {
                "session_id": "s1",
                "subject_id": "M01",
                "event_type": "click",
                "ts_ms": 1000,
                "session_name": "测试",
            }
        ]
        csv_path = str(tmp_path / "columns.csv")
        export_csv(records, csv_path)

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames

        # 关键列名必须是中文
        assert "实验编号" in fieldnames, "session_id 应翻译为 实验编号"
        assert "事件类型" in fieldnames, "event_type 应翻译为 事件类型"
        assert "时间戳" in fieldnames or "时间" in fieldnames, "ts_ms 应翻译为 时间戳"

    def test_no_english_column_names(self, tmp_path):
        """不应出现英文列名"""
        from data.export import export_csv
        records = [
            {"session_id": "s1", "event_type": "click", "ts_ms": 1000, "session_name": "测试"}
        ]
        csv_path = str(tmp_path / "no_english.csv")
        export_csv(records, csv_path)

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames

        # 不应出现的英文列名
        forbidden_english = ["session_id", "event_type", "ts_ms", "subject_id"]
        for col in forbidden_english:
            assert col not in fieldnames, f"不应出现英文列名: {col}"
