# 新版本数据库适配与回归结果

## 2026-11-12 完整复测

当前 231 个测试点、848 个执行用例：842 passed、0 skipped、6 xfailed，
没有非预期失败。SQL Server ROWVERSION 已从 `master` 创建临时业务数据库，
验证插入的 8 字节返回值及更新后的变化；测试结束后删除本次临时数据库。
无法执行的 6 项 PAM 登录用例已移除，不再计为跳过或通过。
证据位于下载目录 `asynckb-regression-20261112-174654`；以下保留原始历史记录。

## 测试环境

实测日期：2026-11-09。三模式均连接 `127.0.0.1` 的 `test` 数据库。

| 模式 | 端口 | 实例实际版本 |
| --- | --- | --- |
| MySQL | 54321 | KingbaseES V009R003C018 |
| Oracle | 54322 | KingbaseES V009R002C016 |
| SQL Server | 54323 | KingbaseES V009R004C019 |

## 适配依据

类型名称、OID、参数方向及结果线路格式，以当前连接读取到的系统目录和协议描述为准，
不以旧实例的类型名称或 OID 为标准。例如 SQL Server 当前使用 `sys.int`，
不能要求其元数据名称为 `pg_catalog.int4`。OID 不写死，也不通过字符串化 Python 参数规避类型错误。

Python 返回值仍需符合类型语义：整数为 `int`，数值为 `Decimal`/`float`，
日期时间为相应 `datetime` 对象，二进制为 `bytes`，唯一标识符为 `UUID`。
测试同时核对实际值、Python 类型、NULL、重复执行和数据库写入/回滚状态。

## 本轮修复

- SQL Server 原生整数/数值类型同时注册文本和二进制解码器，按照实际 RowDescription 选择格式。
- 为执行阶段文本格式的 BINARY/VARBINARY/IMAGE 增加十六进制解码，避免返回字符串。
- 直接 CALL/EXEC 及 SQL Server 直接函数查询，从 `pg_proc` 读取无歧义签名的真实参数 OID；
  调用方显式指定的参数方向继续优先。Oracle 不再对这些调用统一标记 INOUT。
- SQL Server 批量执行使用显式事务；外层已有事务时使用保存点，避免捕获异常后提交部分写入。
- SQL Server schema、视图定义、主键和唯一约束反射改为查询有效的 `pg_catalog` 目录。
- 元数据测试使用新实例的实际类型名称和服务器标识符长度；NOCOUNT 测试检查新版已接受的原语法。

## 回归结果

| 测试模块 | 通过 | 其他结果 |
| --- | ---: | --- |
| 连接与模式初始化 | 15 | 无 |
| 协议与异步调度（含占位符） | 145 | 无 |
| 类型 OID 与 codec | 98 | 1 项服务器限制跳过 |
| 查询执行、事务与语句资源 | 173 | 无 |
| 连接池 | 77 | 无 |
| SQLAlchemy 方言 | 69 | 无 |
| 存储过程与多结果集专项 | 54 | 6 项已知限制，严格预期失败 |

合计 **631 passed，0 failed，1 skipped，6 xfailed**。
六个功能模块共 577 项通过；类型模块包含 19 项执行阶段线路格式/Python 类型回归。
批量错误在外层自动/手动事务中被捕获的 6 个组合均验证无残留写入。

原始机器可读结果：[new-version-results.xml](../_static/kes-testing/new-version-results.xml)。

## 保留限制

1. OUT/INOUT 与多组查询结果同时返回的 6 项组合仍出现结果列数与描述不一致。
   保留原成功结果断言，仅对 `ProtocolError` 标记 `xfail(strict=True)`；
   其他异常和意外通过都会使测试失败。这 6 项不计为已完成能力，本轮未增加多结果集接口。
2. SQL Server 对标量函数执行 `CALL fn(41)` 不返回标量，字面量与绑定参数均如此；
   `SELECT fn($1)` 正常返回并验证 NULL 和重复调用，不能把 CALL 的空结果当作函数值。
3. 当前 SQL Server 的 `test` 数据库拒绝 ROWVERSION 及相关函数。该用例仅在收到
   精确的服务器不支持错误时跳过，不代表驱动已验证 ROWVERSION。
4. 本轮不承诺任意存储过程语法、复杂调用表达式、重载签名和其他数据库版本的完整兼容性。

## 重现

修改 Cython 源码后先重编译，确保运行的是当前源码生成的扩展：

```bash
ASYNCKB_BUILD_CYTHON_ALWAYS=1 python3 setup.py build_ext --inplace
ASYNCKB_KES_PASSWORD='<password>' python3 -m pytest -q --assert=rewrite \
  --tb=short tests/kes --junitxml=docs/_static/kes-testing/new-version-results.xml \
  -o junit_family=legacy
```
