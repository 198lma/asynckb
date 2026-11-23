"""Fill the supplied driver XMind template with concise test designs."""

from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import re
import uuid
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT.parent
TEMPLATE_XMIND = DOWNLOADS / "产出物文档_模板/测试/驱动测试方案.xmind"
MANIFEST = ROOT / "tests/kes/case_manifest.json"
EVIDENCE = ROOT / "docs/_static/kes-testing/regression-20261119"
OUTPUT = ROOT / "docs/kes-testing/asynckb驱动测试方案.xmind"
WORD_PLAN = ROOT / "docs/kes-testing/asynckb驱动测试方案.docx"

MODULES = {
    "CONN": ("功能模块1 连接与兼容模式", "tests/kes/connection_initialization/"),
    "PROTO": ("功能模块2 协议自解析与异步调度", "tests/kes/protocol_and_async/"),
    "TYPE": ("功能模块3 数据类型、OID 与 Codec", "tests/kes/types_and_codecs/"),
    "EXEC": ("功能模块4 查询执行、事务与语句资源", "tests/kes/execution_transactions_statements/"),
    "POOL": ("功能模块5 连接池", "tests/kes/pool/"),
    "SA": ("功能模块6 SQLAlchemy 异步方言", "tests/kes/sqlalchemy_dialect/"),
    "AUTH": ("功能模块7 用户认证与 MAC 信息上传", "tests/kes/authentication/"),
}
MODULE_TITLES = {code: title.replace(" ", "\n", 1)
                 for code, (title, _) in MODULES.items()}
INTERFACES = {
    "CONN": ("asynckb", ["connect()、create_pool()、get_kes_mode()"]),
    "PROTO": ("Connection", ["execute()、fetch()、fetchrow()、fetchval()",
                             "copy_*()、add_listener()、remove_listener()"]),
    "TYPE": ("Connection / PreparedStatement", [
        "set_type_codec()、reset_type_codec()、reload_schema_state()",
        "get_parameters()、get_attributes()"]),
    "EXEC": ("Connection / PreparedStatement / Transaction", [
        "execute()、fetch()、fetchrow()、fetchval()、fetchmany()、executemany()",
        "prepare()、close()、cursor()", "transaction()、is_in_transaction()"]),
    "POOL": ("Pool", ["acquire()、release()、close()、expire_connections()",
                       "init / setup / reset 回调"]),
    "SA": ("SQLAlchemy AsyncEngine / AsyncConnection", [
        "kingbase+asynckb://", "connect()、execute()、begin()、run_sync()"]),
    "AUTH": ("asynckb", ["connect()、create_pool()", "密码、证书、外部身份及 MAC 上传"]),
}


def load_results():
    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = json.loads((EVIDENCE / "parameterized-results.json").read_text(encoding="utf-8"))
    results = {row["nodeid"]: row for row in rows}
    if len(results) != len(rows):
        raise ValueError("duplicate result node IDs")
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("duplicate test point IDs")
    mapped = set()
    for case in cases:
        path, function = case["nodeid"].split("::")
        lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
        case["line"] = next(i for i, line in enumerate(lines, 1)
                            if line.startswith("def " + function + "(")
                            or line.startswith("async def " + function + "("))
        case["module"] = case["id"].split("-")[1]
        case["results"] = [row for nodeid, row in results.items()
                           if nodeid == case["nodeid"]
                           or nodeid.startswith(case["nodeid"] + "[")]
        if not case["results"]:
            raise ValueError(f"missing result nodes for {case['id']}")
        mapped.update(row["nodeid"] for row in case["results"])
    if mapped != set(results):
        raise ValueError(f"unmapped result nodes: {sorted(set(results) - mapped)}")
    if any(row["outcome"] not in {"passed", "xfailed", "skipped", "failed", "error"}
           for row in rows):
        raise ValueError("unknown result outcome")
    return cases


def new_id():
    return str(uuid.uuid4())


def find_topic(topic, title):
    if topic.get("title") == title:
        return topic
    for child in topic.get("children", {}).get("attached", []):
        result = find_topic(child, title)
        if result is not None:
            return result
    return None


def children(topic):
    return topic.setdefault("children", {}).setdefault("attached", [])


def replace_children(topic, values):
    topic["children"] = {"attached": values}
    topic.pop("branch", None)


def clone_topic(prototype, title, nested=None, notes=None):
    result = deepcopy(prototype)
    result["id"] = new_id()
    result["title"] = title
    for field in ("children", "branch", "summaries", "notes", "position"):
        result.pop(field, None)
    if nested:
        result["children"] = {"attached": nested}
    if notes:
        result["notes"] = {"plain": {"content": notes}}
    return result


def set_legend(root, text):
    root["notes"] = {"plain": {"content": text}}


