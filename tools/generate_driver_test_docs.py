"""Generate the driver-only XMind test plan and compatibility test report."""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import re
import uuid
from zipfile import ZipFile

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT.parent
TEMPLATE_DIR = DOWNLOADS / "产出物文档_模板" / "测试"
TEMPLATE_XMIND = TEMPLATE_DIR / "驱动测试方案.xmind"
MANIFEST = ROOT / "tests/kes/case_manifest.json"
EVIDENCE = DOWNLOADS / "asynckb-regression-20261112-174654"
OUT_PLAN = ROOT / "docs/kes-testing/asynckb驱动测试方案.xmind"
OUT_REPORT = ROOT / "docs/kes-testing/asynckb驱动兼容性测试报告.docx"

MODULES = {
    "CONN": ("功能模块1 连接与兼容模式", "tests/kes/connection_initialization/"),
    "PROTO": ("功能模块2 协议自解析与异步调度", "tests/kes/protocol_and_async/"),
    "TYPE": ("功能模块3 数据类型、OID 与 Codec", "tests/kes/types_and_codecs/"),
    "EXEC": ("功能模块4 查询执行、事务与语句资源", "tests/kes/execution_transactions_statements/"),
    "POOL": ("功能模块5 连接池", "tests/kes/pool/"),
    "SA": ("功能模块6 SQLAlchemy 异步方言", "tests/kes/sqlalchemy_dialect/"),
    "AUTH": ("功能模块7 用户认证与 MAC 信息上传", "tests/kes/authentication/"),
}

INTERFACES = {
    "CONN": "asynckb.connect()、create_pool()、ConnectParams、DSN、service、passfile、get_kes_mode()",
    "PROTO": "Connection.execute/fetch/fetchrow/fetchval/fetchmany/executemany/copy_*；$n/?/:n/@name 参数绑定；协议调度、取消和超时",
    "TYPE": "Connection.prepare()、PreparedStatement.get_parameters/get_attributes、set_type_codec()、reset_type_codec()、Record 解码",
    "EXEC": "Connection 查询接口、prepare()、PreparedStatement、Cursor、transaction()、is_in_transaction()、DEALLOCATE 状态管理",
    "POOL": "create_pool()、Pool.acquire/release/close/expire_connections()、PoolConnectionProxy、连接池回调",
    "SA": "kingbase+asynckb:// URL、SQLAlchemy AsyncEngine、Dialect 编译/反射、Alembic online migration",
    "AUTH": "SCRAM/MD5/Cleartext 握手、密码回调/passfile、TLS 身份、peer/ident、LDAP/RADIUS、MAC 上传及白名单",
}


def uid():
    return str(uuid.uuid4())


def topic(title, children=None, notes=None, *, folded=False):
    result = {"id": uid(), "title": title}
    if children:
        result["children"] = {"attached": children}
        if folded:
            result["branch"] = "folded"
    if notes:
        result["notes"] = {"plain": {"content": notes}}
    return result


def load_results():
    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))
    result_rows = json.loads(
        (EVIDENCE / "parameterized-results.json").read_text(encoding="utf-8")
    )
    results = {row["nodeid"]: row for row in result_rows}
    for case in cases:
        path, function = case["nodeid"].split("::")
        source = (ROOT / path).read_text(encoding="utf-8")
        lines = source.splitlines()
        case["line"] = next(i for i, line in enumerate(lines, 1)
                            if line.startswith("def " + function + "(")
                            or line.startswith("async def " + function + "("))
        case["module"] = case["id"].split("-")[1]
        prefix = case["nodeid"]
        case["results"] = [row for nodeid, row in results.items()
                           if nodeid == prefix or nodeid.startswith(prefix + "[")]
        if not case["results"]:
            raise ValueError(f"missing result nodes for {case['id']}: {prefix}")
    if len(cases) != 231 or len(results) != 848:
        raise ValueError(f"unexpected baseline: {len(cases)} points, {len(results)} nodes")
    if Counter(row["outcome"] for row in result_rows) != {
            "passed": 842, "xfailed": 6}:
        raise ValueError("test evidence does not match the documented 842/6 result")
    return cases


