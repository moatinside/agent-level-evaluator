import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "evaluate.py"


def load_module():
    spec = importlib.util.spec_from_file_location("evaluate_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_execution_level_requires_contiguous_gates():
    module = load_module()
    scores = {
        "workflow": 60,
        "routing": 60,
        "ensemble": 60,
        "self_validate": 60,
        "agentic_search": 60,
        "self_evolution": 60,
    }
    assert module.determine_execution_level(scores) == 7
    scores["routing"] = 59
    assert module.determine_execution_level(scores) == 2


def test_report_keeps_collaboration_separate_from_execution():
    module = load_module()
    scores = {axis["id"]: 50 for axis in module.AXES}
    report = module.generate_report(scores, 1, collaboration_stage=5)
    assert "実行自律性" in report
    assert "問い・対象の拡張" in report
    assert "単一総合Level:** 断定しない" in report
    assert "## 総合レベル" not in report


def test_quick_report_marks_collaboration_unobserved():
    module = load_module()
    scores = {axis["id"]: 50 for axis in module.AXES}
    report = module.generate_report(scores, 1, collaboration_stage=0)
    assert "協働・拡張学習:** 未観測" in report
    assert "51点ゲート:** 未評価" in report
