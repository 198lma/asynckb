"""Synchronize existing Word templates and XMind with current test evidence.

Requires python-docx. Does not recreate the supplied Word documents or styles.
"""

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

from docx import Document
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from tools import fill_driver_test_xmind as xmind


ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT.parent
DOCS = ROOT / "docs/kes-testing"
EVIDENCE = xmind.EVIDENCE
POINT_ID = re.compile(r"KB-(?:CONN|PROTO|TYPE|EXEC|POOL|SA|AUTH)-\d{3}")


def set_text(paragraph, text):
    if paragraph.text == text:
        return
    # Paragraph.runs excludes runs inside hyperlinks, including TOC entries.
    runs = [Run(element, paragraph) for element in paragraph._p.xpath('.//w:r')]
    if runs:
        runs[0].text = text
        for run in runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)


def prune_points(doc, retired):
    dropping = False
    for paragraph in list(doc.paragraphs):
        match = POINT_ID.match(paragraph.text)
        if paragraph.style.name.startswith("Heading"):
            dropping = bool(match and match.group() in retired)
        if dropping:
            paragraph._p.getparent().remove(paragraph._p)
    # Remove empty functional categories, retaining all higher-level sections.
    paragraphs = list(doc.paragraphs)
    for index, paragraph in enumerate(paragraphs):
        if paragraph.style.name != "Heading 3":
            continue
        if not paragraph.text.startswith("8."):
            continue
        group = []
        for following in paragraphs[index + 1:]:
            if following.style.name in {"Heading 1", "Heading 2", "Heading 3"}:
                break
            group.append(following)
        if not any(POINT_ID.match(p.text) for p in group):
            paragraph._p.getparent().remove(paragraph._p)


def insert_before(anchor, prototype, text):
    element = deepcopy(prototype._p)
    anchor._p.addprevious(element)
    paragraph = Paragraph(element, anchor._parent)
    set_text(paragraph, text)
    return paragraph


def merge_evidence():
    rows = []
    combined = ET.Element("testsuites")
    for filename in ("full-suite-results.xml", "isolated-suite-results.xml"):
        report = ET.parse(EVIDENCE / filename).getroot()
        for suite in report.findall("testsuite"):
            combined.append(deepcopy(suite))
        for case in report.iter("testcase"):
            properties = {p.get("name"): p.get("value")
                          for p in case.findall("properties/property")}
            source = properties["case_source"]
            nodeid = source.rsplit("::", 1)[0] + "::" + case.get("name")
            outcome, detail = "passed", ""
            for tag in ("error", "failure", "skipped"):
                element = case.find(tag)
                if element is not None:
                    outcome = {"error": "error", "failure": "failed",
                               "skipped": "skipped"}[tag]
                    if tag == "skipped" and element.get("type") == "pytest.xfail":
                        outcome = "xfailed"
                    detail = element.get("message", "")
                    break
            rows.append({"nodeid": nodeid, "case_id": properties["case_id"],
                         "outcome": outcome, "detail": detail,
                         "seconds": float(case.get("time", "0"))})
    rows.sort(key=lambda row: row["nodeid"])
    if len({row["nodeid"] for row in rows}) != len(rows):
        raise ValueError("overlapping regression batches")
    if Counter(row["outcome"] for row in rows) != {"passed": 663, "xfailed": 6}:
        raise ValueError("unexpected current regression result; inspect raw reports")
    (EVIDENCE / "parameterized-results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ET.ElementTree(combined).write(EVIDENCE / "combined-results.xml",
                                   encoding="utf-8", xml_declaration=True)
    cases = xmind.load_results()
    digest = hashlib.sha256()
    for path in sorted((ROOT / "tests/kes").rglob("*.py")):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    summary = {"date": "2026-11-19", "points": len(cases), "nodes": len(rows),
               "outcomes": dict(Counter(row["outcome"] for row in rows)),
               "source_sha256": digest.hexdigest(),
               "hash_scope": "sorted tests/kes/**/*.py: relative path + NUL + file bytes",
               "modules": {code: {
                   "points": sum(case["module"] == code for case in cases),
                   "nodes": sum(len(case["results"]) for case in cases
                                if case["module"] == code),
                   "outcomes": dict(Counter(row["outcome"] for case in cases
                                            if case["module"] == code
                                            for row in case["results"]))}
                   for code in xmind.MODULES}}
    for filename, data in (("summary.json", summary), ("test-cases.json", cases)):
        (EVIDENCE / filename).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cases, summary