def outcome_text(case):
    statuses = Counter(row["outcome"] for row in case["results"])
    parts = []
    if statuses["passed"]:
        parts.append(f"通过 {statuses['passed']}")
    if statuses["xfailed"]:
        parts.append(f"已知限制、预期失败 {statuses['xfailed']}")
    if statuses["skipped"]:
        parts.append(f"跳过 {statuses['skipped']}")
    if statuses["failed"] or statuses["error"]:
        parts.append(f"失败/错误 {statuses['failed'] + statuses['error']}")
    return "；".join(parts) + f"；共 {len(case['results'])} 个参数化执行场景"


def case_topic(case):
    path, function = case["nodeid"].split("::")
    modes = sorted({re.search(r"\[(mysql|oracle|sqlserver)", row["nodeid"]).group(1)
                    for row in case["results"]
                    if re.search(r"\[(mysql|oracle|sqlserver)", row["nodeid"])})
    parameters = "、".join(modes) if modes else "按测试函数输入执行"
    if case["module"] == "EXEC" and "procedures_and_results/" in path:
        parameters += "；存储过程/多结果集边界场景"
    assertions = case.get("expected", [])
    assertion_note = "\n".join(assertions[:10]) if assertions else "由用例断言返回值、异常和数据库状态。"
    notes = (
        f"测试点编号：{case['id']}\n"
        f"作用：{case['title']}。\n"
        f"配置值／输入：{parameters}\n"
        f"预期结果：以测试方案要求的返回值、异常、数据库状态和资源状态为准；"
        f"本轮结果为：{outcome_text(case)}。\n"
        f"核心验证逻辑：执行该测试函数覆盖的操作，逐项核对断言。\n"
        f"完整源码断言：\n{assertion_note}\n"
        f"源码追溯：{path}:{case['line']}::{function}"
    )
    results = []
    for row in case["results"]:
        title = row["nodeid"].split("::", 1)[-1]
        label = {"passed": "通过", "xfailed": "预期失败（已知限制）",
                 "skipped": "跳过", "failed": "失败", "error": "错误"}[row["outcome"]]
        detail = f"完整节点：{row['nodeid']}\n结果：{label}"
        if row.get("detail"):
            detail += f"\n说明：{row['detail']}"
        results.append(topic(f"{title}：{label}", notes=detail))
    children = [
        topic(f"作用：{case['title']}"),
        topic(f"配置值／输入：{parameters}"),
        topic("核心验证逻辑", [
            topic("触发：运行对应 pytest 测试函数及参数化组合。"),
            topic("校验：检查测试函数中的返回值、异常、状态和资源断言。"),
            topic(f"预期／实测：{outcome_text(case)}。"),
        ]),
        topic(f"实测执行节点（{len(results)}）", results, folded=True),
    ]
    return topic(f"{case['id']}  {case['title']}", children, notes=notes,
                 folded=True)


def module_nodes(cases, code):
    result = []
    for case in cases:
        if case["module"] == code:
            result.append(case_topic(case))
    return result


