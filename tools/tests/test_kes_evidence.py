"""Evidence must follow the active manifest, not a fixed historical count."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "xmind_filler", Path(__file__).resolve().parents[1]
            / "fill_driver_test_xmind.py")
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.tool.ROOT = root
        self.tool.MANIFEST = root / "manifest.json"
        self.tool.EVIDENCE = root
        (root / "test_one.py").write_text(
            "def test_one():\n    assert True\n", encoding="utf-8")
        self.tool.MANIFEST.write_text(json.dumps([{
            "id": "KB-CONN-001", "nodeid": "test_one.py::test_one",
            "title": "one case",
        }]), encoding="utf-8")
        self.rows = [{"nodeid": "test_one.py::test_one[mysql]",
                      "outcome": "passed"}]

    def load(self, rows):
        (self.tool.EVIDENCE / "parameterized-results.json").write_text(
            json.dumps(rows), encoding="utf-8")
        return self.tool.load_results()

    def test_accepts_current_manifest_without_historical_count(self):
        cases = self.load(self.rows)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["results"], self.rows)
        self.assertEqual(cases[0]["line"], 1)

    def test_rejects_duplicate_result_nodes(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.load(self.rows * 2)

    def test_rejects_retired_or_unknown_result_nodes(self):
        with self.assertRaisesRegex(ValueError, "unmapped"):
            self.load(self.rows + [{"nodeid": "test_old.py::test_old",
                                   "outcome": "passed"}])

    def test_rejects_missing_results(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            self.load([])

    def test_legend_does_not_rename_template_design_branch(self):
        root = {"title": "测试方案", "children": {"attached": [
            {"title": "需求分析"}, {"title": "测试环境"},
            {"title": "测试方案设计"}]}}
        self.assertTrue(hasattr(self.tool, "set_legend"))
        self.tool.set_legend(root, "当前统计")
        self.assertEqual(root["children"]["attached"][-1]["title"],
                         "测试方案设计")
        self.assertIn("当前统计", root["notes"]["plain"]["content"])

    def test_case_design_uses_template_verification_nodes_not_execution_log(self):
        case = {
            "id": "KB-CONN-001", "title": "自动识别兼容模式",
            "nodeid": "tests/test_connection.py::test_mode", "line": 12,
            "module": "CONN", "results": self.rows,
            "input": "不指定 kes_mode，分别连接三模式实例。",
            "action": "读取连接模式并执行基础查询。",
            "expected_result": "模式与实例一致，基础查询返回 1。",
        }
        node = self.tool.case_node(case, {"id": "prototype", "title": "测试点"})
        nodes = node["children"]["attached"]
        self.assertEqual(len(nodes), 2)
        self.assertTrue(nodes[0]["title"].startswith("验证"))
        self.assertEqual(nodes[1]["title"], "验证条件")
        self.assertEqual(nodes[1]["children"]["attached"][0]["title"],
                         "模式与实例一致，基础查询返回 1。")
        serialized = json.dumps(node, ensure_ascii=False)
        for unwanted in ("源码", "pytest", "参数化执行", "实测结果", "tests/"):
            self.assertNotIn(unwanted, serialized)

    def test_packages_are_named_by_python_file_and_keep_all_their_cases(self):
        cases = []
        for filename, identifier, category in (
                ("test_procedures.py", "KB-EXEC-051", "输出参数"),
                ("test_procedures.py", "KB-EXEC-052", "函数调用"),
                ("test_multiple_results.py", "KB-EXEC-049", "多语句")):
            cases.append({
                "id": identifier, "title": category, "module": "EXEC",
                "nodeid": f"tests/kes/procedures_and_results/{filename}::test_example",
                "category": category, "input": "输入", "action": "执行",
                "expected_result": "符合预期", "results": [],
            })
        self.assertTrue(hasattr(self.tool, "package_topics"))
        prototype = {"id": "prototype", "title": "用例包"}
        packages = self.tool.package_topics(cases, prototype, prototype, prototype)
        self.assertEqual([p["title"] for p in packages], [
            "需求1 - 用例包\ntest_multiple_results.py",
            "需求2 - 用例包\ntest_procedures.py"])
        self.assertIn("KB-EXEC-049", json.dumps(packages[0]))
        self.assertNotIn("KB-EXEC-051", json.dumps(packages[0]))
        self.assertIn("KB-EXEC-051", json.dumps(packages[1]))
        self.assertIn("KB-EXEC-052", json.dumps(packages[1]))


if __name__ == "__main__":
    unittest.main()