def performance_paragraphs():
    return [
        ("heading", "6.8 性能与短时压力测试（非功能测试）"),
        ("body", "作用：在同一本机三模式环境记录吞吐、P50/P95/P99、错误数和客户端资源，"
         "并核对并发事务、连接池恢复及清理结果。七个功能模块不变；本节另计 7 个场景、21 组执行。"),
        ("body", "配置值／输入：每模式最多 8 个池连接、32 个并发任务，三模式顺序执行。"
         "常规场景每组 10 秒，持续场景每组 120 秒；本机 TCP、未开启 TLS，闭环负载。"
         "缓存查询路径预热 100 次。"),
        ("body", "PERF-001：单连接 statement_cache_size=0，执行参数化标量查询。"),
        ("body", "PERF-002：单连接 statement_cache_size=100，执行相同参数化标量查询。"),
        ("body", "PERF-003：8 个池连接、1 个任务，获取连接后执行查询并归还。"),
        ("body", "PERF-004：8 个池连接、8 个任务，执行并发查询。"),
        ("body", "PERF-005：8 个池连接、32 个任务，验证超出池容量时的等待与查询。"),
        ("body", "PERF-006：8 个池连接、32 个任务，持续查询 120 秒。"),
        ("body", "PERF-007：8 个池连接、32 个任务，混合事务提交与回滚；"
         "核对数据库最终行数等于成功提交次数，回滚数据不落表。"),
        ("body", "核心验证逻辑：逐次检查返回值，记录成功操作时延和失败次数；"
         "池占满后触发 acquire 超时，再确认连接可获取。结束时关闭池并核对会话与测试表清理。"
         "查询与事务使用不同统计单位，不把事务数当作 SQL 条数。"),
        ("body", "预期结果：执行错误为 0；事务行数、池空闲数、恢复和清理断言全部通过。"
         "吞吐和分位时延作为当前环境基线记录，未约定绝对性能门槛，不能据此推定生产容量。"),
        ("body", "实测结果：2026-11-19 三模式共 21 组完成，1,901,403 次操作、0 错误。"
         "120 秒持续查询：MySQL 3790.25 次/秒、P95 24.66 ms；"
         "Oracle 3824.68 次/秒、P95 24.97 ms；SQL Server 3870.61 次/秒、P95 24.27 ms。"
         "事务行数、池恢复及清理核对通过。"),
        ("body", "限制：短时负载不替代 24 小时长稳、独占性能环境或生产容量测试；"
         "客户端 RSS 有增长，不能据此声称无内存泄漏。未与原版 asyncpg 做性能对比。"),
        ("body", "源码追溯：tools/run_kes_performance.py；实测明细："
         "docs/kes-testing/PERFORMANCE_RESULTS.md；原始数据："
         "docs/_static/kes-testing/performance/results-20261119.json。"),
        ("code", "ASYNCKB_KES_PASSWORD='<测试密码>' python3 tools/run_kes_performance.py "
         "--output docs/_static/kes-testing/performance/results-rerun.json"),
    ]


