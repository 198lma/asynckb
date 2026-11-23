# 测试方案与代码索引

编号沿用测试方案和 XMind。一个编号对应一个测试函数；参数化执行共用编号，
模式、缓存大小等组合由 pytest 节点的 `[参数]` 后缀区分。

通过 `pytest tests/kes -k KB-EXEC-049 -v` 按编号执行；
JUnit 报告中的 `case_id`、`case_title`、`case_source` 用于追溯。

本索引由 `python3 tools/check_test_traceability.py --write-index` 生成，
新增测试时须同时更新方案、XMind、代码标记及 `tests/kes/case_manifest.json`。

## 连接初始化（8 个测试点）

| 编号 | 测试点 | 代码位置 |
| --- | --- | --- |
| KB-CONN-001 | 不传 kes_mode 时驱动通过服务端属性自动识别兼容模式 | [test_connection_detects_kes_mode_without_explicit_option](../../tests/kes/connection_initialization/test_connection_initialization.py#L16) |
| KB-CONN-002 | service file、passfile 和 primary 目标筛选可组合连接 KES | [test_service_file_passfile_and_primary_target_connect](../../tests/kes/connection_initialization/test_connection_initialization.py#L35) |
| KB-CONN-005 | 模式名称大小写归一化，且不允许 PostgreSQL 等非 KES 模式 | [test_mode_normalization_accepts_supported_names_and_rejects_unknown_names](../../tests/kes/connection_initialization/test_connection_initialization.py#L94) |
| KB-CONN-006 | DSN 解码 kes_mode、保留服务端参数并允许显式模式覆盖 | [test_dsn_parser_extracts_encoded_kes_mode_and_preserves_other_settings](../../tests/kes/connection_initialization/test_connection_initialization.py#L107) |
| KB-CONN-007 | 建连总超时会中止已建立 TCP 但不响应的协议握手 | [test_connect_timeout_aborts_stalled_protocol_handshake](../../tests/kes/connection_initialization/test_connection_initialization.py#L154) |
| KB-CONN-008 | 独立 asynckb 包加载本包协议扩展和 pgproto，不依赖原 asyncpg 包 | [test_asynckb_imports_its_own_protocol_extension](../../tests/kes/test_package_identity.py#L10) |
| KB-CONN-009 | SQLAlchemy 的 kingbase+asynckb 入口加载独立驱动 | [test_sqlalchemy_uses_the_asynckb_driver_entry_point](../../tests/kes/test_package_identity.py#L20) |
| KB-CONN-010 | SQLAlchemy 正确转换 asynckb 异常而非导入原 asyncpg 异常模块 | [test_sqlalchemy_error_translation_uses_asynckb_exceptions](../../tests/kes/test_package_identity.py#L31) |

## 协议与异步调度（28 个测试点）

| 编号 | 测试点 | 代码位置 |
| --- | --- | --- |
| KB-PROTO-001 | 只识别单条简单例程调用及绑定位置；表达式、多语句和非法编号不误识别 | [test_routine_bindings_only_identify_single_simple_invocations](../../tests/kes/protocol_and_async/test_placeholders.py#L29) |
| KB-PROTO-002 | MySQL ?、Oracle :编号／:名称、SQL Server @名称 转换为 $n，核对重用与混合编号 | [test_placeholder_numbering](../../tests/kes/protocol_and_async/test_placeholders.py#L62) |
| KB-PROTO-003 | 字符串、标识符、Dollar 引号和嵌套注释中的占位符文本保持不变 | [test_literals_identifiers_and_comments_are_not_parameters](../../tests/kes/protocol_and_async/test_placeholders.py#L72) |
| KB-PROTO-004 | 各模式引号、转义字符串、系统变量与注释中的占位符保护 | [test_mode_specific_quoted_regions_and_escape_strings](../../tests/kes/protocol_and_async/test_placeholders.py#L85) |
| KB-PROTO-006 | SQL Server 局部变量及 EXEC 形参标签不当作外部绑定参数 | [test_sqlserver_locals_and_exec_labels_are_not_bind_slots](../../tests/kes/protocol_and_async/test_placeholders.py#L109) |
| KB-PROTO-008 | SQL Server 未声明赋值和例程定义等歧义输入明确拒绝 | [test_sqlserver_ambiguous_assignments_and_routine_definitions_rejected](../../tests/kes/protocol_and_async/test_placeholders.py#L134) |
| KB-PROTO-009 | 非法编号、超限编号以及歧义混用明确拒绝 | [test_invalid_or_ambiguous_parameter_numbers_rejected](../../tests/kes/protocol_and_async/test_placeholders.py#L151) |
| KB-PROTO-010 | 三模式原生占位符覆盖查询、预编译、批量、游标、错误恢复及绑定安全 | [test_mode_placeholders_query_prepare_batch_cursor_and_recovery](../../tests/kes/protocol_and_async/test_placeholders.py#L166) |
| KB-PROTO-011 | 占位符样式的字面量与注释不改写，无绑定参数 execute 正常执行 | [test_placeholder_literals_comments_and_zero_argument_execute](../../tests/kes/protocol_and_async/test_placeholders.py#L228) |
| KB-PROTO-012 | 区分驱动绑定处理与 SQL Server 局部变量、具名 EXEC 的服务端限制 | [test_sqlserver_local_and_named_exec_server_restrictions](../../tests/kes/protocol_and_async/test_placeholders.py#L261) |
| KB-PROTO-013 | 重复具名参数复用同一位置，已有位置编号保留且不冲突 | [test_named_placeholders_reuse_and_reserved_numbers](../../tests/kes/protocol_and_async/test_placeholders.py#L305) |
| KB-PROTO-014 | 游标清理不会错误关闭仍可复用的改写后缓存语句 | [test_cursor_cleanup_preserves_cached_rewritten_statement](../../tests/kes/protocol_and_async/test_placeholders.py#L333) |
| KB-PROTO-016 | 配置模式与实际 KES 实例不一致时连接必须失败 | [test_connected_server_rejects_the_wrong_compatibility_mode](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L16) |
| KB-PROTO-017 | KES 模式识别失败后驱动关闭已建立的服务端会话 | [test_wrong_mode_initialization_closes_server_session](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L35) |
| KB-PROTO-020 | COPY records、CSV、TEXT、BINARY 四条数据路径结果一致 | [test_copy_round_trip_supports_records_csv_text_and_binary](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L68) |
| KB-PROTO-021 | COPY source 同时支持内存 bytes 和原 asynckb 的 bytes 文件路径 | [test_copy_source_accepts_inline_bytes_and_bytes_file_path](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L151) |
| KB-PROTO-022 | bytes 源的文件路径探测失败时仍按内存 COPY 数据处理 | [test_copy_inline_bytes_survives_path_probe_errors](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L201) |
| KB-PROTO-024 | COPY 支持异步 records、带参数查询、异步输出和异步输入链路 | [test_copy_async_records_parameterized_sink_and_source](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L247) |
| KB-PROTO-025 | 小结果 COPY 已完成后 sink 异常不触发无限取消等待 | [test_copy_completed_output_sink_failure_preserves_connection](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L318) |
| KB-PROTO-026 | 大结果 COPY 进行中 sink 异常能取消命令并复用连接 | [test_copy_active_output_sink_failure_preserves_connection](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L361) |
| KB-PROTO-027 | COPY source 首次和中途异常均回滚已发送数据并复用连接 | [test_copy_async_source_failures_are_atomic_and_connection_reusable](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L421) |
| KB-PROTO-028 | COPY source 超时后无部分数据且连接可继续查询 | [test_copy_async_source_timeout_is_atomic_and_connection_reusable](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L486) |
| KB-PROTO-029 | COPY 服务端先拒绝数据时不再为延迟 source 异常取消空闲连接 | [test_copy_server_error_before_source_error_preserves_connection](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L539) |
| KB-PROTO-030 | COPY 服务端报错与 source 超时竞态不产生内部异常或污染连接 | [test_copy_server_error_racing_source_timeout_preserves_connection](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L585) |
| KB-PROTO-031 | 小结果 COPY 已完成后 sink 超时不再取消已空闲的连接 | [test_copy_completed_output_sink_timeout_preserves_connection](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L635) |
| KB-PROTO-032 | COPY 服务端先报错后取消 source 任务不会阻塞连接复用 | [test_copy_server_error_before_source_cancellation_preserves_connection](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L679) |
| KB-PROTO-033 | 监听连接能收到发送连接发出的频道和 payload | [test_listen_notify_delivers_payload_in_both_modes](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L726) |
| KB-PROTO-035 | 三模式连续极短查询超时不会污染取消状态或后续连接 | [test_repeated_query_timeout_race_preserves_connection](../../tests/kes/protocol_and_async/test_protocol_and_async.py#L763) |

## 类型 OID 与 Codec（34 个测试点）

| 编号 | 测试点 | 代码位置 |
| --- | --- | --- |
| KB-TYPE-001 | 三模式 ENUM 自定义 codec 同时作用于标量和数组元素 | [test_enum_custom_codec_applies_to_scalar_and_array](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L37) |
| KB-TYPE-002 | 三模式递归解析 DOMAIN 基类型并保持 domain codec 限制 | [test_nested_domain_uses_base_codec_and_rejects_custom_domain_codec](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L74) |
| KB-TYPE-003 | 三模式 COMPOSITE 映射编解码及 schema cache 重载可用 | [test_composite_mapping_round_trip_after_schema_cache_reload](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L118) |
| KB-TYPE-004 | 三模式 RANGE codec 保持边界归一化并拒绝非法输入 | [test_range_codec_round_trip_and_invalid_input](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L152) |
| KB-TYPE-005 | SQL_VARIANT 的异构值以文本形式返回并可绑定字符串 | [test_sqlserver_sql_variant_uses_text_representation](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L181) |
| KB-TYPE-006 | 原 asynckb 标量、UUID、二进制、数组、JSONB 和网络 codec 正常 | [test_standard_asynckb_scalar_array_and_network_codecs](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L206) |
| KB-TYPE-007 | Oracle 隐式外层事务按会话 SERIALIZABLE 校验嵌套隔离级别 | [test_oracle_nested_transaction_uses_session_default_isolation](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L251) |
| KB-TYPE-008 | MySQL 专有类型的自定义 codec 重置后恢复 KES 默认 codec | [test_mysql_custom_codec_reset_restores_kes_default](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L282) |
| KB-TYPE-009 | Oracle 专有类型的自定义 codec 重置后恢复 KES 默认 codec | [test_oracle_custom_codec_reset_restores_kes_default](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L325) |
| KB-TYPE-010 | 三模式文本 wire 类型拒绝错误 binary builtin 且连接可复用 | [test_kes_builtin_codec_rejects_incompatible_binary_wire_format](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L354) |
| KB-TYPE-011 | Oracle DATE codec 映射实际 TIMESTAMP OID 并保留 PG date tuple | [test_oracle_standard_date_tuple_codec_maps_to_timestamp_oid](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L454) |
| KB-TYPE-012 | 标准 pg_catalog.json codec API 映射到 KES MySQL JSON | [test_mysql_standard_json_codec_name_maps_to_kes_json](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L488) |
| KB-TYPE-013 | MySQL JSON builtin codec 同步更新 domain 及其基类型 | [test_mysql_builtin_json_codec_updates_domain_and_base_type](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L550) |
| KB-TYPE-014 | MySQL 标准日期时间和 BIT codec 名称映射到实际 KES OID | [test_mysql_standard_codec_name_maps_to_kes_type](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L607) |
| KB-TYPE-015 | 标准时间 tuple codec 保留 PG epoch 语义并适配 KES 文本协议 | [test_mysql_standard_temporal_tuple_codec_maps_to_kes_text_protocol](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L657) |
| KB-TYPE-016 | MySQL TIMESTAMP 接受 date，拒绝字符串和带时区时间 | [test_mysql_timestamp_accepts_date_and_rejects_invalid_input](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L688) |
| KB-TYPE-017 | MySQL 模式覆盖数值、字符、二进制、日期时间、JSON、BIT | [test_mysql_common_type_matrix_round_trips_values](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L727) |
| KB-TYPE-018 | Oracle 模式覆盖 NUMBER、CHAR、LOB、BLOB、时区和 INTERVAL | [test_oracle_common_type_matrix_round_trips_values](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L776) |
| KB-TYPE-019 | SQL Server 模式覆盖数值、Unicode、日期时间、UUID 和二进制类型 | [test_sqlserver_common_type_matrix_round_trips_values](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L852) |
| KB-TYPE-020 | 临时业务数据库中的 ROWVERSION 返回 8 字节并随更新变化 | [test_sqlserver_rowversion_database_support](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L904) |
| KB-TYPE-022 | MySQL 无符号整数边界、ENUM/SET 及含零字节二进制类型正常 | [test_mysql_unsigned_enum_set_and_binary_types_round_trip](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L951) |
| KB-TYPE-023 | Oracle ROWID/UROWID、BFILE、BLOB 和本地时区时间戳正常 | [test_oracle_rowid_bfile_and_local_timestamp_types_round_trip](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L1036) |
| KB-TYPE-025 | Oracle INTERVAL 编解码、READ COMMITTED 和 SERIALIZABLE 事务 | [test_oracle_types_and_supported_transaction_isolation](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L1126) |
| KB-TYPE-026 | 三模式只读事务在支持的隔离级别下拒绝写入，回滚后连接可复用 | [test_supported_readonly_transactions_reject_writes_and_recover](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L1164) |
| KB-TYPE-027 | 三模式约束及 SQL 错误映射准确，报错后连接可立即复用 | [test_server_errors_map_to_driver_subclasses_and_preserve_connection](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L1202) |
| KB-TYPE-030 | Schema cache reload 和 statement TTL 到期后 KES codec 仍可用 | [test_schema_reload_and_statement_expiry_preserve_kes_codecs](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L1284) |
| KB-TYPE-031 | MySQL TIME/DATETIME codec 保留小数秒并支持超过 24 小时 | [test_mysql_fractional_datetime_codecs_preserve_precision_and_duration](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L1326) |
| KB-TYPE-032 | SQL Server DATETIME2(7) 截取为 Python 六位微秒精度 | [test_sqlserver_datetime2_default_precision_decodes_to_microseconds](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L1348) |
| KB-TYPE-033 | KES 标量 codec 拒绝文本、二进制和时区值的静默转换 | [test_kes_scalar_encoders_reject_silent_python_coercions](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L1358) |
| KB-TYPE-035 | 日期时间 codec 处理无穷值、越界值和 tuple 边界 | [test_kes_temporal_codecs_cover_infinity_range_and_shape_boundaries](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L1391) |
| KB-TYPE-036 | 标量 codec 覆盖布尔假值、BIT、数值、UUID 和非法输入 | [test_kes_scalar_codecs_cover_false_hex_numeric_and_uuid_boundaries](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L1452) |
| KB-TYPE-038 | Codec 注册使用服务端发现的 OID，模式标记缺失时不注册 | [test_codec_registration_uses_discovered_oids_and_rejects_missing_markers](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L1483) |
| KB-TYPE-041 | 执行阶段文本结果描述仍保持数值、二进制等正确 Python 类型 | [test_sqlserver_execution_row_descriptions_preserve_python_types](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L1598) |
| KB-TYPE-042 | 新版 SQL Server 原生类型往返、真实类型元信息和重置 Codec 后的默认行为 | [test_sqlserver_native_scalar_types_round_trip_and_reset](../../tests/kes/types_and_codecs/test_types_and_codecs.py#L1636) |

## 查询执行、事务与语句资源（42 个测试点）

| 编号 | 测试点 | 代码位置 |
| --- | --- | --- |
| KB-EXEC-004 | 预编译单值/单行和 Cursor 异步迭代、事务及预取边界正常 | [test_prepared_single_result_and_cursor_iteration_contracts](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L57) |
| KB-EXEC-005 | 活动查询期间优雅关闭和强制终止返回明确且不同的异常 | [test_active_query_close_and_terminate_report_distinct_failures](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L123) |
| KB-EXEC-006 | 同一连接并发执行被拒绝，取消首个命令后连接仍可复用 | [test_concurrent_connection_operation_is_rejected_then_connection_recovers](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L154) |
| KB-EXEC-007 | 批处理中途约束失败会整体回滚，且同一连接可以继续使用 | [test_executemany_server_error_is_atomic_and_connection_is_reusable](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L186) |
| KB-EXEC-008 | 客户端批处理迭代器中途失败不会留下部分写入 | [test_executemany_client_iterator_failure_is_atomic](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L224) |
| KB-EXEC-010 | statement cache 可关闭，且超长 SQL 不进入配置容量内的缓存 | [test_statement_cache_disable_and_query_size_limit](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L261) |
| KB-EXEC-013 | DEALLOCATE 单条和 ALL 后旧对象失效、同名对象可重新准备 | [test_mysql_manual_deallocate_allows_reprepare](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L306) |
| KB-EXEC-014 | 旧 named statement 被 GC 时不能误关闭同名的新 statement | [test_mysql_old_statement_gc_does_not_close_replacement](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L338) |
| KB-EXEC-015 | 三模式重复名称必须报错，且原 statement 仍可执行 | [test_duplicate_named_statement_is_rejected_without_replacing_original](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L365) |
| KB-EXEC-016 | 多语句或尾注释 DEALLOCATE 后，三模式同名重建和 GC 正常 | [test_named_statement_recovers_when_deallocate_is_not_a_standalone_command](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L396) |
| KB-EXEC-017 | 多语句错误保留 KES 模式自身的 DDL 原子性语义 | [test_execute_script_error_preserves_mode_specific_ddl_atomicity](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L444) |
| KB-EXEC-018 | 三模式带参数 execute 拒绝多命令且不执行前置 DDL | [test_parameterized_execute_rejects_multiple_commands_before_execution](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L474) |
| KB-EXEC-020 | 三模式显式 IN、INOUT、OUT 方向绑定；重复、NULL、批量与 SQL Server EXEC 调用 | [test_kes_explicit_parameter_directions](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L510) |
| KB-EXEC-022 | 非法参数方向或参数个数在执行前拒绝，不产生 DML 副作用 | [test_kes_invalid_parameter_directions_do_not_execute](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L585) |
| KB-EXEC-023 | Oracle 输出参数数值、时间、NULL 编解码及零行、多行异常后的恢复 | [test_oracle_returning_into_temporal_numeric_and_zero_rows](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L615) |
| KB-EXEC-024 | 当前 Oracle 实例拒绝独立 SQL 的 RETURNING INTO，普通 RETURNING 仍返回数据 | [test_oracle_standalone_returning_into_is_server_restriction](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L676) |
| KB-EXEC-026 | 混合 IN/OUT/IN OUT 参数通过 fetch 和批量接口返回结果行 | [test_oracle_call_returns_out_and_inout_parameters](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L709) |
| KB-EXEC-027 | 纯 OUT 返回、命名语句、事务回滚及调用失败后的连接恢复 | [test_oracle_call_pure_out_parameters_and_transaction_recovery](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L764) |
| KB-EXEC-028 | 多个结果集的行合并返回，各行保留列名，但不保留集合边界 | [test_oracle_call_returns_multiple_result_sets](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L819) |
| KB-EXEC-029 | OUT SYS_REFCURSOR 返回匿名 portal 名，可在事务内 FETCH | [test_oracle_refcursor_anonymous_portal_can_be_fetched](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L870) |
| KB-EXEC-030 | SQL Server 绑定参数 CALL／EXEC 嵌套过程返回行与输入值核对，不承诺结果集边界 | [test_sqlserver_bound_nested_procedure_result_sets](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L909) |
| KB-EXEC-031 | SQL Server 带参数多语句查询，由服务端推导类型并核对结果行 | [test_sqlserver_bound_multistatement_select](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L965) |
| KB-EXEC-032 | SQL Server 带参数批次的命令状态、数据变更、NULL 与事务回滚 | [test_sqlserver_bound_multistatement_dml_and_rollback](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L1010) |
| KB-EXEC-033 | SQL Server 批次内字符串中的占位符文本不计为绑定位置 | [test_sqlserver_bound_batch_ignores_placeholder_text_in_strings](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L1058) |
| KB-EXEC-034 | SQL Server 事务内捕获批次错误后，批次仍保持原子性且连接可复用 | [test_sqlserver_batch_error_caught_inside_transaction_is_atomic](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L1087) |
| KB-EXEC-035 | prepared statement 的 fetchval/fetchrow 行限制调用保持状态正确 | [test_mysql_prepared_statement_row_limit_does_not_corrupt_status](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L1135) |
| KB-EXEC-036 | Oracle prepared INSERT RETURNING、fetchmany、游标和核心类型元数据 | [test_oracle_prepared_statement_cursor_and_returning_support](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L1158) |
| KB-EXEC-039 | 异步单连接完整执行新增、查询、更新和删除并返回正确状态 | [test_async_connection_crud_round_trip](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L1231) |
| KB-EXEC-042 | 异步事务中的业务异常自动回滚且同一连接可继续提交 | [test_async_transaction_exception_rolls_back_and_recovers](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L1299) |
| KB-EXEC-043 | 取消异步事务任务会回滚数据并及时归还连接池槽位 | [test_cancelled_async_transaction_rolls_back_and_releases_pool_slot](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L1341) |
| KB-EXEC-045 | 三模式复用 PG 事务选项，且不改变下一事务的默认设置 | [test_transaction_options_are_scoped_to_the_pg_transaction](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L1389) |
| KB-EXEC-046 | 三模式复用 PG 保存点，内层回滚和外层提交的数据正确 | [test_nested_transactions_reuse_pg_savepoint_commands](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L1421) |
| KB-EXEC-047 | 双连接并发提交后，读取结果符合指定的事务隔离级别 | [test_transaction_isolation_controls_visibility_of_concurrent_commits](../../tests/kes/execution_transactions_statements/test_execution_transactions_statements.py#L1500) |
| KB-EXEC-049 | ZIP 原始分号和空格两种多 SELECT 写法，经简单协议和 PBE 执行 | [test_zip_original_two_select_forms](../../tests/kes/procedures_and_results/test_multiple_results.py#L16) |
| KB-EXEC-050 | 原始 SET NOCOUNT ON/OFF 是否被当前 KES 语法接受 | [test_zip_original_nocount_syntax](../../tests/kes/procedures_and_results/test_multiple_results.py#L41) |
| KB-EXEC-051 | NOCOUNT 的 KES 可用写法下，多 INSERT/UPDATE 的真实表数据和连接恢复 | [test_zip_dml_with_supported_nocount_setting](../../tests/kes/procedures_and_results/test_multiple_results.py#L65) |
| KB-EXEC-052 | fetch 合并返回行，不表示能保留空结果集或通过 nextset 遍历 | [test_empty_result_boundary_is_not_exposed](../../tests/kes/procedures_and_results/test_multiple_results.py#L115) |
| KB-EXEC-053 | 三模式纯 OUT、NULL、重复执行和批量返回不依赖过程查询结果集 | [test_pure_out_parameters_without_query_result_sets](../../tests/kes/procedures_and_results/test_procedures.py#L14) |
| KB-EXEC-054 | 普通 DML 在匿名块内输出绑定值，并核对真实表数据与回滚 | [test_oracle_returning_into_output_and_table_state](../../tests/kes/procedures_and_results/test_procedures.py#L63) |
| KB-EXEC-055 | 区分三模式函数 SELECT/CALL 的绑定输入、返回值、NULL 与重复执行 | [test_scalar_function_input_null_and_repeated_calls](../../tests/kes/procedures_and_results/test_procedures.py#L114) |
| KB-EXEC-056 | 同一次过程调用既返回多组查询行，也返回 INOUT 和 OUT 值 | [test_output_parameters_together_with_multiple_result_rows](../../tests/kes/procedures_and_results/test_procedures.py#L178) |
| KB-EXEC-057 | MySQL 内外层过程返回不同列数和类型时，行序与字段不丢失 | [test_mysql_nested_procedure_multiple_results](../../tests/kes/procedures_and_results/test_procedures.py#L249) |

## 连接池（13 个测试点）

| 编号 | 测试点 | 代码位置 |
| --- | --- | --- |
| KB-POOL-005 | Pool 释放时回滚事务，过期重连后重新注册 KES codec | [test_pool_release_rolls_back_transaction_and_reloads_kes_codecs](../../tests/kes/pool/test_pool.py#L34) |
| KB-POOL-006 | Pool init/setup/reset 生命周期顺序正确且连接保持 KES 模式 | [test_pool_callbacks_run_in_order_and_preserve_kes_mode](../../tests/kes/pool/test_pool.py#L97) |
| KB-POOL-007 | Pool 部分初始化失败时关闭所有已建立的 KES 连接 | [test_pool_partial_initialization_failure_closes_kes_connections](../../tests/kes/pool/test_pool.py#L146) |
| KB-POOL-009 | Pool setup 回调失败后丢弃连接，下一次 acquire 可恢复 | [test_pool_setup_callback_failure_discards_connection_and_recovers](../../tests/kes/pool/test_pool.py#L187) |
| KB-POOL-010 | Pool reset 回调失败后终止连接，下一次 acquire 可恢复 | [test_pool_reset_callback_failure_discards_connection_and_recovers](../../tests/kes/pool/test_pool.py#L233) |
| KB-POOL-013 | Pool 按查询数和空闲时间回收后，新连接重新注册 KES codec | [test_pool_query_and_idle_recycling_reload_kes_codecs](../../tests/kes/pool/test_pool.py#L283) |
| KB-POOL-016 | Pool 批处理代理、容量统计、获取超时、并发排队和关闭状态正常 | [test_pool_batch_capacity_timeout_and_shutdown_contracts](../../tests/kes/pool/test_pool.py#L352) |
| KB-POOL-017 | 等待连接的任务被取消后不占用 holder，连接池容量可立即恢复 | [test_cancelled_pool_waiter_does_not_consume_capacity](../../tests/kes/pool/test_pool.py#L441) |
| KB-POOL-019 | release 调用被取消时，受保护的 reset 仍完成并归还连接 | [test_cancelled_pool_release_still_returns_connection](../../tests/kes/pool/test_pool.py#L476) |
| KB-POOL-020 | Pool 归还刚取消查询的连接时等待协议清理，随后可正常复用 | [test_pool_release_waits_for_query_cancellation_and_connection_recovers](../../tests/kes/pool/test_pool.py#L518) |
| KB-POOL-021 | Pool.close 等待借出连接归还，关闭期间拒绝新的 acquire | [test_pool_close_waits_for_checked_out_connection](../../tests/kes/pool/test_pool.py#L554) |
| KB-POOL-023 | 空闲物理连接被服务端终止后，原生 Pool 自动建立新连接 | [test_idle_pool_connection_terminated_by_server_is_replaced](../../tests/kes/pool/test_pool.py#L589) |
| KB-POOL-025 | Pool 容量、生命周期及扩展类型非法边界在建连前失败 | [test_pool_configuration_boundaries_fail_before_connecting](../../tests/kes/pool/test_pool.py#L673) |

## SQLAlchemy 方言（20 个测试点）

| 编号 | 测试点 | 代码位置 |
| --- | --- | --- |
| KB-SA-001 | SQL Server 列反射基于当前系统目录，不依赖已删除的 information_schema 字段 | [test_sqlserver_native_column_types_reflect_from_catalog](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L20) |
| KB-SA-002 | 统一 URL 自动加载模式方言并使用 asynckb 参数绑定 | [test_sqlalchemy_unified_url_detects_and_loads_mode_dialect](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L79) |
| KB-SA-004 | 三模式 async engine 支持 URL 中的 SSL、缓存和超时连接参数 | [test_sqlalchemy_url_options_connect_in_all_kes_modes](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L127) |
| KB-SA-006 | 三模式方言在 AUTOCOMMIT 下可跳过无效的连接归还回滚 | [test_sqlalchemy_autocommit_detection_in_all_kes_modes](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L163) |
| KB-SA-008 | 三模式 get_isolation_level 返回 KES 会话实际隔离级别 | [test_sqlalchemy_reports_server_session_isolation_level](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L193) |
| KB-SA-009 | 三模式连接被服务端终止后 pool_pre_ping 自动建立新连接 | [test_sqlalchemy_pool_pre_ping_replaces_terminated_connections](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L225) |
| KB-SA-010 | 三模式 DEALLOCATE ALL 后 SQLAlchemy 和 asynckb 缓存同步重建 | [test_sqlalchemy_deallocate_all_invalidates_both_statement_caches](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L272) |
| KB-SA-011 | 三模式方言支持视图发现、定义、查询和 SQLAlchemy 2 批量反射 | [test_sqlalchemy_views_and_multi_reflection_in_all_kes_modes](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L317) |
| KB-SA-012 | 三模式 quoted 标识符完整反射且 SQLAlchemy 保存点可提交回滚 | [test_sqlalchemy_quoted_identifiers_and_nested_transactions](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L396) |
| KB-SA-013 | MySQL 方言覆盖建表、插入、upsert、分页、流式读取和完整反射 | [test_sqlalchemy_mysql_crud_and_catalog_reflection](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L566) |
| KB-SA-014 | SQL Server 方言覆盖 identity、CRUD、流读取及完整目录反射 | [test_sqlalchemy_sqlserver_crud_and_catalog_reflection](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L754) |
| KB-SA-015 | Oracle 方言覆盖 identity、sequence、RETURNING、computed 和反射 | [test_sqlalchemy_oracle_crud_stream_and_catalog_reflection](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L908) |
| KB-SA-016 | Oracle CHAR/NCHAR 反射使用有效长度，不返回 KES 的零值 | [test_sqlalchemy_oracle_character_lengths_use_kes_data_length](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L1094) |
| KB-SA-017 | Oracle 方言可发现其他用户 Schema，并反射、查询其表 | [test_sqlalchemy_oracle_can_reflect_and_query_another_owner](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L1140) |
| KB-SA-018 | Oracle mixed-case quoted 用户按精确 owner 反射自身对象 | [test_sqlalchemy_oracle_quoted_user_reflects_its_default_owner](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L1239) |
| KB-SA-020 | 三模式 SQLAlchemy executemany 失败可回滚并继续查询 | [test_sqlalchemy_executemany_failure_rolls_back_and_recovers](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L1349) |
| KB-SA-021 | 三模式 schema、物化视图和不存在对象反射语义明确 | [test_sqlalchemy_catalog_boundaries_in_all_kes_modes](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L1397) |
| KB-SA-024 | SQLAlchemy URL 的 SSL、缓存、超时和多主机参数正确传给 asynckb | [test_sqlalchemy_connection_url_options_are_normalized](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L1454) |
| KB-SA-029 | SQLAlchemy URL 拒绝缺 host/port 和 SSL 参数冲突 | [test_sqlalchemy_connection_url_rejects_incomplete_or_conflicting_options](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L1500) |
| KB-SA-030 | SQLAlchemy 执行 named DEALLOCATE 同步关闭两层语句缓存 | [test_sqlalchemy_adapter_named_deallocate_updates_both_caches](../../tests/kes/sqlalchemy_dialect/test_sqlalchemy_dialect.py#L1545) |

## 用户认证（15 个测试点）

| 编号 | 测试点 | 代码位置 |
| --- | --- | --- |
| KB-AUTH-002 | 实际算法与 HBA/密码存储组合一致，重复登录和查询正常 | [test_password_method_and_repeat_connection](../../tests/kes/authentication/test_authentication.py#L31) |
| KB-AUTH-003 | 错误、缺失和空密码不能绕过真实密码校验 | [test_password_methods_reject_invalid_credentials](../../tests/kes/authentication/test_authentication.py#L55) |
| KB-AUTH-004 | HBA reject 规则优先于正确凭证，不能建立会话 | [test_reject_rule_refuses_valid_password](../../tests/kes/authentication/test_authentication.py#L81) |
| KB-AUTH-005 | 明确配置的 trust 不发送密码挑战，不误计为密码认证成功 | [test_trust_does_not_request_password](../../tests/kes/authentication/test_authentication.py#L98) |
| KB-AUTH-006 | 同步/异步密码回调参与真实认证且每条连接调用一次 | [test_password_callback](../../tests/kes/authentication/test_authentication.py#L119) |
| KB-AUTH-007 | 密码文件转义后的特殊字符/Unicode 密码仍能通过认证 | [test_password_file](../../tests/kes/authentication/test_authentication.py#L150) |
| KB-AUTH-008 | 并发池连接及过期后的新连接分别完成真实身份认证 | [test_pool_reauthenticates_new_connections](../../tests/kes/authentication/test_authentication.py#L180) |
| KB-AUTH-009 | 真实 KES 交换中的伪造签名、错误 nonce 和未知机制被拒绝 | [test_scram_refuses_invalid_server_authentication](../../tests/kes/authentication/test_authentication.py#L215) |
| KB-AUTH-010 | 真实 KES 转发密码至本机 LDAP/RADIUS，正确放行、错误拒绝 | [test_external_password_service](../../tests/kes/authentication/test_external_authentication.py#L88) |
| KB-AUTH-011 | TLS CA/CN 校验通过后 cert 登录成功，缺证书/错误身份拒绝 | [test_certificate_identity](../../tests/kes/authentication/test_external_authentication.py#L141) |
| KB-AUTH-012 | Unix socket 使用操作系统身份校验，不依赖数据库密码 | [test_peer_identity](../../tests/kes/authentication/test_external_authentication.py#L176) |
| KB-AUTH-015 | 真实 TCP ident 服务返回身份，匹配放行，不匹配拒绝 | [test_ident_server](../../tests/kes/authentication/test_external_authentication.py#L218) |
| KB-AUTH-017 | 服务端验证实际上传的本地接口 MAC，匹配放行、不匹配拒绝 | [test_server_validates_uploaded_loopback_mac](../../tests/kes/authentication/test_mac.py#L15) |
| KB-AUTH-022 | 实际出站接口的 MAC 与内核 sysfs 一致，不误取回环地址 | [test_routed_interface_matches_operating_system](../../tests/kes/authentication/test_mac_address.py#L17) |
| KB-AUTH-023 | sso MAC 白名单匹配才放行，且不能绕过后续密码认证 | [test_limited_info_mac_whitelist](../../tests/kes/authentication/test_mac_whitelist.py#L15) |
