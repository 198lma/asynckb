# 存储过程、输出参数与多结果集专项测试

## 新版本结果

本文下面的 2026-11-03 结果仅为旧版本历史记录，不能用来判断新实例。
2026-11-09 新版本的修复、测试结果和限制见
[新版本回归报告](../../../docs/kes-testing/NEW_VERSION_RESULTS.md)。
新实例的 SQL Server 原生类型名称为 `sys.int` 等，不能继续期待 `int4`；
原始 `SET NOCOUNT ON/OFF` 已能执行。SQL Server 函数通过 `SELECT` 取得标量值，
`CALL` 即使用字面量也不返回函数结果。
OUT 与多结果集混合的 6 项用例保留成功预期，但只对已确认的 `ProtocolError`
标记严格预期失败，不计入已完成能力；发生其他错误或意外通过都将导致测试失败。

## 范围与执行

这是六个需求模块之外的补充场景目录，不代表新增存储过程适配模块。
本次只补测试、记录限制，并移除多结果集专用的 `Connection.fetchsets()`
及其内部 `return_sets` 分支；保留现有 OUT 参数方向绑定。
测试针对当前已修改的 asynckb 源码，不等同于上游原版 asynckb 的能力。
未继续增加多结果集解析适配，也没有回退已有的动态行解析实现。

| 文件 | 内容 |
| --- | --- |
| `test_procedures.py` | 三模式纯 OUT；函数 SELECT/CALL 对照；OUT 和多个查询结果同时返回；MySQL 嵌套过程；Oracle DML RETURNING INTO 与实际表数据、回滚 |
| `test_multiple_results.py` | SQL Server ZIP 原始两个 SELECT 写法；NOCOUNT 原语法和 KES 写法；字面量及绑定参数多 INSERT/UPDATE；空结果集边界限制 |
| `results.xml` | 本目录的真实执行结果和 ZIP 场景的返回值、表数据（JUnit XML） |
| `full_results.xml` | 包含原六模块和本目录的全量回归结果（JUnit XML） |

```bash
ASYNCKB_KES_PASSWORD='<测试密码>' PYTHONPATH=. pytest -q \
  tests/kes/procedures_and_results --kes-mode all --tb=short \
  --junitxml=tests/kes/procedures_and_results/results.xml -o junit_family=legacy

ASYNCKB_KES_PASSWORD='<测试密码>' PYTHONPATH=. pytest -q tests/kes \
  --kes-mode all --tb=short \
  --junitxml=tests/kes/procedures_and_results/full_results.xml -o junit_family=legacy
```

2026-11-03 在本地 KES V009R001C010 三模式实例、`test` 数据库实测：

- 本目录：**51 passed, 9 failed**，没有跳过或 xfail。
- 全量：**524 passed, 12 failed**，没有宣称全部兼容。
- 失败用例保留成功返回的预期断言，便于复现差异；它们不是已完成能力。

## ZIP 场景实际结果

来源：`/home/rootdba/下载/test_sqlserver_mul_sql.zip` 中的 `test_sqlserver.md`。
归档 SHA256：`5cf4796ceeb52f09da74a9d10d193c402b2a1c188cc5398e7e43338c79cadfce`。
ZIP 包含说明及截图，不含可直接执行的测试程序。

