# asynckb KES 测试方案

## 1. 目标与范围

验证 asynckb 0.31.0.post12 在 KES MySQL、Oracle、SQL Server 三模式下的
驱动 API、协议、类型/OID/Codec、事务、连接池、SQLAlchemy 异步方言和认证。
仅连接 KES，不把 PostgreSQL 或其他厂商数据库结果代作 KES 验收。
逐点输入、步骤、预期结果及源码见 [Word 测试方案](asynckb驱动测试方案.docx)、
[XMind 测试方案](asynckb驱动测试方案.xmind)和 [编号索引](TEST_CASE_INDEX.md)。
Word 沿用现有章节、段落及表格格式，XMind 沿用用户提供的驱动模板。

## 2. 当前基线

2026-11-19 精简并实际重跑。一个 KB 编号对应一个测试函数；参数组合形成不同
pytest 节点。保留原编号，不重排、不复用退役编号。

| 模块 | 测试点 | 参数化节点 | 本轮结果 |
| --- | ---: | ---: | --- |
| 连接与兼容模式 | 8 | 12 | 12 通过 |
| 协议自解析与异步调度 | 28 | 100 | 100 通过 |
| 数据类型、OID 与 Codec | 34 | 87 | 87 通过 |
| 查询执行、事务与语句资源 | 42 | 200 | 194 通过、6 预期失败 |
| 连接池 | 13 | 43 | 43 通过 |
| SQLAlchemy 异步方言 | 20 | 40 | 40 通过 |
| 用户认证与 MAC 信息上传 | 15 | 187 | 187 通过 |
| 合计 | 160 | 669 | 663 通过、6 预期失败、0 跳过、0 非预期失败 |

过程、函数、OUT 和多结果集归属查询执行模块；包身份归属连接模块。
性能与短时压力另计 7 场景、三模式 21 组，不与功能节点相加。

## 3. 场景取舍

删除 71 个测试点，主要为重复验证、通用上游工具边界和非核心框架场景，
不以凑到固定数量为目标。保留类型与 OID、codec、绑定、取消恢复、COPY、
嵌套事务、OUT 参数、Oracle DML 输出及 SQL Server ZIP 的两个多语句写法。
部分高级边界不再单列，不能宣称所有删除断言仍被覆盖。

删减编号、原因及保留关联项见 [删减清单](CASE_REDUCTION.json)，原测试和文档
可从备份恢复。Alembic、部分流式/跨 schema 反射及 PAM/BSD 环境检查退出活动
测试点，不代表删除驱动功能，也不代表认证登录成功。

## 4. 环境

| 模式 | 地址 | 数据库 | KES 版本 |
| --- | --- | --- | --- |
| MySQL | 127.0.0.1:54321 | test | V009R003C018 |
| Oracle | 127.0.0.1:54322 | test | V009R002C016 |
| SQL Server | 127.0.0.1:54323 | test | V009R004C019 |

Linux x86_64、CPython 3.10.12。发行声明 Python >=3.9，本轮不代表全版本矩阵。
配置入口为 `tests/kes/support/config.py`，密码由 `ASYNCKB_KES_PASSWORD` 设置。
使用当前 schema，不要求创建驱动同名数据库或 schema。
账号应有临时对象及认证管理权限；ROWVERSION 在从 master 创建的唯一临时业务
数据库中测试并清理。外部认证服务由隔离测试构造，不修改宿主机 PAM。

## 5. 执行与追溯

```bash
python3 tools/check_test_traceability.py
python3 -m pytest tests/kes --kes-mode all --collect-only -q

# 现有实例功能及密码认证，临时角色和 HBA 退出时恢复。
ASYNCKB_KES_PASSWORD='<测试密码>' PYTHONPATH=. python3 -m pytest tests/kes \
  --kes-mode all --kes-auth-configure-server \
  --ignore=tests/kes/authentication/test_external_authentication.py \
  --ignore=tests/kes/authentication/test_mac.py \
  --ignore=tests/kes/authentication/test_mac_whitelist.py \
  -q --assert=rewrite -rs -o junit_family=legacy \
  --junitxml=full-suite-results.xml

# 独立认证，需要非 root Linux 用户、unshare 和 iproute2。
python3 -m pip install -r tests/kes/authentication/requirements.txt
PYTHONPATH=. python3 -m tests.kes.authentication.run_isolated \
  --kes-mode all -rs -o junit_family=legacy \
  --junitxml=isolated-suite-results.xml
```

两批不重叠，本轮分别为 `615 passed, 6 xfailed` 和 `48 passed`。
认证准备、依赖和恢复说明见 [认证 README](../../tests/kes/authentication/README.md)。
不启用专项时的默认跳过不能作为已完成证据。

## 6. 性能与短时压力

| 编号 | 场景 | 输入 |
| --- | --- | --- |
| PERF-001 | 单连接参数化查询，关闭缓存 | cache=0，10 秒 |
| PERF-002 | 单连接参数化查询，开启缓存 | cache=100，10 秒 |
| PERF-003 | 连接池低并发查询 | 池 8、任务 1，10 秒 |
| PERF-004 | 连接池等容量并发 | 池 8、任务 8，10 秒 |
| PERF-005 | 超过池容量并发 | 池 8、任务 32，10 秒 |
| PERF-006 | 持续并发查询 | 池 8、任务 32，120 秒 |
| PERF-007 | 并发提交和回滚 | 池 8、任务 32，10 秒 |

逐次校验返回值，记录吞吐、P50/P95/P99 和错误；事务最终行数等于成功提交数。
验证池占满后的超时恢复，关闭后检查会话、测试表及客户端资源。
三模式 21 组完成，1,901,403 次操作、0 错误，事务与清理核对通过。
未约定绝对速度门槛；120 秒短压不替代 24 小时长稳，不推定生产容量或无泄漏。
步骤和结果见 [性能说明](PERFORMANCE_TESTING.md)、[实测结果](PERFORMANCE_RESULTS.md)。

## 7. 判定与限制

返回值、Python 类型、异常、数据库状态及资源状态断言须满足，不能用无报错
代替核对，也不能为通过而跳过 codec 或类型错误。
六项严格预期失败仅限三模式、缓存 0/100 的 OUT/INOUT 与多结果集组合，
只接受 `ProtocolError`；不计功能通过，其他异常或意外成功须重新分析。

基础 CALL 输出及 Oracle 匿名块内 INSERT/UPDATE/DELETE RETURNING INTO 已验证。
多语句接口不保留结果集分组和空结果边界，不提供 `nextset()`。
SQL Server CALL 标量函数不取得目标返回值时使用 SELECT 调用；Oracle 独立 DML
RETURNING INTO 与匿名块执行不能混同。

PAM/BSD、国密、真实主备切换、网络故障注入、生产外部认证集群、全平台矩阵及
24 小时长稳不由本轮结果推定通过。MAC 是信息上传，不是独立密码算法；
HBA/SSO 验证不等于登录审计展示验证。

## 8. 证据与同步

[本轮证据](../_static/kes-testing/regression-20261119/)包含原始 JUnit、合并报告、
160 个点清单、669 个参数化结果及源码摘要。性能证据为
`docs/_static/kes-testing/performance/results-20261119.json`。

```bash
python3 -m pip install -r tools/requirements-test-docs.txt
PYTHONPATH=. python3 tools/sync_kes_test_docs.py
```

同步工具修改现有 Word 正文，不重新设计布局；XMind 保留模板主题及包内其他文件。
生成前须更新真实回归证据，工具拒绝重复或清单外节点。
