"""Validate test-plan IDs and keep the browsable source index current."""

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
INDEX = Path("docs/kes-testing/TEST_CASE_INDEX.md")
MODULES = (
    ("CONN", "连接初始化"), ("PROTO", "协议与异步调度"),
    ("TYPE", "类型 OID 与 Codec"), ("EXEC", "查询执行、事务与语句资源"),
    ("POOL", "连接池"), ("SA", "SQLAlchemy 方言"), ("AUTH", "用户认证"),
)


def collect_sources(root):
    sources = {}
    for path in sorted((root / "tests/kes").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            ids = []
            for decorator in node.decorator_list:
                if not (isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr == "case_id"):
                    continue
                try:
                    ids.append(ast.literal_eval(decorator.args[0])
                               if len(decorator.args) == 1 else None)
                except (ValueError, TypeError):
                    ids.append(None)
            target = f"{path.relative_to(root).as_posix()}::{node.name}"
            if target in sources:
                raise ValueError(f"duplicate test target: {target}")
            sources[target] = (ids, node.lineno)
    return sources


def validate(cases, sources):
    errors = []
    for field in ("id", "nodeid"):
        for value, count in Counter(case[field] for case in cases).items():
            if count != 1:
                errors.append(f"duplicate {field}: {value}")
    targets = {case["nodeid"] for case in cases}
    for target in sorted(sources.keys() - targets):
        errors.append(f"test missing from manifest: {target}")
    for case in cases:
        case_id, target = case["id"], case["nodeid"]
        if not re.fullmatch(
                r"KB-(CONN|PROTO|TYPE|EXEC|POOL|SA|AUTH)-\d{3}", case_id):
            errors.append(f"invalid case_id: {case_id}")
        if target not in sources:
            errors.append(f"source missing: {case_id}: {target}")
        elif sources[target][0] != [case_id]:
            errors.append(f"case_id mismatch: {case_id}: {target}")
    return errors


def render_index(cases, sources):
    lines = [
        "# 测试方案与代码索引", "",
        "编号沿用测试方案和 XMind。一个编号对应一个测试函数；参数化执行共用编号，",
        "模式、缓存大小等组合由 pytest 节点的 `[参数]` 后缀区分。", "",
        "通过 `pytest tests/kes -k KB-EXEC-049 -v` 按编号执行；",
        "JUnit 报告中的 `case_id`、`case_title`、`case_source` 用于追溯。", "",
        "本索引由 `python3 tools/check_test_traceability.py --write-index` 生成，",
        "新增测试时须同时更新方案、XMind、代码标记及 `tests/kes/case_manifest.json`。", "",
    ]
    for code, name in MODULES:
        group = sorted((c for c in cases if c["id"].startswith(f"KB-{code}-")),
                       key=lambda c: c["id"])
        lines.extend([f"## {name}（{len(group)} 个测试点）", "",
                      "| 编号 | 测试点 | 代码位置 |", "| --- | --- | --- |"])
        for case in group:
            target = case["nodeid"]
            path, function = target.split("::")
            line = sources[target][1]
            title = case["title"].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {case['id']} | {title} | "
                         f"[{function}](../../{path}#L{line}) |")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--write-index", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest_path = root / "tests/kes/case_manifest.json"
    cases = json.loads(manifest_path.read_text(
        encoding="utf-8"))
    sources = collect_sources(root)
    errors = validate(cases, sources)
    if not errors:
        expected = render_index(cases, sources)
        index = root / INDEX
        if args.write_index:
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text(expected, encoding="utf-8")
        elif (not index.exists()
              or index.read_text(encoding="utf-8") != expected):
            errors.append("index is stale; run with --write-index")
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"OK: {len(cases)} test-plan IDs match code and source index")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
