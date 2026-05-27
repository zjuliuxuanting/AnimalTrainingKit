"""
测试 experiment_manager CRUD 操作。

所有测试使用 tmp_path fixture，不污染 data_store/。
"""

import pytest


@pytest.fixture
def exp_root(tmp_path):
    """使用临时目录作为实验根目录，跑完自动清理。"""
    from data.experiment_manager import set_experiments_root, EXPERIMENTS_ROOT
    old_root = EXPERIMENTS_ROOT
    root = str(tmp_path / "experiments")
    set_experiments_root(root)
    yield root
    # 恢复原始根目录
    if old_root is not None:
        set_experiments_root(old_root)


class TestExperimentCRUD:
    def test_create_and_list(self, exp_root):
        """创建实验 → 列表包含该实验"""
        from data.experiment_manager import create_experiment, list_experiments
        exp_id = create_experiment(name="测试实验", subject_id="M01")
        exps = list_experiments()
        names = [e["name"] for e in exps]
        assert "测试实验" in names

    def test_delete_removes_from_list(self, exp_root):
        """删除实验 → 列表不再包含"""
        from data.experiment_manager import create_experiment, list_experiments, delete_experiment
        exp_id = create_experiment(name="待删除实验")
        assert len(list_experiments()) == 1
        ok = delete_experiment(exp_id)
        assert ok
        assert len(list_experiments()) == 0

    def test_duplicate_name_raises(self, exp_root):
        """创建同名实验 → 抛出 ValueError"""
        from data.experiment_manager import create_experiment
        create_experiment(name="同名实验")
        with pytest.raises(ValueError, match="同名实验"):
            create_experiment(name="同名实验")

    def test_create_experiment_with_custom_save_path(self, exp_root, tmp_path):
        """使用自定义 save_path 创建实验 → 实验保存在指定路径"""
        from data.experiment_manager import create_experiment, list_experiments
        custom_path = str(tmp_path / "custom_save")
        exp_id = create_experiment(name="自定义路径实验", save_path=custom_path)
        exps = list_experiments()
        ids = [e["id"] for e in exps]
        assert exp_id in ids

    def test_get_experiment(self, exp_root):
        """按 ID 获取实验 → 返回正确实验"""
        from data.experiment_manager import create_experiment, get_experiment
        exp_id = create_experiment(name="获取测试", subject_id="M02")
        exp = get_experiment(exp_id)
        assert exp is not None
        assert exp["name"] == "获取测试"
        assert exp["subject_id"] == "M02"

    def test_get_nonexistent_experiment(self, exp_root):
        """获取不存在的实验 → 返回 None"""
        from data.experiment_manager import get_experiment
        exp = get_experiment("nonexistent_id")
        assert exp is None

    def test_update_experiment(self, exp_root):
        """更新实验字段 → 更新后的值正确"""
        from data.experiment_manager import create_experiment, get_experiment, update_experiment
        exp_id = create_experiment(name="更新测试", notes="原始备注")
        ok = update_experiment(exp_id, {"notes": "更新后的备注"})
        assert ok
        exp = get_experiment(exp_id)
        assert exp["notes"] == "更新后的备注"

    def test_batch_delete(self, exp_root):
        """批量删除 → 删除计数正确"""
        from data.experiment_manager import create_experiment, list_experiments, batch_delete_experiments
        ids = []
        for i in range(3):
            ids.append(create_experiment(name=f"批量删除{i}"))
        assert len(list_experiments()) == 3
        deleted = batch_delete_experiments(ids[:2])
        assert deleted == 2
        assert len(list_experiments()) == 1


class TestIndexRebuild:
    def test_index_rebuild_preserves_data(self, exp_root):
        """索引重建 → 数据不丢失"""
        from data.experiment_manager import (
            create_experiment, list_experiments, _write_index
        )
        exp_id = create_experiment(name="索引测试")
        assert len(list_experiments()) == 1

        # 模拟索引损坏
        _write_index({})

        # list_experiments 应通过扫描目录找到实验
        exps = list_experiments()
        assert len(exps) == 1
        assert exps[0]["name"] == "索引测试"
