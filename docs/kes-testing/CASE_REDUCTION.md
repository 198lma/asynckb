# 测试点精简记录

2026-11-19：231 个功能点精简为 160 个，删除 71 个，七模块不变。
保留项不重编号，退役编号不复用；Word、XMind、manifest 和源码索引同步。

删减主要为重复连接/查询冒烟、通用工具/API 边界及非核心框架场景。
部分高级边界退出本轮验收，不声称其原断言全部仍有覆盖。
删除编号、原位置、原因和关联保留项见 [JSON 清单](CASE_REDUCTION.json)。

保留重点是动态 OID、实际类型及 codec、占位符、查询/事务/保存点、COPY 恢复、
池并发、SQLAlchemy 核心功能、基础 OUT/INOUT、Oracle DML 输出和 SQL Server
ZIP 两个多语句写法，以及可执行的认证场景。
六个 OUT 与多结果集组合失败节点仍严格记录，未因精简被掩盖。

实际复测：669 个节点，663 通过、6 预期失败、0 跳过、0 非预期失败。
性能与短时压力另计 7 场景、21 组。

删除可恢复，修改前备份位于：
`/home/rootdba/下载/asynckb-test-cleanup-backup-fqEBjtSV`。
其中 `repository-tests-and-docs.tar.gz` 保存原测试和仓库文档，下载目录的原
Word/XMind 另存同目录。备份不属于交付的活动测试清单。