def node_outcome(case):
    counts = Counter(row["outcome"] for row in case["results"])
    names = (("passed", "通过"), ("xfailed", "已知限制预期失败"),
             ("skipped", "跳过"), ("failed", "非预期失败"), ("error", "错误"))
    return "；".join(f"{label} {counts[key]}" for key, label in names if counts[key]) + \
        f"；执行 {len(case['results'])} 项"


def module_summary(cases, code):
    group = [case for case in cases if case["module"] == code]
    counts = Counter(row["outcome"] for case in group for row in case["results"])
    text = f"{MODULES[code][0]}：{len(group)} 个测试点，{sum(counts.values())} 个执行节点；通过 {counts['passed']}"
    if counts["xfailed"]:
        text += f"；预期失败 {counts['xfailed']}（不计功能通过）"
    return text + "。"


def load_designs(cases):
    """Reuse the reviewed Chinese inputs/expectations, not Python assertions."""
    from docx import Document

    designs = {}
    current = None
    category = None
    for paragraph in Document(WORD_PLAN).paragraphs:
        text = paragraph.text
        if paragraph.style.name == "Heading 3" and text.startswith("8."):
            category = re.sub(r"^8\.\d+\.\d+\s+", "", text)
        if paragraph.style.name.startswith("Heading"):
            match = re.match(r"KB-[A-Z]+-\d{3}", text)
            current = match.group() if match else None
            if current:
                designs[current] = {"category": category}
        if current:
            for prefix, key in (("配置值／输入：", "input"), ("触发：", "action"),
                                ("预期结果：", "expected_result")):
                if text.startswith(prefix):
                    designs[current][key] = text[len(prefix):]
    for case in cases:
        design = designs.get(case["id"], {})
        if any(not design.get(key) for key in ("category", "input", "action", "expected_result")):
            raise ValueError(f"missing test design for {case['id']}")
        case.update(design)


def case_node(case, prototype):
    return clone_topic(prototype, f"功能测试点 {case['id']}\n{case['title']}", nested=[
        clone_topic(prototype, f"验证内容\n{case['input']}\n{case['action']}"),
        clone_topic(prototype, "验证条件", nested=[
            clone_topic(prototype, case["expected_result"]),
        ]),
    ])


def group_cases(cases):
    groups = defaultdict(list)
    for case in cases:
        groups[case["category"]].append(case)
    return groups


def group_files(cases):
    groups = defaultdict(list)
    for case in cases:
        groups[case["nodeid"].split("::", 1)[0]].append(case)
    return dict(sorted(groups.items()))


def package_topics(cases, requirement, point, leaf):
    packages = []
    for index, (path, file_cases) in enumerate(group_files(cases).items(), 1):
        categories = []
        if file_cases[0]["module"] == "TYPE":
            by_mode = defaultdict(list)
            for case in file_cases:
                modes = {mode for row in case["results"]
                         for mode in ("mysql", "oracle", "sqlserver")
                         if f"[{mode}" in row["nodeid"]}
                mode = next(iter(modes)) if len(modes) == 1 else "common"
                by_mode[mode].append(case)
            for mode, name in (("oracle", "Oracle"), ("mysql", "MySQL"),
                               ("sqlserver", "SQLServer"), ("common", "三模式共同类型")):
                if by_mode[mode]:
                    categories.append(clone_topic(leaf, name, nested=[
                        clone_topic(leaf, category, nested=[case_node(case, point) for case in group])
                        for category, group in group_cases(by_mode[mode]).items()]))
        else:
            categories = [clone_topic(leaf, category, nested=[case_node(case, point) for case in group])
                          for category, group in group_cases(file_cases).items()]
        packages.append(clone_topic(requirement,
            f"需求{index} - 用例包\n{Path(path).name}", nested=[
                clone_topic(leaf, "正常功能验证", nested=categories)]))
    return packages