def build_xmind(cases):
    with ZipFile(TEMPLATE_XMIND) as archive:
        entries = [(info, archive.read(info.filename))
                   for info in archive.infolist()]
        sheets = json.loads(archive.read("content.json"))
    sheet = sheets[0]
    root = sheet["rootTopic"]
    root["title"] = "asynckb KES 三模式驱动测试方案"

    requirements = [topic(
        f"{label}：{sum(c['module'] == code for c in cases)} 个测试点",
        [topic(case["id"] + " " + case["title"])
         for case in cases if case["module"] == code], folded=True,
    ) for code, (label, _) in MODULES.items()]
    mappings = [topic(label, [
        topic("测试编号", [topic(c["id"] + " " + c["title"])
                           for c in cases if c["module"] == code], folded=True),
        topic("对应测试目录", notes=MODULES[code][1]),
    ], folded=True) for code, (label, _) in MODULES.items()]
    focus = [topic(label, [
        topic("驱动接口", notes=INTERFACES[code]),
        topic("验证方式", notes="通过真实连接与 pytest 断言核对驱动 API 行为；具体点位见该模块编号。"),
    ]) for code, (label, _) in MODULES.items()]

    environment = [
        topic("驱动发行包／导入名：asynckb；版本：0.31.0.post12"),
        topic("Python：3.10.12；Linux x86_64"),
        topic("KES MySQL：127.0.0.1:54321；V009R003C018；数据库 test"),
        topic("KES Oracle：127.0.0.1:54322；V009R002C016；数据库 test"),
        topic("KES SQL Server：127.0.0.1:54323；V009R004C019；数据库 test"),
        topic("测试密码通过 ASYNCKB_KES_PASSWORD 注入；不写入测试文档。"),
    ]
    module_notes = {
        "TYPE": [topic("ROWVERSION 场景", [
            topic("通过 master 创建临时业务数据库，验证插入和更新后均返回 8 字节 bytes。")
        ])],
        "EXEC": [
            topic("过程与函数调用", [
            topic("按模式覆盖 IN、OUT、IN OUT、函数返回、普通结果读取及 Oracle RETURNING INTO；详见 EXEC 模块对应编号。"),
            topic("OUT/INOUT 与多个结果集同时返回的 6 个参数组合出现 ProtocolError，列为已知限制，不计功能通过。"),
            ]),
            topic("SQL Server 多结果集场景", [
            topic("两个 SELECT 写法分别通过 execute、fetch、prepare 执行；6 个组合均通过。"),
            topic("驱动接口不保留结果集分组、不提供 nextset()；测试记录可读结果与能力边界。"),
            ]),
        ],
        "AUTH": [topic("认证能力边界", [
            topic("PAM 登录：三个构建均不支持，登录测试已从本测试集移除；KB-AUTH-014 退役，不复用。"),
            topic("PAM/BSD 配置限制检查通过，不等同于对应认证方式登录通过。"),
        ])],
    }
    test_modules = [topic(
        MODULES[code][0], module_nodes(cases, code) + module_notes.get(code, []),
        folded=True,
    ) for code in MODULES]

    root["children"] = {"attached": [
        topic("需求分析", [
            topic("原始需求", notes="基于 asyncpg 的异步驱动代码，一套 asynckb 发行包兼容 KES MySQL、Oracle、SQL Server 三种模式。测试聚焦驱动层，不将 SQLAlchemy/Alembic 框架自身功能作为驱动测试范围。"),
            topic("需求分解表", requirements),
            topic("关联功能分析", [topic("驱动接口到三模式协议、类型、事务和资源行为的适配由本驱动实现；数据库语义由 KES 服务端提供。")]),
            topic("使用约束", [
                topic("驱动限制", notes="存储过程语言与多结果集迭代接口不在适配范围；只报告已验证调用场景和限制。"),
                topic("测试边界", notes="仅本次三套 KES 构建、Python 3.10/Linux 实测；不能外推至其他版本、操作系统或 HA 拓扑。"),
            ]),
            topic("需求列表和用例对应", mappings),
            topic("测试重点分析", focus),
        ]),
        topic("测试环境", [
            topic("功能测试环境", environment),
            topic("非功能测试环境", [topic("本次不包含长期压力、性能基准及多节点故障转移。")]),
        ]),
        topic("测试方案设计", [
            topic("功能测试", test_modules),
        ]),
        topic("测试结果摘要", [
            topic("231 个活跃测试点；848 个参数化执行节点。"),
            topic("842 passed；0 skipped；6 strict xfailed；0 failed/error。"),
            topic("完整报告：asynckb驱动兼容性测试报告.docx；逐节点报告见下载目录证据包。"),
        ]),
    ]}
    root["notes"] = {"plain": {"content": (
        "格式参考模板目录中的‘驱动测试方案.xmind’：需求分析→需求分解→关联功能→使用约束→需求/用例映射→测试重点→环境→功能测试。"
        "本文件只覆盖 asynckb 数据库驱动，不纳入框架测试。总计 231 个活跃测试点、848 个执行节点；842 通过、0 跳过、6 个已知限制预期失败。"
        "每个测试点附 KB 编号、源码位置、验证内容与实测节点。"
    )}}
    sheet["title"] = "asynckb 七模块驱动测试方案"
    sheet["revisionId"] = uid()
    rendered = json.dumps(sheets, ensure_ascii=False, separators=(",", ":")).encode()
    OUT_PLAN.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUT_PLAN, "w") as output:
        for info, data in entries:
            if info.filename == "content.json":
                output.writestr(info, rendered)
            elif info.filename == "content.xml":
                # The current XMind JSON model is authoritative; don't retain
                # the template's placeholder XML as a conflicting legacy map.
                continue
            else:
                output.writestr(info, data)