| 原始场景及执行方式 | 实测结果 | 能力边界 |
| --- | --- | --- |
| `select 1; select 2;`、`select 1 select 2`，无参数 `execute()` | 均返回命令状态 `SELECT 1`，随后查询正常 | execute 不返回查询行，不能据此宣称读取到了两个结果集 |
| 同上，`fetch()`、`prepare().fetch()`，无参数 PBE | 均返回行 `[(1,), (2,)]` | 合并返回行，不提供结果集分组或 nextset |
| 原文 `SET NOCOUNT ON`、`SET NOCOUNT OFF` | 当前服务器返回语法错误，SQLSTATE `42601` | 这是明确的原语法限制；两项限制测试通过不等于原语法兼容 |
| `SET nocount = on/off` 后执行多 INSERT/UPDATE，分号或空格分隔，字面量或绑定参数，三种接口 | 24 个组合均通过；最终表数据均为 `[(1, 'updated'), (2, 'yy')]`，随后查询正常 | 替代写法单独测试，不冒充 ZIP 原语法；仅检查状态/数据，不证明抓包中的计数消息序列完全一致 |
| 中间为空结果集，前后非空 | fetch 返回前后两行的 Record | 空集合不占返回列表位置，集合边界丢失 |

本文件实际收集 **34 项**，
即原始 SELECT 6 项、原语法限制 2 项、DML 24 项、空集合 2 项，均通过。
DML 的组合数为 `2 分隔方式 × 2 NOCOUNT × 3 接口 × 2 参数形式 = 24`。

## 存储过程与函数实际结果

| 场景 | 实测结果 |
| --- | --- |
| 三模式纯 OUT，显式声明方向；缓存 0/100；NULL、重复和批量执行 | 6 项通过。MySQL/Oracle 为 `(42, None)`，SQL Server 为 `(0, 42, None)`，首列为 `_retval_` |
| Oracle 匿名块中的 INSERT/UPDATE/DELETE RETURNING INTO | 3 项通过；返回 id/label，操作后表数据及回滚后数据均符合预期 |
| 三模式 `SELECT 函数($1)` | 3 项通过；输入 41 返回 42，输入 7 返回 8，输入 NULL 返回 NULL |
| Oracle `CALL 函数($1)`，默认及显式 IN | 2 项通过，均取得标量返回值 |
| MySQL `CALL 函数($1)` | 默认处理报 `INVALID MODE 变量绑定到 IN 位置`；显式 `parameter_modes=('in',)` 后通过 |
| SQL Server `CALL 函数($1)`，默认及显式 IN | 2 项失败，首个输入 41 时 fetchval 返回 None，而非函数值 42；不能将 CALL 和 SELECT 取值等同 |
| MySQL 内外层过程返回不同列结构，并包含空查询结果；缓存 0/100 | 2 项通过；返回前置行、内层 id/label、后置行；不保留空结果集边界 |
| 三模式同一次调用返回 INOUT/OUT 和两组查询结果；缓存 0/100 | 6 项失败，均为 ProtocolError：MySQL/Oracle 实际输出 2 列而当前描述为 1 列；SQL Server 实际输出 3 列而描述为 1 列。当前不支持该组合，不据此判定数据库不支持 |

混合场景失败发生在首次调用，后续 NULL、重复调用断言未执行，不算已验证。
基础混合 `CALL(IN, INOUT, OUT)` **不同时返回查询结果集**的用例仍在原模块：
`test_kes_explicit_parameter_directions`，三模式缓存 0/100 共 6 项均通过。
原模块也保留 Oracle IN/纯 OUT/INOUT、异常恢复、REF CURSOR、多个结果查询行，
以及 SQL Server CALL/EXEC 嵌套过程查询行测试；本次全量运行均通过这些节点。

Oracle 独立 SQL `INSERT ... RETURNING ... INTO` 仍被当前服务器拒绝，
需要匿名块或改用不带 INTO 的 `RETURNING`；零行和多行错误测试仍在原模块。
本目录没有将匿名块通过写成独立 SQL 通过。

## 剩余问题

新增 9 项失败为 3 项函数 CALL 差异和 6 项 OUT/多结果集组合失败。
另有原模块的 SQL Server 带参数多语句批处理回滚 3 项失败
（executemany/fetchmany/prepared）：未显式开启事务时批处理错误后仍残留更改。
这些问题没有因本次删除接口而被修复，也没有隐藏。
完整存储过程语法、所有输出类型和所有 KES 版本不在本次已验证结论内。