def sync_plan(cases, summary):
    source = DOWNLOADS / "asyncpg测试方案.docx"
    doc = Document(source)
    retired = {row["id"] for row in json.loads(
        (DOCS / "CASE_REDUCTION.json").read_text())["retired"]}
    prune_points(doc, retired)
    case_map = {case["id"]: case for case in cases}
    current = None
    for p in doc.paragraphs:
        match = POINT_ID.match(p.text)
        if p.style.name.startswith("Heading"):
            current = case_map.get(match.group()) if match else None
        if current and p.text.startswith("实测结果："):
            set_text(p, "实测结果：" + xmind.node_outcome(current) + "。")
        if current and p.text.startswith("源码追溯："):
            path, function = current["nodeid"].split("::")
            set_text(p, f"源码追溯：{path}:{current['line']}::{function}")
        text = p.text.replace("SQLAlchemy 异步方言与 Alembic", "SQLAlchemy 异步方言")
        if p.style.name == "Normal":
            for number in ("6.6", "8.6", "9.3"):
                if text.startswith(number + " SQLAlchemy"):
                    text = number + " SQLAlchemy 异步方言"
        text = text.replace("SQLAlchemy／Alembic online", "SQLAlchemy 异步方言")
        text = text.replace("SQLAlchemy／Alembic", "SQLAlchemy 异步方言")
        text = text.replace("SQLAlchemy 2.x／Alembic online 集成", "SQLAlchemy 2.x 异步接入")
        text = text.replace("SQLAlchemy／Alembic", "SQLAlchemy")
        text = text.replace("2026-11-12 当前源码和实测报告", "2026-11-19 精简后的源码和实测报告")
        text = text.replace("848", "669").replace("231 个", "160 个")
        text = text.replace("788 通过", "615 通过").replace("54 通过", "48 通过")
        text = text.replace("842 通过", "663 通过")
        text = text.replace("asynckb-regression-20261112-174654",
                            "docs/_static/kes-testing/regression-20261119")
        if "test_password_file.py" in text:
            text = text.replace("  tests/kes/authentication/test_password_file.py \\\n", "")
        overrides = {
            "测试场景：覆盖错误密码": "测试场景：覆盖错误密码、错误用户、错误数据库、同步／异步密码回调及失败后的正确登录。不再单列多主机回退分支。",
            "测试场景：覆盖 URL 参数": "测试场景：覆盖统一 URL 参数归一化和三模式建连；证书认证另由隔离 cert 用例验证。TLS 回退和证书吊销不列为本轮验证。",
            "预期结果：参数类型和值": "预期结果：URL 参数类型和值符合测试断言，三模式均可建连并完成查询。不得由此推定未测 TLS 配置均可用。",
            "测试场景：覆盖 init/setup": "测试场景：保留 init／setup 部分失败、reset 失败及归还取消后的资源清理；一般回调顺序和错误连接类不再单列。",
            "预期结果：回调顺序精确": "预期结果：失败连接关闭或丢弃；按保留用例断言验证下一次获取和连接状态。",
            "测试场景：覆盖事务内 Cursor": "测试场景：覆盖事务内 Cursor、异步迭代、手动 fetch，以及 Connection／PreparedStatement／Pool 的 fetchmany。SQLAlchemy stream_scalars 不再单列。",
            "验证 kingbase+asynckb 唯一入口": "验证 kingbase+asynckb 统一入口按连接模式切换方言，覆盖 CRUD、DDL、RETURNING、目录反射、事务、缓存及 pre-ping。Alembic 迁移与流式读取不再单列为本轮测试点。",
            "验证 SCRAM-SHA-256": "验证 SCRAM-SHA-256、MD5、Cleartext、trust、cert、peer、LDAP、RADIUS、ident 及拒绝场景，核对实际协议与真实登录。MAC 是信息上传，验证 HBA／SSO 白名单。PAM／BSD 仅记录环境限制，本轮不安排测试。",
            "PAM：三套": "PAM／BSD：当前 Linux 三套构建不具备相应登录验证条件，不列为已支持认证能力；相关限制说明保留，不再列活动测试点。",
            "BSD：当前": "认证范围：国密和未列明的平台认证不在本轮验证范围。",
            "本轮无跳过项。": "本轮无跳过项。6 项严格预期失败仍为三模式 OUT／INOUT 与多组查询结果组合，不计为支持该组合。编号追溯与文档同步另行检查，不计入功能节点。",
            "七模块功能分类、中文输入": "七模块功能分类、中文输入、操作及预期沿用原方案格式；Word、XMind、代码清单的 160 个活动测试点逐项对应。退役编号不复用，删减理由见 CASE_REDUCTION.json。",
        }
        if current is None:
            for prefix, replacement in overrides.items():
                if text.startswith(prefix):
                    text = replacement
                    break
        if text.startswith("证据目录："):
            text = "证据目录：docs/_static/kes-testing/regression-20261119"
        set_text(p, text)
    for row in doc.tables[0].rows:
        if row.cells and row.cells[0].text == "日 期":
            set_text(row.cells[1].paragraphs[0], "2026.11.19")
        if row.cells and row.cells[0].text == "文档编号":
            set_text(row.cells[1].paragraphs[0], "{项目编号}-TP-asynckb-V1.5")
    history = doc.tables[1]
    if not any("160 个" in c.text for r in history.rows for c in r.cells):
        row = next(r for r in history.rows[1:] if r.cells and not r.cells[0].text)
        for cell, text in zip(row.cells, ("V1.5", "项目组", "2026.11.19", "", "",
                "精简为 160 个测试点、669 个节点；补入性能与短时压力的 7 场景、21 组实测。")):
            set_text(cell.paragraphs[0], text)
    for row in doc.tables[2].rows:
        key = row.cells[0].text
        if key == "测试范围":
            value = f"tests/kes：{len(list((ROOT / 'tests/kes').rglob('test_*.py')))} 个测试文件、160 个测试点、669 个参数化节点；另有非功能 7 场景、21 组"
        elif key == "测试源码快照 SHA256":
            value = summary["source_sha256"]
        elif key == "节点清单与证据":
            value = "docs/_static/kes-testing/regression-20261119；XML、test-cases.json 和 parameterized-results.json"
        else:
            continue
        set_text(row.cells[1].paragraphs[0], value)
    for table in (doc.tables[3], doc.tables[4], doc.tables[8]):
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    text = p.text.replace("六模块", "七模块").replace("848", "669")
                    if text.startswith("无。ROWVERSION"):
                        text = "无。无法执行的环境限制只记录说明，不计通过；已知组合限制单列预期失败。"
                    set_text(p, text)
    for row, code in zip(doc.tables[5].rows[1:], xmind.MODULES):
        module = summary["modules"][code]
        values = [row.cells[0].text, xmind.MODULES[code][0].split(" ", 1)[1],
                  str(module["points"]), str(module["nodes"]),
                  f"通过 {module['outcomes'].get('passed', 0)}" +
                  (f"；预期失败 {module['outcomes']['xfailed']}"
                   if module['outcomes'].get('xfailed') else "")]
        for cell, text in zip(row.cells, values):
            set_text(cell.paragraphs[0], text)
    if not any(p.text.startswith("6.8 性能") for p in doc.paragraphs):
        anchor = next(p for p in doc.paragraphs if p.text.startswith("7 执行流程")
                      and p.style.name == "Heading 1")
        heading = next(p for p in doc.paragraphs if p.style.name == "Heading 2")
        body = next(p for p in doc.paragraphs if p.text.startswith("验证独立发行包"))
        code = next(p for p in doc.paragraphs if p.style.name == "Source Code")
        for kind, text in performance_paragraphs():
            insert_before(anchor, {"heading": heading, "body": body, "code": code}[kind], text)
    # Update the static contents list without replacing its typography.
    toc_anchor = next(p for p in doc.paragraphs if p.text == "7 执行流程与质量门禁"
                      and p.style.name == "Normal")
    if not any(p.text == "6.8 性能与短时压力测试" for p in doc.paragraphs):
        insert_before(toc_anchor, toc_anchor, "6.8 性能与短时压力测试")
    actual_ids = {m.group() for p in doc.paragraphs
                  if (m := POINT_ID.match(p.text)) and p.style.name == "Heading 4"}
    if actual_ids != set(case_map):
        raise ValueError(f"Word point mapping mismatch: {actual_ids ^ set(case_map)}")
    for target in (source, DOWNLOADS / "asynckb驱动测试方案.docx",
                   DOCS / "asynckb驱动测试方案.docx"):
        doc.save(target)