def build(cases):
    load_designs(cases)
    with ZipFile(TEMPLATE_XMIND) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
        sheets = json.loads(archive.read("content.json"))
    sheet = sheets[0]
    root = sheet["rootTopic"]
    root["title"] = "asynckb 驱动测试方案"
    module = find_topic(root, "功能模块1\n连接与兼容模式")
    requirement = find_topic(root, "需求1\n驱动及数据库模式选择")
    point = find_topic(root, "功能测试点1\n连接指定数据库模式")
    leaf = find_topic(root, "验证条件")
    scenario = find_topic(root, "测试场景1")
    package = find_topic(root, "用例包1")
    assert all((module, requirement, point, leaf, scenario, package))

    def topic(title, nested=None, prototype=leaf):
        return clone_topic(prototype, title, nested=nested)

    requirements, mappings, focuses, designs = [], [], [], []
    for code in MODULES:
        module_cases = [case for case in cases if case["module"] == code]
        grouped = group_cases(module_cases)
        requirements.append(topic(MODULE_TITLES[code], [
            topic(f"需求{index}\n{category}", prototype=requirement)
            for index, category in enumerate(grouped, 1)], module))
        mappings.append(topic(MODULE_TITLES[code], [
            topic(f"需求{index}\n{category}", [
                topic("测试场景\n" + category, [
                    topic("用例包\n" + Path(path).name, prototype=package)
                    for path in group_files(group)
                ], scenario)
            ], requirement) for index, (category, group) in enumerate(grouped.items(), 1)
        ], module))
        classname, methods = INTERFACES[code]
        focuses.append(topic(MODULE_TITLES[code], [
            topic(classname, [topic(method) for method in methods])
        ], module))
        groups = package_topics(module_cases, requirement, point, leaf)
        designs.append(topic(MODULE_TITLES[code], groups, module))

    replace_children(find_topic(root, "需求分解表"), requirements)
    replace_children(find_topic(root, "需求列表和用例对应"), mappings)
    replace_children(find_topic(root, "功能测试"), designs)
    focus = find_topic(root, "测试重点分析")
    replace_children(focus, [topic("通过 asynckb 驱动接口完成以上场景", [
        topic("测试接口", focuses)
    ])])
    replace_children(find_topic(root, "原始需求"), [topic(
        "一套代码兼容 KES Oracle、MySQL、SQLServer，提供异步驱动及 SQLAlchemy 方言。")])
    replace_children(find_topic(root, "关联功能分析"), [topic(
        "查询执行、事务和方言共用类型及协议适配；过程和多结果集场景归入查询执行模块。")])
    replace_children(find_topic(root, "驱动限制"), [
        topic("Python >=3.9；独立包名及导入名为 asynckb"),
        topic("不提供 nextset()；OUT 与多组查询同时返回为已知限制"),
        topic("PAM、BSD 及国密不列为本轮已验证能力"),
    ])
    replace_children(find_topic(root, "其他限制"), [topic(
        "不外推至未测试平台、补丁版本、主备切换及生产容量；短时压力不替代长期稳定性测试。")])
    replace_children(find_topic(root, "功能测试环境"), [
        topic("Linux", [topic("x86_64", [topic("CPython 3.10.12；asynckb 0.31.0.post12"),
            topic("MySQL：V009R003C018；127.0.0.1:54321；test"),
            topic("Oracle：V009R002C016；127.0.0.1:54322；test"),
            topic("SQLServer：V009R004C019；127.0.0.1:54323；test")])])
    ])
    replace_children(find_topic(root, "非功能测试环境"), [
        topic("同功能测试环境；本机 TCP、无 TLS；池上限 8，最多 32 个任务")
    ])
    perf = []
    for index, (name, inputs, expected) in enumerate((
        ("单连接查询，关闭缓存", "statement_cache_size=0，持续 10 秒。", "查询返回值正确，执行错误为 0；记录吞吐和分位时延。"),
        ("单连接查询，开启缓存", "statement_cache_size=100，预热 100 次，持续 10 秒。", "查询返回值正确，执行错误为 0；记录吞吐和分位时延。"),
        ("连接池单任务查询", "池上限 8，1 个任务，持续 10 秒。", "查询成功，连接正确归还；记录吞吐和分位时延。"),
        ("连接池等容量并发", "池上限 8，8 个任务，持续 10 秒。", "并发查询返回正确，无执行错误，连接归还。"),
        ("连接池超容量并发", "池上限 8，32 个任务，持续 10 秒。", "查询等待空闲连接后正常完成，池容量不超限，超时后可恢复。"),
        ("持续并发查询", "池上限 8，32 个任务，持续 120 秒。", "执行错误为 0，负载后连接可复用；关闭后无测试会话及测试表残留。"),
        ("并发事务提交与回滚", "池上限 8，32 个任务，持续 10 秒，混合提交与回滚。", "数据库行数等于成功提交数，回滚数据不落表，连接池及测试对象正确清理。"),
    ), 1):
        perf.append(topic(f"功能测试点 PERF-{index:03d}\n{name}", [
            topic("验证内容\n三模式分别执行；" + inputs),
            topic("验证条件", [topic(expected)])
        ], point))
    design_branch = find_topic(root, "测试方案设计")
    children(design_branch).append(topic("非功能测试", [
        topic("性能与短时压力", [topic("用例包\nrun_kes_performance.py", [
            topic("正常功能验证", perf)])])
    ]))
    sheet["title"] = root["title"]
    sheet["revisionId"] = new_id()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUTPUT, "w") as output:
        for info, data in entries:
            if info.filename == "content.json":
                data = json.dumps(sheets, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            output.writestr(info, data)
    print(OUTPUT)


def main():
    build(load_results())


if __name__ == "__main__":
    main()