def shade(cell, fill):
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    properties.append(shading)


def set_cell_text(cell, text, *, bold=False, color=None):
    cell.text = str(text)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.bold = bold
            run.font.name = "宋体"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
            if color:
                run.font.color.rgb = RGBColor(*color)
            run.font.size = Pt(9)


def table(document, headers, rows, widths=None):
    result = document.add_table(rows=1, cols=len(headers))
    result.style = "Table Grid"
    result.autofit = False
    for i, header in enumerate(headers):
        set_cell_text(result.rows[0].cells[i], header, bold=True, color=(255, 255, 255))
        shade(result.rows[0].cells[i], "1F4E78")
    for row in rows:
        cells = result.add_row().cells
        for i, value in enumerate(row):
            set_cell_text(cells[i], value)
            if len(result.rows) % 2 == 0:
                shade(cells[i], "EAF1F8")
    if widths:
        for row in result.rows:
            for cell, width in zip(row.cells, widths):
                cell.width = Cm(width)
    document.add_paragraph()
    return result


def add_heading(document, title, level=1):
    p = document.add_heading(title, level=level)
    p.paragraph_format.keep_with_next = True
    return p


def add_body(document, text):
    p = document.add_paragraph(text)
    p.paragraph_format.space_after = Pt(6)
    for run in p.runs:
        run.font.name = "宋体"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        run.font.size = Pt(10)
    return p


def module_rows(cases):
    rows = []
    for code, (name, _) in MODULES.items():
        grouped = [case for case in cases if case["module"] == code]
        nodes = Counter(row["outcome"] for case in grouped for row in case["results"])
        rows.append((name, len(grouped), sum(nodes.values()), nodes["passed"],
                     nodes["xfailed"], nodes["skipped"], nodes["failed"] + nodes["error"]))
    return rows


