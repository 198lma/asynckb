# KES 占位符兼容测试

## 范围

占位符转换依据连接识别出的模式执行，在发送 Parse 前转换 SQL 标记，
参数值仍通过 Bind 绑定，不拼接到 SQL 中。本次不修改 OUT 参数方向逻辑，
不新增多结果集或存储过程适配接口。

| 连接模式 | 支持形式 | 编号规则 |
| --- | --- | --- |
| MySQL | `?` | 按出现顺序对应位置参数；不可与 `$n` 绑定标记混用 |
| Oracle | `:n`、`:name` | 数字保留编号；名称不区分大小写，重复名称复用编号 |
| SQL Server | `@name` | 按首次出现顺序编号，完全同名时复用，区分大小写 |
| 所有模式 | `$n` | 保留原有编号和绑定方式 |

名称参数仍通过 `fetch*(sql, *args)` 的位置参数传值，不接收参数字典。
命名标记分配最小未占用编号，避开已有 `$n` 和 Oracle `:n`。
例如 `SELECT :name, :1, $2` 转换为 `SELECT $3, $1, $2`。

字符串、注释、引用标识符不转换；包含嵌套块注释、dollar quote、
Oracle q 引用及 SQL Server 方括号标识符的单元测试。
字符串反斜线规则读取连接的 `standard_conforming_strings` 设置。
MySQL 参数化 SQL 中使用 `??` 表示字面的 `?` 运算符；`?|`、`?&` 保持不变。

转换统一接入 `Connection._get_statement()`，覆盖带参数 `execute()`、
`fetch*()`、`executemany()`、`prepare()` 及游标。
缓存命中及已准备语句复用不重复转换，`PreparedStatement.get_query()`
保留应用提交的 SQL。无参数 `execute(sql)` 使用简单查询，原样发送 SQL。
非 KES PostgreSQL 不转换。

## 实际示例

以下三段分别在对应模式的连接上运行；`con` 为已连接的 `Connection`。

```python
# MySQL：两个问号对应两个输入。
row = await con.fetchrow("SELECT CAST(? AS INT), CAST(? AS INT)", 10, 20)
print(tuple(row))
```

```text
(10, 20)
```

```python
# Oracle：:x 与 :X 复用第一个输入，:2 使用第二个输入。
row = await con.fetchrow(
    "SELECT CAST(:x AS INT), CAST(:X AS INT), CAST(:2 AS INT)", 10, 20)
print(tuple(row))
```

```text
(10, 10, 20)
```

```python
# SQL Server：@x 复用第一个输入，@X 使用第二个输入。
row = await con.fetchrow(
    "SELECT CAST(@x AS INT), CAST(@x AS INT), CAST(@X AS INT)", 10, 20)
print(tuple(row))
```

```text
(10, 10, 20)
```

上述输出于 2026-11-03 在本地 KES V009R001C010 三模式实例实际取得，
不是仅根据转换规则推算的输出。

## 测试与复现

测试文件：`tests/kes/protocol_and_async/test_placeholders.py`。

```bash
export ASYNCKB_KES_PASSWORD='<password>'
PYTHONPATH=. pytest -q tests/kes/protocol_and_async/test_placeholders.py \
  --kes-mode all --tb=short
```

默认连接 `127.0.0.1` 的 MySQL / Oracle / SQL Server 端口分别为
54321 / 54322 / 54323，用户 `system`，数据库 `test`。
可通过 `ASYNCKB_KES_HOST`、`ASYNCKB_KES_USER`、`ASYNCKB_KES_DATABASE`
及 `ASYNCKB_KES_<MODE>_PORT` 覆盖。

专项实测：**52 passed**，其中 36 项单元测试、16 项实库测试。
实库测试覆盖缓存大小 0 / 100、参数数量错误、类型错误与后续恢复、NULL、
特殊字符输入、重复名称、保留编号、批量执行、预编译及游标缓存生命周期。
限制断言通过表示成功复现限制，不表示对应 SQL 已兼容。

全量回归命令与结果：

```bash
PYTHONPATH=. pytest -q tests/kes --kes-mode all --tb=short
```

```text
修改前：524 passed, 12 failed（共 536 项）
修改后：576 passed, 12 failed（共 588 项）
占位符专项：52 passed
```

通过 JUnit XML 按用例名称比较，新增失败 0 项，原有 12 个失败用例未变化：
SQL Server 绑定多语句的批量回滚 3 项、函数 CALL 3 项、
三模式 OUT 与多组查询结果混合返回 6 项。
未将这些失败改成跳过或 xfail，也未将其列为已完成能力。

## 已确认的限制

1. 本次转换的是数据值占位符，不转换表名、列名、类型名称或其他 SQL 方言。
   `%s`、参数字典不在支持范围内。
2. SQL Server 的 `DECLARE` 局部变量、`@@` 系统变量和 EXEC 形参标签不作为
   绑定标记。含 `@` 变量的过程、函数及触发器定义应使用无参数 `execute(sql)`。
   本功能不是完整 T-SQL 解析器，复杂语法不属于本次已验证范围。
3. 当前 SQL Server 实例拒绝带绑定参数的
   `DECLARE @local INT; SET @local=$1; SELECT @local`，返回 `42P02`。
   将 `@input` 转为 `$1` 后也相同；字面量批次可执行。
4. 当前 SQL Server 实例拒绝 `EXEC proc @formal=$1`，返回 `42601`；
   原生 `$1` 与兼容标记 `@input` 的实测结果一致。
   位置传参 `EXEC proc @input` 在测试中成功返回值 42。
5. 当前 MySQL 实例在部分表达式中可能将未指定类型的参数推断为 `text`。
   例如 `id >= $1` 和转换后的 `id >= ?` 均可能如此，需按业务使用
   `CAST(? AS INT)`。这不属于占位符编号问题。
   本次 MySQL 实例的 `sql_mode` 为 `ONLY_FULL_GROUP_BY,ANSI_QUOTES`；
   未宣称验证了其他 SQL 模式配置。
6. 占位符转换不解决既有的 OUT 混合多结果集、函数 CALL 及 SQL Server
   批量多语句回滚问题；详见 `tests/kes/procedures_and_results/README.md`。