def sync_report(cases, summary):
    source = DOCS / "asynckb驱动兼容性测试报告（按模板）.docx"
    doc = Document(source)
    for p in doc.paragraphs:
        text = p.text.replace("2026-11-12", "2026-11-19")
        text = text.replace("231 个", "160 个").replace("848 项", "669 项")
        text = text.replace("842 项", "663 项").replace("788 项", "615 项")
        text = text.replace("54 项", "48 项")
        text = text.replace("asynckb-regression-20261112-174654",
                            "docs/_static/kes-testing/regression-20261119")
        if text.startswith("本轮未测吞吐量"):
            text = "已完成三模式 7 场景、21 组性能与短时压力测试，1,901,403 次操作、0 错误。记录吞吐和 P50/P95/P99；每组常规 10 秒、持续负载 120 秒，池上限 8、最多 32 任务。未设置未经约定的吞吐门槛。"
        elif text.startswith("覆盖连接池并发、超时"):
            text = "已执行每模式 120 秒持续查询、32 任务并发及混合提交／回滚，事务行数、池超时恢复、会话与测试表清理核对通过。不替代 24 小时长稳，不推定生产容量或无内存泄漏。"
        elif text.startswith("下表列出本轮确认"):
            text = "下表列出本轮确认的接口或环境限制。性能与短时压力已完成，长期稳定性及全平台矩阵未执行。"
        elif text.startswith("下表按第 3 章"):
            text = "下表按第 3 章需求给出结果；非功能恢复用例不重复计数，性能与短时压力另列 21 组，不并入 669 个功能节点。"
        elif "（KB-" in text:
            match = re.search(r"（KB-(\w+)）", text)
            if match:
                text = xmind.module_summary(cases, match.group(1))
        set_text(p, text)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    text = p.text.replace("2026-11-12", "2026-11-19")
                    if "当前构建仅确认配置限制" in text:
                        text = text.replace("当前构建仅确认配置限制", "当前环境不具备登录验证条件")
                    set_text(p, text)
    # Requirement and quality rows retain the original table layout.
    for row in doc.tables[2].rows:
        if len(row.cells) < 5:
            continue
        if row.cells[1].text == "性能需求":
            set_text(row.cells[4].paragraphs[0], "7 场景、三模式 21 组，吞吐和分位时延")
        if row.cells[1].text == "稳定性需求":
            set_text(row.cells[3].paragraphs[0], "短时压力与资源观察")
            set_text(row.cells[4].paragraphs[0], "120 秒持续查询及并发事务；未执行 24 小时长稳")
    groups = (("CONN", "PROTO", "AUTH"), ("TYPE", "EXEC"), ("POOL", "SA"))
    for index, codes in enumerate(groups, 1):
        passed = sum(summary["modules"][c]["outcomes"].get("passed", 0) for c in codes)
        nodes = sum(summary["modules"][c]["nodes"] for c in codes)
        failed = nodes - passed
        set_text(doc.tables[4].rows[index].cells[5].paragraphs[0],
                 f"通过 {passed} 项" + (f"；预期失败 {failed} 项" if failed else ""))
        row = doc.tables[6].rows[index]
        set_text(row.cells[3].paragraphs[0], f"{passed / nodes * 100:.2f}%")
        set_text(row.cells[4].paragraphs[0], f"{passed}/{nodes} 项通过" +
                 (f"；{failed} 项预期失败" if failed else ""))
    set_text(doc.tables[4].rows[-1].cells[5].paragraphs[0], "性能与短压 21 组完成；长稳及全版本矩阵未执行")
    set_text(doc.tables[4].rows[-1].cells[6].paragraphs[0], "实测 Python 3.10.12；独立非功能统计")
    for row in doc.tables[6].rows:
        if not row.cells:
            continue
        if row.cells[0].text in {"性能测试", "稳定性测试"}:
            stable = row.cells[0].text == "稳定性测试"
            values = ("PERF-006/007" if stable else "PERF-001～007", "100%", "100%",
                      "三模式短时负载完成；24 小时长稳未做" if stable else
                      "21/21 组完成，0 错误；无约定绝对速度门槛")
            for cell, text in zip(row.cells[1:], values):
                set_text(cell.paragraphs[0], text)
    for target in (source, DOCS / "asynckb驱动兼容性测试报告.docx",
                   DOWNLOADS / source.name, DOWNLOADS / "asynckb驱动兼容性测试报告.docx"):
        doc.save(target)


def main():
    cases, summary = merge_evidence()
    sync_plan(cases, summary)
    sync_report(cases, summary)
    xmind.build(cases)
    for name in ("asynckb驱动测试方案.xmind", "完整 asyncpg-KES 测试体系.xmind"):
        shutil.copy2(xmind.OUTPUT, DOWNLOADS / name)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