def build_report(cases):
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.4)
    section.right_margin = Cm(2.2)
    styles = doc.styles
    styles["Normal"].font.name = "宋体"
    styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    styles["Normal"].font.size = Pt(10)
    for name, size in (("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 11)):
        style = styles[name]
        style.font.name = "黑体"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(31, 78, 121)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(95)
    run = title.add_run("asynckb 驱动兼容性测试报告")
    run.bold = True
    run.font.name = "黑体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
    run.font.size = Pt(24)
    run.font.color.rgb = RGBColor(31, 78, 121)
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.add_run("KingbaseES MySQL / Oracle / SQL Server 兼容模式").font.size = Pt(14)
    doc.add_paragraph()
    table(doc, ["项目", "内容"], [
        ("产品", "asynckb 异步数据库驱动"),
        ("驱动版本", "0.31.0.post12"),
        ("测试日期", "2026-11-12"),
        ("测试环境", "Python 3.10.12 / Linux x86_64"),
        ("测试范围", "七个驱动功能模块；231 个测试点，848 个执行节点"),
        ("文档版本", "V1.0"),
        ("编制", "项目组"),
    ], widths=[4.0, 11.0])
    doc.add_page_break()

    add_heading(doc, "修订记录")
    table(doc, ["版本", "日期", "说明"], [
        ("V1.0", "2026-11-18", "依据驱动测试方案模板，形成 asynckb 三模式兼容性测试报告。"),
    ], widths=[2.3, 3.0, 9.7])

    add_heading(doc, "1 测试概述")
    add_heading(doc, "1.1 测试目的", 2)
    add_body(doc, "验证独立发行包 asynckb 在 KingbaseES MySQL、Oracle、SQL Server 三种兼容模式下的异步连接、协议交互、类型编解码、查询和事务、连接池、SQLAlchemy 方言及认证行为。测试对象是数据库驱动；SQLAlchemy/Alembic 框架自身能力不作为本报告的验收对象。")
    add_heading(doc, "1.2 测试范围", 2)
    add_body(doc, "本轮覆盖 7 个驱动模块、231 个活动测试点和 848 个参数化执行节点。过程/函数及多结果集仅验证列明的调用场景与接口边界，不代表实现完整过程语言或 nextset() 能力。")
    add_heading(doc, "1.3 判定口径", 2)
    table(doc, ["状态", "判定"], [
        ("通过", "测试断言满足；限制检查通过只表示限制行为被确认。"),
        ("预期失败", "严格复现已知不支持行为；单列统计，不计功能通过。"),
        ("跳过", "本轮没有可跳过节点；无法在当前构建执行的 PAM 登录用例已从活动测试集移除。"),
        ("失败/错误", "非预期断言失败或执行错误；本轮为 0。"),
    ], widths=[3.0, 12.0])

    add_heading(doc, "2 测试环境")
    table(doc, ["模式", "地址/端口", "数据库", "KES 版本"], [
        ("MySQL", "127.0.0.1:54321", "test", "V009R003C018"),
        ("Oracle", "127.0.0.1:54322", "test", "V009R002C016"),
        ("SQL Server", "127.0.0.1:54323", "test", "V009R004C019"),
    ], widths=[3.0, 4.0, 2.5, 5.5])
    add_body(doc, "操作系统为 Linux x86_64，CPython 3.10.12。测试凭证通过环境变量注入，不记录在报告中。外部认证专项使用隔离网络命名空间中的临时 KES 实例和临时服务。")

    add_heading(doc, "3 测试执行")
    add_heading(doc, "3.1 执行组织", 2)
    add_body(doc, "完整回归分两批执行：现有实例上的功能及密码认证测试；隔离实例上的 LDAP、RADIUS、cert、peer、ident 与 MAC 专项。两批执行节点互不重叠，按 pytest 完整节点 ID 合并。")
    add_heading(doc, "3.2 结果汇总", 2)
    table(doc, ["模块", "测试点", "执行节点", "通过", "预期失败", "跳过", "失败/错误"], module_rows(cases), widths=[5.0, 1.5, 1.8, 1.5, 1.8, 1.2, 1.7])
    table(doc, ["总体指标", "结果"], [
        ("活动测试点", "231"),
        ("参数化执行节点", "848"),
        ("通过", "842"),
        ("已知限制、预期失败", "6"),
        ("跳过", "0"),
        ("非预期失败/错误", "0"),
    ], widths=[6.0, 9.0])

    add_heading(doc, "4 分模块测试结果")
    result_summary = {
        "CONN": "模式选择、连接参数、握手初始化和独立发行入口场景均通过。",
        "PROTO": "协议交互、异步调度、占位符、COPY、通知、超时、取消和连接恢复场景均通过。",
        "TYPE": "三模式类型、OID、Codec 及 ROWVERSION 临时数据库往返场景均通过。",
        "EXEC": "查询接口、事务、语句资源和过程/多结果集可复现场景通过；OUT 与多个结果集组合的 6 项参数场景为已知限制。",
        "POOL": "连接池生命周期、并发、容量、回收、取消及重连场景均通过。",
        "SA": "asynckb SQLAlchemy 方言、SQL 编译、连接、反射和迁移集成场景均通过。",
        "AUTH": "SCRAM、MD5、Cleartext、trust、证书、peer、LDAP、RADIUS、ident 及 MAC 相关活动测试均通过。PAM/BSD 限制检查不表示对应登录方式可用。",
    }
    for code, (name, _) in MODULES.items():
        add_heading(doc, name, 2)
        add_body(doc, result_summary[code])
        grouped = [case for case in cases if case["module"] == code]
        nodes = Counter(row["outcome"] for case in grouped for row in case["results"])
        add_body(doc, f"统计：{len(grouped)} 个测试点，{sum(nodes.values())} 个执行节点；通过 {nodes['passed']}，已知限制预期失败 {nodes['xfailed']}，跳过 {nodes['skipped']}，失败/错误 {nodes['failed'] + nodes['error']}。")

    add_heading(doc, "5 重点场景与限制")
    add_heading(doc, "5.1 存储过程、函数及输出参数", 2)
    add_body(doc, "三模式基础 CALL IN、IN OUT、OUT 参数场景已纳入测试；Oracle DML RETURNING INTO 另行验证。函数 SELECT 调用与 CALL 调用分别判断，不将两种语义混为一谈。数据库执行过程及函数，驱动负责现有接口下的参数绑定和协议交互。")
    add_heading(doc, "5.2 多结果集", 2)
    add_body(doc, "SQL Server ZIP 中两种双 SELECT 写法分别通过 execute、fetch、prepare 执行，6 个参数组合通过。当前 API 不保留结果集分组、不提供 nextset()。OUT/IN OUT 与多个结果集同时返回时，MySQL、Oracle、SQL Server 在缓存大小 0/100 下共 6 项出现 ProtocolError，作为已知限制严格预期失败；该结果不表示数据库本身不支持。")
    add_heading(doc, "5.3 服务端认证限制", 2)
    add_body(doc, "PAM 登录测试因三套 KES 构建均拒绝 pam HBA 方法，已从活动测试中删除；原编号 KB-AUTH-014 退役且不复用。PAM/BSD 配置限制检查仅确认服务端行为，不视为登录验证通过。")
    add_heading(doc, "5.4 ROWVERSION", 2)
    add_body(doc, "test/kingbase 数据库限制 ROWVERSION。本轮从 SQL Server master 创建唯一临时业务数据库，验证 INSERT 后返回 8 字节 bytes，UPDATE 后返回 8 字节且值改变；测试结束关闭连接并删除临时数据库。")

    add_heading(doc, "6 测试结论")
    add_body(doc, "在本报告列明的三套 KES 版本、Linux x86_64 和 Python 3.10.12 环境中，asynckb 三模式活动测试共 848 个执行节点，842 项通过、0 项跳过、0 项非预期失败；另有 6 项已知 OUT/多结果集组合限制按 strict xfail 复现。已执行的三模式常用驱动功能未发现新的回归问题。本结论不外推至未测试的操作系统、Python 版本、KES 补丁版本或生产拓扑。")

    add_heading(doc, "7 证据及复现")
    add_body(doc, "详细逐节点状态、编号和源码映射见配套 XMind 测试方案、仓库 TEST_CASE_INDEX.md 及证据目录 asynckb-regression-20261112-174654。证据包包含现有实例和隔离认证原始 JUnit 报告、合并报告、231 项用例清单及 848 项参数化结果。")
    add_body(doc, "现有实例回归命令：python3 -m pytest tests/kes --kes-mode all --kes-auth-configure-server --ignore=tests/kes/authentication/test_external_authentication.py --ignore=tests/kes/authentication/test_mac.py --ignore=tests/kes/authentication/test_mac_whitelist.py -q --assert=rewrite -rs -o junit_family=legacy")
    add_body(doc, "隔离认证命令：python3 -m tests.kes.authentication.run_isolated --kes-mode all -rs -o junit_family=legacy。执行环境、权限及清理要求见 tests/kes/authentication/README.md。")
    add_body(doc, f"测试方案源码快照 SHA256：{json.loads((EVIDENCE / 'summary.json').read_text())['source_sha256']}")

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("asynckb 驱动兼容性测试报告  |  V1.0  |  2026-11-18")
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT_REPORT)


def main():
    # The approved templates must be edited in place, not recreated.
    from tools.sync_kes_test_docs import main as sync_existing_templates
    sync_existing_templates()


if __name__ == "__main__":
    main()
