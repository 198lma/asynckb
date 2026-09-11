.. _asyncpg-kes-user-manual-zh:

asyncpg-kes 用户手册
====================

文档信息
--------

.. list-table::
   :widths: 24 76
   :header-rows: 1

   * - 项目
     - 内容
   * - 产品名称
     - asyncpg-kes
   * - 文档版本
     - 0.31.0.post12
   * - 适用数据库
     - KingbaseES V009R001C010 MySQL、Oracle、SQL Server 兼容模式
   * - Python 版本
     - CPython 3.9 至 3.14
   * - 目标读者
     - Python 开发人员、测试人员、数据库管理员和运维人员

本文档说明如何安装、配置和使用 asyncpg-kes。文档中的 MySQL、Oracle 和
SQL Server 均表示 **KingbaseES 对应兼容模式**，不是连接官方 MySQL、Oracle
或 Microsoft SQL Server 数据库。

产品说明
--------

asyncpg-kes 是在 asyncpg 0.31.0 基础上适配 KingbaseES 三种兼容模式的异步
Python 驱动。安装包名称是 ``asyncpg-kes``，Python 导入名仍然是
``asyncpg``。应用通过 PostgreSQL Wire Protocol 与 KingbaseES 通信，不依赖
``libkci``、ksycopg2 或官方 MySQL、Oracle、SQL Server 驱动。

运行链路如下：

.. code-block:: text

   asyncio 应用 / SQLAlchemy AsyncEngine
       -> asyncpg Connection / Pool
       -> Cython 协议与 codec
       -> PostgreSQL Wire Protocol
       -> KingbaseES 兼容模式实例

驱动保留了 asyncpg 的连接、预编译语句、游标、事务、连接池、COPY、通知、
自定义 codec 和异常体系。用户可以继续使用原 asyncpg 的连接 URL 和参数；连接
认证成功后，驱动会在内部执行 ``SHOW DATABASE_MODE``，自动识别 KES MySQL、
Oracle 或 SQL Server 兼容模式，并初始化对应 Codec。普通 PostgreSQL 不支持该
命令时会自动回退到原 PostgreSQL 路径。``kes_mode`` 仍可作为可选的显式模式校验
参数保留，但正常使用不需要手动配置。

环境准备
--------

运行环境
~~~~~~~~

* CPython 3.9 至 3.14；不支持 Python 3.8 及更早版本。
* 可访问的 KingbaseES MySQL、Oracle 或 SQL Server 兼容模式实例。
* 数据库用户应具有连接目标数据库以及执行业务 SQL 所需的权限。
* 从源码构建时需要 C 编译器、Python 开发头文件和 Cython。
* 使用 SQLAlchemy 时需要 SQLAlchemy 2.x；使用 Alembic 时建议 Alembic 1.13
  或更高版本。

以下端口是本项目测试环境的默认值，不是所有 KingbaseES 安装的固定端口：

.. list-table:: KES 模式配置速查
   :widths: 18 18 20 44
   :header-rows: 1

   * - KES 模式
     - ``kes_mode``
     - 测试默认端口
     - SQLAlchemy URL 前缀
   * - MySQL 兼容模式
     - ``mysql``
     - ``54321``
     - ``kingbase_mysql+asyncpg``
   * - Oracle 兼容模式
     - ``oracle``
     - ``54322``
     - ``kingbase_oracle+asyncpg``
   * - SQL Server 兼容模式
     - ``sqlserver``
     - ``54323``
     - ``kingbase_sqlserver+asyncpg``

本文档中的终端截图来自 KingbaseES V009R001C010 本地三模式实例的实际执行
结果。密码均以 ``***`` 脱敏，临时路径经过简化；端口、账号和数据库名仍应以
实际交付环境为准。

数据库准备
~~~~~~~~~~

使用前应向数据库管理员确认以下信息：

* 数据库服务器地址和实际端口；
* 数据库名、用户名和密码；
* 实例的兼容模式；
* 是否启用 TLS，以及 CA、客户端证书和私钥位置；
* 应用使用默认 schema，还是预先创建的业务 schema。

不指定 schema 时，对象创建在当前用户的默认 schema。若使用 ``asynckes``
schema，应先由有权限的账号创建并授权。应用 SQL 中可以使用
``asynckes.table_name`` 这样的限定名称。

安装与升级
----------

使用 wheel 安装
~~~~~~~~~~~~~~~~~~~~

推荐在独立虚拟环境中安装发布的 wheel：

.. code-block:: bash

   python -m pip uninstall -y asyncpg asyncpg-kes
   python -m pip install /path/to/asyncpg_kes-0.31.0.post12-*.whl

``asyncpg`` 和 ``asyncpg-kes`` 都提供名为 ``asyncpg`` 的 Python 包，不能在
同一个环境中同时安装。安装后执行：

.. code-block:: bash

   python -c "import asyncpg; print(asyncpg.__version__, asyncpg.__file__)"
   python -m pip show asyncpg-kes

输出版本应为 ``0.31.0.post12``，文件路径应位于当前环境的
``site-packages/asyncpg``，而不是源码目录。

.. figure:: _static/user-manual/01-wheel-installation.png
   :width: 96%
   :align: center
   :alt: asyncpg-kes wheel 安装与导入验证终端截图

   图 1：从 wheel 安装 asyncpg-kes，并在源码目录外验证版本、导入位置、
   三种 KES 模式和 ``connect`` API。

安装可选功能
~~~~~~~~~~~~

.. code-block:: bash

   # SQLAlchemy 异步方言
   python -m pip install 'asyncpg-kes[sqlalchemy]'

   # SQLAlchemy 和 Alembic
   python -m pip install 'asyncpg-kes[alembic]'

   # GSSAPI/SSPI 认证
   python -m pip install 'asyncpg-kes[gssauth]'

从源码构建
~~~~~~~~~~

在 Linux 上先安装编译环境。Debian/Ubuntu 示例：

.. code-block:: bash

   sudo apt install build-essential python3-dev
   python -m pip install --upgrade pip build
   python -m build --wheel

构建结果位于 ``dist/``。交付前必须在源码目录外创建干净环境安装 wheel，并
确认 ``asyncpg.connect``、版本信息和 SQLAlchemy entry point 均存在。不要只
使用 ``pip install -e .`` 验证发布包，因为 editable 安装会直接读取源码。

快速开始
--------

建立连接
~~~~~~~~

下面示例使用原 asyncpg 连接方式。驱动认证后会自动识别 KES 兼容模式；请替换
主机、端口、用户、密码和数据库名：

.. code-block:: python

   import asyncio
   import asyncpg


   async def main():
       connection = await asyncpg.connect(
           host="127.0.0.1",
           port=54321,
           user="system",
           password="your-password",
           database="test",
           ssl=False,
           timeout=5,
           command_timeout=30,
       )
       try:
           value = await connection.fetchval("SELECT 1")
           print(value, connection.get_kes_mode())
       finally:
           await connection.close()


   asyncio.run(main())

连接 MySQL、Oracle 或 SQL Server 兼容模式时不需要手动传入 ``kes_mode``，驱动会
自动执行 ``SHOW DATABASE_MODE`` 并初始化对应适配。Oracle 模式的连通性 SQL
建议使用 ``SELECT 1 FROM dual``。``kes_mode`` 仍可用于需要显式校验的场景。

.. figure:: _static/user-manual/02-three-mode-connectivity.png
   :width: 96%
   :align: center
   :alt: KingbaseES MySQL Oracle SQL Server 三模式连通性截图

   图 2：同一个 asyncpg-kes wheel 分别连接 KingbaseES MySQL、Oracle 和
   SQL Server 兼容模式，驱动模式校验与连通性查询均成功。

使用 DSN
~~~~~~~~

原生 asyncpg DSN 继续使用 ``postgresql://`` 协议名，因为底层仍是 PostgreSQL
Wire Protocol：

.. code-block:: python

   connection = await asyncpg.connect(
       "postgresql://system:your-password@127.0.0.1:54321/test"
       "?kes_mode=mysql&sslmode=disable"
   )

用户名、密码和数据库名含特殊字符时必须进行 URL 编码。关键字参数会覆盖 DSN
中的同名配置。不要把密码写入源码或提交到版本库。

使用服务文件
~~~~~~~~~~~~

``pg_service.conf`` 示例：

.. code-block:: ini

   [kes_mysql]
   host=127.0.0.1
   port=54321
   user=system
   dbname=test
   sslmode=disable
   kes_mode=mysql

连接代码：

.. code-block:: python

   connection = await asyncpg.connect(
       service="kes_mysql",
       servicefile="/path/to/pg_service.conf",
   )

也可以使用 ``PGSERVICE`` 和 ``PGSERVICEFILE`` 环境变量。显式传入的
``kes_mode`` 优先于服务文件。

连接参数
--------

.. list-table:: 常用连接参数
   :widths: 28 72
   :header-rows: 1

   * - 参数
     - 说明
   * - ``host`` / ``port``
     - 主机和端口；可以传入等长序列实现多地址连接。
   * - ``user`` / ``password`` / ``database``
     - 认证用户、密码和目标数据库；密码也可以是同步或异步回调。
   * - ``kes_mode``
     - ``mysql``、``oracle`` 或 ``sqlserver``；必须与服务端模式一致。
   * - ``timeout``
     - 建立连接和协议握手的超时时间，默认 60 秒。
   * - ``command_timeout``
     - 该连接上数据库操作的默认超时时间；默认不限制。
   * - ``statement_cache_size``
     - 预编译语句 LRU 缓存大小，默认 100；传 ``0`` 禁用。
   * - ``max_cached_statement_lifetime``
     - 缓存语句最大存活秒数，默认 300；传 ``0`` 表示不按时间过期。
   * - ``max_cacheable_statement_size``
     - 可缓存 SQL 的最大字节数，默认 15 KiB；传 ``0`` 不限制。
   * - ``ssl``
     - ``False``、``True``、SSLContext，或 ``disable``、``prefer``、
       ``allow``、``require``、``verify-ca``、``verify-full``。
   * - ``direct_tls``
     - 直接开始 TLS，不执行 PostgreSQL STARTTLS；必须配合 ``ssl``。
   * - ``server_settings``
     - 建立会话时传入服务端运行参数；只使用当前 KES 模式支持的参数。
   * - ``target_session_attrs``
     - 多主机时选择 ``primary``、``standby``、``read-write``、
       ``read-only``、``prefer-standby`` 或 ``any``。
   * - ``connection_class`` / ``record_class``
     - 自定义 Connection 和 Record 子类。

使用 ``ssl=False`` 只适合可信测试网络。生产环境应根据证书体系配置
``verify-ca`` 或 ``verify-full``。

SQL 与参数绑定
--------------

asyncpg-kes 使用 ``$1``、``$2`` 形式的位置参数。参数绑定只用于数据值，不能
用于表名、列名或 SQL 关键字。

.. code-block:: python

   row = await connection.fetchrow(
       "SELECT id, username FROM app_user WHERE id = $1", 1
   )

不要使用字符串拼接处理外部输入：

.. code-block:: python

   # 错误：存在 SQL 注入风险
   sql = f"SELECT * FROM app_user WHERE username = '{username}'"

   # 正确：值通过协议参数发送
   row = await connection.fetchrow(
       "SELECT * FROM app_user WHERE username = $1", username
   )

传给原生 asyncpg API 的 SQL **不会被跨模式翻译**。应用必须使用当前 KES 模式
支持的 SQL 语法。例如 Oracle 常用 ``NUMBER``、``VARCHAR2`` 和 ``dual``，
MySQL、SQL Server 模式常用 ``INT``、``VARCHAR``。MySQL 模式在部分表达式中会
把无类型参数推断为 ``text``，遇到类型推断错误时应显式写
``CAST($1 AS SIGNED)`` 或目标类型。

CRUD 操作
---------

核心查询方法
~~~~~~~~~~~~

.. list-table:: Connection 数据操作 API
   :widths: 24 76
   :header-rows: 1

   * - 方法
     - 用途和返回值
   * - ``execute()``
     - 执行命令，返回 ``INSERT 0 1``、``UPDATE 1`` 等状态字符串。
   * - ``executemany()``
     - 对多组参数执行同一命令，成功返回 ``None``；作为原子批次执行。
   * - ``fetch()``
     - 返回由 ``asyncpg.Record`` 组成的列表。
   * - ``fetchrow()``
     - 返回第一行 ``Record``，没有结果时返回 ``None``。
   * - ``fetchval()``
     - 返回第一行指定列的值，默认第 0 列。
   * - ``prepare()``
     - 显式创建 PreparedStatement，适合重复执行和读取参数/列元数据。

完整异步 CRUD 示例
~~~~~~~~~~~~~~~~~~

下面的建表 SQL 按模式选择，其他 CRUD 代码保持一致：

.. code-block:: python

   import asyncio
   import asyncpg


   SETTINGS = {
       "host": "127.0.0.1",
       "user": "system",
       "password": "your-password",
       "database": "test",
       "ssl": False,
   }


   async def drop_table(connection, table):
       try:
           await connection.execute(f"DROP TABLE {table}")
       except asyncpg.UndefinedTableError:
           pass


   async def run(mode: str, port: int):
       connection = await asyncpg.connect(
           **SETTINGS, port=port, kes_mode=mode
       )
       table = "asyncpg_kes_user_demo"
       columns = (
           "id NUMBER(10) PRIMARY KEY, "
           "username VARCHAR2(50) NOT NULL UNIQUE, age NUMBER(3)"
           if mode == "oracle"
           else
           "id INT PRIMARY KEY, "
           "username VARCHAR(50) NOT NULL UNIQUE, age INT"
       )
       try:
           await drop_table(connection, table)
           await connection.execute(f"CREATE TABLE {table} ({columns})")

           await connection.execute(
               f"INSERT INTO {table} VALUES ($1, $2, $3)",
               1, "alice", 24,
           )
           await connection.executemany(
               f"INSERT INTO {table} VALUES ($1, $2, $3)",
               [(2, "bob", 30), (3, "carol", 36)],
           )

           row = await connection.fetchrow(
               f"SELECT id, username, age FROM {table} WHERE id = $1", 1
           )
           print(dict(row))

           await connection.execute(
               f"UPDATE {table} SET age = $1 WHERE id = $2", 31, 2
           )
           count = await connection.fetchval(f"SELECT count(*) FROM {table}")
           print("rows:", count)

           await connection.execute(
               f"DELETE FROM {table} WHERE id = $1", 3
           )
       finally:
           await drop_table(connection, table)
           await connection.close()


   asyncio.run(run("mysql", 54321))

示例通过捕获 ``asyncpg.UndefinedTableError`` 兼容三个模式的清理行为。业务程序
不应在每次启动时重复建表和删表，生产 DDL 应由经过审查的迁移脚本统一管理。

.. figure:: _static/user-manual/03-async-crud.png
   :width: 96%
   :align: center
   :alt: asyncpg-kes 三模式异步 CRUD 执行截图

   图 3：三种 KES 兼容模式执行异步建表、插入、批量插入、查询、更新和删除；
   Oracle ``NUMBER`` 按驱动类型映射返回 ``Decimal``。

Record 使用方式
~~~~~~~~~~~~~~~

``Record`` 同时支持索引、列名、迭代和转换为字典：

.. code-block:: python

   row = await connection.fetchrow("SELECT id, username FROM app_user")
   print(row[0])
   print(row["username"])
   print(tuple(row))
   print(dict(row))

字段访问推荐使用 ``row["column"]``。Record 默认不提供
``row.column`` 点号访问；需要时可以通过 ``record_class`` 自定义。

预编译语句与游标
----------------

预编译语句
~~~~~~~~~~

.. code-block:: python

   statement = await connection.prepare(
       "SELECT username, age FROM app_user WHERE id = $1"
   )
   row = await statement.fetchrow(1)
   name = await statement.fetchval(1, column=0)
   print(row, name)

Connection 会自动缓存常用参数化语句。数据库前置代理若不保持会话级连接，可能
无法支持命名预编译语句，此时设置 ``statement_cache_size=0``，并避免显式
``prepare()``。

游标
~~~~

游标必须在事务内使用：

.. code-block:: python

   async with connection.transaction():
       async for row in connection.cursor(
           "SELECT id, username FROM app_user ORDER BY id",
           prefetch=100,
       ):
           process(row)

游标用于流式读取大量结果。``prefetch`` 越大，网络往返通常越少，但单连接内存
占用也会增加。不要在一个连接上并发推进多个游标。

事务
----

自动提交和回滚
~~~~~~~~~~~~~~

.. code-block:: python

   async with connection.transaction():
       await connection.execute(
           "UPDATE account SET balance = balance - $1 WHERE id = $2",
           100, 1,
       )
       await connection.execute(
           "UPDATE account SET balance = balance + $1 WHERE id = $2",
           100, 2,
       )

代码块正常退出时提交；抛出异常或任务被取消时回滚。事务失败后应让异常离开
``async with`` 块，再继续使用连接。

也可以手动控制：

.. code-block:: python

   transaction = connection.transaction()
   await transaction.start()
   try:
       await connection.execute("INSERT INTO audit_log VALUES ($1)", "ok")
   except Exception:
       await transaction.rollback()
       raise
   else:
       await transaction.commit()

模式差异
~~~~~~~~

.. list-table:: 事务能力边界
   :widths: 20 26 27 27
   :header-rows: 1

   * - 功能
     - MySQL 模式
     - Oracle 模式
     - SQL Server 模式
   * - 开始事务
     - ``START TRANSACTION``
     - ``SET TRANSACTION`` + ``START TRANSACTION``
     - ``BEGIN TRANSACTION``
   * - 常用隔离级别
     - read_uncommitted、read_committed、repeatable_read、serializable
     - read_committed、serializable
     - read_uncommitted、read_committed、repeatable_read、serializable
   * - readonly
     - 支持，最终能力由服务端确认
     - 支持，最终能力由服务端确认
     - 支持，最终能力由服务端确认
   * - deferrable
     - 不支持
     - 不支持
     - 不支持
   * - 嵌套事务
     - SAVEPOINT
     - SAVEPOINT；嵌套提交不发送 RELEASE
     - SAVE TRANSACTION；嵌套提交不发送 RELEASE

Oracle 模式传入 ``read_uncommitted`` 或 ``repeatable_read``，以及任意模式传入
``deferrable=True`` 时，驱动会在执行前抛出
``UnsupportedClientFeatureError``。不同模式的 DDL 事务语义可能不同，不应假设
所有 DDL 都能随外层事务回滚。

连接池
------

创建和使用
~~~~~~~~~~

服务端应用应优先使用 ``create_pool()``：

.. code-block:: python

   import asyncpg


   pool = await asyncpg.create_pool(
       host="127.0.0.1",
       port=54321,
       user="system",
       password="your-password",
       database="test",
       kes_mode="mysql",
       ssl=False,
       min_size=2,
       max_size=10,
       max_queries=50000,
       max_inactive_connection_lifetime=300,
       command_timeout=30,
   )

   try:
       async with pool.acquire(timeout=5) as connection:
           async with connection.transaction():
               await connection.execute(
                   "INSERT INTO app_user VALUES ($1, $2)", 1, "alice"
               )

       count = await pool.fetchval("SELECT count(*) FROM app_user")
   finally:
       await pool.close()

``async with pool.acquire()`` 会在成功、异常和任务取消时归还连接。不要保存并继续
使用已经归还的连接代理。

.. figure:: _static/user-manual/04-transaction-and-pool.png
   :width: 96%
   :align: center
   :alt: asyncpg-kes 事务回滚和异步连接池并发截图

   图 4：事务块抛出异常后插入行数回到 0；六个异步任务通过最大连接数为 3 的
   Pool 并发完成，连接全部归还。

连接池参数
~~~~~~~~~~

.. list-table:: 常用连接池参数
   :widths: 31 69
   :header-rows: 1

   * - 参数
     - 说明
   * - ``min_size`` / ``max_size``
     - 最小和最大连接数，默认都是 10。总连接数应小于数据库为该应用预留的上限。
   * - ``max_queries``
     - 单物理连接执行指定次数后重建，默认 50000。
   * - ``max_inactive_connection_lifetime``
     - 空闲连接最大保留秒数，默认 300；传 0 禁用空闲回收。
   * - ``init``
     - 每个物理连接创建后执行一次，适合注册 codec 或设置固定会话属性。
   * - ``setup``
     - 每次连接借出前执行，适合安装临时 listener。
   * - ``reset``
     - 连接归还前执行；自定义实现仍应执行默认 reset SQL 或等价清理。
   * - ``connect``
     - 自定义建立物理连接的协程，必须返回正确的 Connection 类型。

连接池会在归还连接时回滚未完成事务、清理监听器和会话状态。若服务端终止空闲
连接，下一次借用会创建新连接并重新加载 KES codec。

运行状态
~~~~~~~~

.. code-block:: python

   metrics = {
       "size": pool.get_size(),
       "idle": pool.get_idle_size(),
       "min": pool.get_min_size(),
       "max": pool.get_max_size(),
       "closing": pool.is_closing(),
   }

可监控 ``size - idle`` 作为当前借出数量。持续接近 ``max``、获取连接超时增多或
``close()`` 超过 60 秒，通常表示容量不足、SQL 变慢或连接未及时归还。关闭服务
时建议：

.. code-block:: python

   try:
       await asyncio.wait_for(pool.close(), timeout=30)
   except asyncio.TimeoutError:
       pool.terminate()

异步并发、超时与取消
--------------------

并发原则
~~~~~~~~

一个 Connection 同一时刻只能执行一个数据库操作。多个任务共享一个连接会抛出
``InterfaceError``。并发业务应通过连接池让每个任务借用独立连接：

.. code-block:: python

   async def load_user(user_id):
       async with pool.acquire(timeout=5) as connection:
           return await connection.fetchrow(
               "SELECT id, username FROM app_user WHERE id = $1", user_id
           )


   users = await asyncio.gather(
       *(load_user(user_id) for user_id in range(1, 101))
   )

使用信号量限制应用层瞬时任务数，避免创建远多于连接池容量的等待任务。

超时
~~~~

* ``connect(timeout=...)``：连接与握手超时。
* ``command_timeout``：连接上的默认命令超时。
* 每个 ``execute``、``fetch``、COPY 等 API 的 ``timeout``：覆盖默认命令超时。
* ``pool.acquire(timeout=...)``：等待连接池槽位的超时。
* ``asyncio.wait_for()``：控制一组应用操作的总时限。

.. code-block:: python

   try:
       row = await connection.fetchrow(
           "SELECT id FROM app_user WHERE id = $1",
           1,
           timeout=2,
       )
   except asyncio.TimeoutError:
       # 记录超时并按业务幂等性决定是否重试
       raise

任务取消时驱动会尝试取消服务端命令并恢复连接状态。不要捕获
``asyncio.CancelledError`` 后无条件继续提交事务；应让事务上下文执行回滚。

COPY 批量导入导出
-----------------

asyncpg-kes 保留 asyncpg 的 COPY API，三种 KES 模式均已覆盖 text、CSV 和
binary 路径。常用接口包括：

* ``copy_records_to_table()``：Python 记录批量写表；
* ``copy_to_table()``：从路径、bytes、文件对象或异步数据源导入；
* ``copy_from_table()``：将整表导出到路径、文件对象或异步 sink；
* ``copy_from_query()``：将查询结果导出。

.. code-block:: python

   await connection.copy_records_to_table(
       "import_user",
       records=[(1, "alice"), (2, "bob")],
       columns=["id", "username"],
   )

   await connection.copy_from_query(
       "SELECT id, username FROM import_user ORDER BY id",
       output="/tmp/users.csv",
       format="csv",
       header=True,
   )

   await connection.copy_to_table(
       "import_user_backup",
       source="/tmp/users.csv",
       format="csv",
       header=True,
   )

异步流式传输示例：

.. code-block:: python

   chunks = []

   async def sink(chunk: bytes):
       chunks.append(chunk)

   await connection.copy_from_query(
       "SELECT id, username FROM import_user",
       output=sink,
       format="csv",
   )

   async def source():
       for chunk in chunks:
           yield chunk

   await connection.copy_to_table(
       "import_user_backup", source=source(), format="csv"
   )

COPY 表结构和字段类型必须兼容。失败、超时或取消时，应捕获异常并确认事务状态；
项目测试已覆盖连接恢复和未完成导入的原子性。

LISTEN/NOTIFY
-------------

三种模式可使用 PostgreSQL 协议通知机制：

.. code-block:: python

   event = asyncio.Event()

   def callback(connection, pid, channel, payload):
       print(pid, channel, payload)
       event.set()

   listener = await asyncpg.connect(**settings)
   sender = await asyncpg.connect(**settings)
   try:
       await listener.add_listener("order_changed", callback)
       await sender.execute(
           "SELECT pg_notify($1, $2)", "order_changed", "order-1001"
       )
       await asyncio.wait_for(event.wait(), timeout=5)
       await listener.remove_listener("order_changed", callback)
   finally:
       await listener.close()
       await sender.close()

监听连接应保持独立并持续存活。连接归还到池之前移除 listener，否则驱动会产生
``InterfaceWarning``。通知适合事件提示，不代替需要持久化和确认机制的消息队列。

类型转换与 codec
----------------

驱动连接成功后查询 ``pg_catalog`` 和 ``sys``，按当前实例实际 OID 动态注册 KES
类型，不硬编码某个服务器版本的 OID。常见映射包括：

.. list-table:: 典型 KES 类型映射
   :widths: 22 38 40
   :header-rows: 1

   * - 模式
     - KES 类型示例
     - Python 类型
   * - MySQL
     - tinyint、uint4、uint8
     - ``int``
   * - MySQL
     - date、time、datetime、timestamp
     - ``date``、``time``/``timedelta``、``datetime``
   * - MySQL
     - binary、varbinary、bit、json
     - ``bytes`` 或 ``str``
   * - Oracle
     - rowid、urowid、bfile、dsinterval、yminterval
     - ``str``；部分 interval 可编码 ``timedelta``
   * - SQL Server
     - bit、tinyint、money
     - ``bool``、``int``、``Decimal``
   * - SQL Server
     - date、time、datetime、datetime2、smalldatetime
     - ``date``、``time``、``datetime``
   * - SQL Server
     - uniqueidentifier、binary、varbinary、rowversion
     - ``UUID``、``bytes``

未配置专用 codec 的类型通常按文本处理。实际可用类型由 KES 版本和兼容模式决定。

自定义 JSON codec 示例：

.. code-block:: python

   import json

   await connection.set_type_codec(
       "json",
       schema="pg_catalog",
       encoder=json.dumps,
       decoder=json.loads,
       format="text",
   )

   await connection.reset_type_codec("json", schema="pg_catalog")

KES 兼容类型使用文本 wire codec 时，``set_builtin_type_codec()`` 不能把它别名为
不兼容的 PostgreSQL 二进制 codec。此类类型应使用 ``format="text"``，或通过
``set_type_codec()`` 提供 Python 编解码函数。修改复合类型或 schema 后，调用：

.. code-block:: python

   await connection.reload_schema_state()

池中注册 codec 应使用 ``init`` 回调，确保新建和重建连接都执行注册。

SQLAlchemy 2.x
--------------

创建 AsyncEngine
~~~~~~~~~~~~~~~~

安装 ``asyncpg-kes[sqlalchemy]`` 后，可直接使用三个已注册方言：

.. code-block:: python

   from sqlalchemy import text
   from sqlalchemy.ext.asyncio import create_async_engine


   engine = create_async_engine(
       "kingbase_mysql+asyncpg://system:your-password@"
       "127.0.0.1:54321/test?sslmode=disable",
       pool_pre_ping=True,
   )

   async with engine.connect() as connection:
       result = await connection.execute(
           text("SELECT CAST(:value AS SIGNED)"), {"value": 9}
       )
       print(result.scalar_one())

   await engine.dispose()

.. figure:: _static/user-manual/05-sqlalchemy-dialects.png
   :width: 96%
   :align: center
   :alt: SQLAlchemy asyncpg-kes 三种异步方言截图

   图 5：SQLAlchemy 2.x 通过三个已注册 URL 前缀加载对应 SQL 编译方言，底层
   驱动均为 asyncpg-kes，并成功返回查询结果。

对应 URL：

.. code-block:: text

   kingbase_mysql+asyncpg://user:password@host:54321/database
   kingbase_oracle+asyncpg://user:password@host:54322/database
   kingbase_sqlserver+asyncpg://user:password@host:54323/database

SQLAlchemy URL 会自动设置相应的 ``kes_mode``，无需再传模式参数。可在 query 中
配置 ``sslmode``、``timeout``、``command_timeout``、
``statement_cache_size``、``prepared_statement_cache_size``、
``max_cached_statement_lifetime``、``max_cacheable_statement_size`` 和
``direct_tls``。

.. code-block:: text

   kingbase_mysql+asyncpg://user:password@host:54321/database?sslmode=disable&prepared_statement_cache_size=0&command_timeout=5

多主机 URL 使用重复的 ``host=address:port`` 参数：

.. code-block:: text

   kingbase_mysql+asyncpg://user:password@/database?host=host-a:54321&host=host-b:54321&sslmode=disable&timeout=5

方言能力
~~~~~~~~

三个方言提供模式 SQL 编译和 KES catalog 反射，包括表、视图、列、主键、外键、
唯一约束、检查约束和索引。主要边界如下：

* MySQL 方言支持反引号、``AUTO_INCREMENT``、``LIMIT/OFFSET``、
  ``ON DUPLICATE KEY UPDATE``、字符串拼接和 ``LAST_INSERT_ID()``。
* Oracle 方言支持 identity、computed、sequence、流式结果和单行/批量 DML
  RETURNING。KES Oracle 返回 RETURNING 行时不使用 Oracle ``INTO`` 子句。
* SQL Server 方言支持 identity、流式结果、DML RETURNING、嵌套事务和注释。
  当前验证服务器不支持 computed column 语法，因此方言不宣传该能力。

SQLAlchemy 的连接池与 asyncpg 原生 Pool 是两套池。使用 AsyncEngine 时应配置
SQLAlchemy 池参数，不要在其下再套一层 asyncpg Pool。服务启动时创建一个全局
Engine，关闭时调用 ``await engine.dispose()``。

Alembic
~~~~~~~

安装 ``asyncpg-kes[alembic]`` 后，Alembic 可使用上述 URL 进行 schema 比较和
迁移。迁移脚本中的 DDL 仍应符合目标 KES 模式。上线前必须在同版本、同模式测试
实例执行 ``upgrade`` 和 ``downgrade`` 演练，不要假设三个模式的 DDL 事务行为
一致。

TLS、认证与安全
---------------

生产 TLS
~~~~~~~~

推荐由应用创建 SSLContext：

.. code-block:: python

   import ssl

   context = ssl.create_default_context(
       ssl.Purpose.SERVER_AUTH,
       cafile="/etc/app/certs/ca.pem",
   )
   context.check_hostname = True
   context.load_cert_chain(
       "/etc/app/certs/client.crt",
       "/etc/app/certs/client.key",
   )

   connection = await asyncpg.connect(
       **settings,
       ssl=context,
   )

证书、私钥和密码应由密钥管理系统、受限环境变量或挂载文件提供。不要记录完整
DSN；其中通常含明文密码。密码文件应限制为当前用户可读。

安全建议
~~~~~~~~

* 应用账号按最小权限授权，不使用数据库超级用户运行普通业务。
* 始终使用参数绑定传递业务值。
* 对动态表名和列名使用应用内白名单，不接受任意外部字符串。
* 为连接、命令和连接池获取分别设置合理超时。
* 不在异常日志中输出密码、证书私钥或完整连接 URL。
* 生产升级先经过同模式预发布环境和回归套件。

日志与运行监控
--------------

查询日志
~~~~~~~~

``add_query_logger()`` 可以收集 SQL、参数、超时、耗时、异常、连接地址和连接
参数。回调应快速完成，敏感参数应脱敏：

.. code-block:: python

   import logging

   logger = logging.getLogger("database.query")

   def log_query(record):
       logger.info(
           "query=%r elapsed=%.3f error=%r address=%r",
           record.query,
           record.elapsed,
           record.exception,
           record.conn_addr,
       )

   connection.add_query_logger(log_query)

   # 不再需要时移除
   connection.remove_query_logger(log_query)

也可以用 ``with connection.query_logger(callback):`` 限定记录范围。不要在日志中
直接输出 ``record.args``，除非完成敏感信息脱敏。

建议指标
~~~~~~~~

* 连接建立成功率、握手耗时和模式校验失败数；
* SQL 调用量、延迟分位数、超时数和异常类型；
* Pool 总连接数、空闲连接数、借出数和获取超时数；
* 事务提交、回滚和任务取消数量；
* COPY 行数、字节数、失败和取消数量；
* 服务关闭时等待归还的连接数。

asyncpg-kes 本身不提供 Druid 式 Web 监控页面。应将 query logger、连接池指标和
应用日志接入现有日志/指标平台。数据库侧慢 SQL、会话和锁等待仍由 KingbaseES
监控工具负责。

异常处理
--------

asyncpg-kes 保留 asyncpg 的异常层次。建议按可恢复性处理：

.. list-table:: 常见异常及处理
   :widths: 32 68
   :header-rows: 1

   * - 异常
     - 建议处理
   * - ``ClientConfigurationError``
     - 检查 ``kes_mode``、DSN、服务文件和实际实例模式；不要重试错误配置。
   * - ``InvalidPasswordError``
     - 检查账号、密码和认证规则；不要无限重试。
   * - ``InvalidCatalogNameError``
     - 目标数据库不存在或无权访问。
   * - ``InterfaceError``
     - 常见于连接已关闭、连接已归还池、并发使用同一连接或游标不在事务中。
   * - ``PostgresSyntaxError``
     - SQL 不符合当前 KES 模式语法；原生驱动不会转换 SQL。
   * - ``UnsupportedClientFeatureError``
     - 请求了当前模式不支持的事务选项或 codec 格式。
   * - ``OutdatedSchemaCacheError``
     - schema 发生变化；调用 ``reload_schema_state()`` 并重新执行安全操作。
   * - ``asyncio.TimeoutError``
     - 区分连接、SQL、Pool 获取超时；只对幂等操作实施有上限退避重试。
   * - ``asyncio.CancelledError``
     - 继续向上传播，让事务回滚和连接池归还逻辑完成。

捕获数据库异常时应回滚当前事务。不要对唯一键冲突、语法错误、错误模式等确定性
错误自动重试。网络瞬断和只读查询超时可以按业务幂等规则有限重试。

生产配置建议
------------

连接池容量
~~~~~~~~~~

连接池不是越大越好。建议从以下关系估算：

.. code-block:: text

   单实例应用 max_size
       <= 数据库为该应用预留连接数 / 应用实例数

为数据库管理员、迁移任务和故障处置保留连接。根据 SQL 延迟、事务时长、CPU、锁
等待和 Pool 获取等待持续调整。不要直接照搬 Druid ``maxActive=1000`` 等参数。

推荐基线
~~~~~~~~

以下值只是起点，应通过压测确定：

.. code-block:: python

   pool = await asyncpg.create_pool(
       **settings,
       min_size=2,
       max_size=10,
       max_queries=50000,
       max_inactive_connection_lifetime=300,
       timeout=5,
       command_timeout=30,
       statement_cache_size=100,
   )

应用应在进程启动阶段创建 Pool，在停机阶段等待请求结束后关闭 Pool。不要为每个
请求创建和销毁一个连接池。

高可用连接
~~~~~~~~~~

原生 API 支持主机和端口序列：

.. code-block:: python

   connection = await asyncpg.connect(
       host=["kes-a.example.com", "kes-b.example.com"],
       port=[54321, 54321],
       target_session_attrs="read-write",
       **common_settings,
   )

驱动按候选地址建立连接并关闭未选中的连接。高可用切换、DNS、负载均衡和重试
策略仍应与 KingbaseES 部署方案一起设计。

测试与验收
----------

仓库中的测试按以下层级组织：

.. code-block:: text

   tests/kes/unit/          不连接数据库的驱动内部测试
   tests/kes/integration/   三模式连接、API、事务、类型、COPY、并发测试
   tests/kes/framework/     SQLAlchemy 和 Alembic 测试

测试环境变量：

.. code-block:: bash

   export ASYNCPG_KES_HOST=127.0.0.1
   export ASYNCPG_KES_USER=system
   export ASYNCPG_KES_PASSWORD='your-password'
   export ASYNCPG_KES_DATABASE=test
   export ASYNCPG_KES_MYSQL_PORT=54321
   export ASYNCPG_KES_ORACLE_PORT=54322
   export ASYNCPG_KES_SQLSERVER_PORT=54323

执行测试：

.. code-block:: bash

   ./run_kes_tests.sh unit -q
   ./run_kes_tests.sh integration --kes-mode mysql -q
   ./run_kes_tests.sh integration --kes-mode oracle -q
   ./run_kes_tests.sh integration --kes-mode sqlserver -q
   ./run_kes_tests.sh framework -q
   ./run_kes_tests.sh all -q

.. figure:: _static/user-manual/06-unit-tests.png
   :width: 96%
   :align: center
   :alt: asyncpg-kes 单元测试通过截图

   图 6：驱动单元测试在允许本地 TCP 套接字的正常宿主环境中全部通过。

集成测试会创建并清理临时对象。``asynckes`` schema 测试要求三个模式的 test
数据库中已经存在该 schema。生产发布至少应验证安装 wheel、三模式连接、CRUD、
事务回滚、连接池并发、类型映射、COPY、SQLAlchemy 反射和优雅关闭。

常见问题
--------

为什么安装的是 asyncpg-kes，代码却 import asyncpg？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

为了兼容原 asyncpg API，发行包名是 ``asyncpg-kes``，导入包名仍为
``asyncpg``。同一环境不要同时安装两个发行包。

为什么连接时提示 kes_mode 与实例不匹配？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

端口指向了其他兼容模式，或 ``kes_mode`` 配置错误。分别核对实例、端口、服务
文件和 SQLAlchemy URL 前缀。该校验用于阻止错误模式连接，不应绕过。

为什么 MySQL、Oracle、SQL Server SQL 不能互相执行？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

驱动适配的是协议、类型、事务和 API，不会翻译传给原生 asyncpg 的 SQL。使用
SQLAlchemy 方言可以获得模式化 SQL 编译；手写 SQL 必须符合目标 KES 模式。

为什么 Oracle 模式 CALL 带参数失败？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

当前验证的 KES Oracle 模式接受字面量 ``CALL``，但拒绝扩展协议参数。优先使用
常规 SQL 或经验证的过程调用方式。Oracle 风格 OUT bind 不属于 asyncpg API；
需要返回 DML 结果时使用 KES 支持的 RETURNING 路径。

为什么 Oracle 模式不能使用 VARBINARY？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

当前验证服务器不暴露该类型。使用该模式支持的 ``BLOB`` 或 ``BYTEA``，并在
目标 KES 版本上验证。

为什么 SQL Server computed column 不可用？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

当前验证的 V009R001C010 SQL Server 模式拒绝 computed column 语法，因此方言
没有宣传该能力。不要根据官方 SQL Server 行为推断 KES 兼容模式能力。

为什么游标提示必须在事务中使用？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

asyncpg 游标依赖服务端 portal，必须放在 ``async with connection.transaction()``
中。事务结束后不要继续使用该游标。

为什么预编译语句偶尔不存在或重名？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

先确认是否经过事务级或语句级代理，以及代理是否保持服务端会话。必要时设置
``statement_cache_size=0``。KES 模式中的命名语句生命周期已做适配，但代理仍
必须满足 asyncpg 的会话要求。

为什么 wheel 安装后没有 connect？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

这通常表示 wheel 只包含 C 扩展、没有 Python 包，或 Python 从错误目录导入。
检查：

.. code-block:: bash

   python -c "import asyncpg; print(asyncpg.__file__); print(asyncpg.connect)"
   python -m pip show -f asyncpg-kes

应从干净 Git 归档构建，并在源码目录外安装验证。当前项目打包配置同时兼容
``setup.py`` 元数据和 PEP 517 构建。

项目结构与维护
--------------

.. code-block:: text

   asyncpg-0.31.0-kes/
   |-- asyncpg/                 驱动运行时代码
   |   |-- kes.py               三模式 codec、事务和模式适配
   |   `-- sa_dialect.py        SQLAlchemy 三模式方言
   |-- docs/                    Sphinx 文档和本用户手册源文件
   |-- tests/kes/               KES 单元、集成和框架测试
   |-- run_kes_tests.sh         测试入口
   |-- pyproject.toml           构建系统和工具配置
   `-- setup.py                 发行元数据、包发现和 C 扩展构建

用户手册与驱动源码放在同一个仓库，可以随版本一起评审、测试和发布。无需为手册
单独创建项目。发布新版本时，应同步更新版本号、变更记录、用户手册、API 文档、
测试记录和 wheel 校验结果。

附录：最小连通性检查
--------------------

.. code-block:: python

   import asyncio
   import os
   import asyncpg


   PORTS = {"mysql": 54321, "oracle": 54322, "sqlserver": 54323}


   async def check(mode):
       connection = await asyncpg.connect(
           host=os.getenv("ASYNCPG_KES_HOST", "127.0.0.1"),
           port=PORTS[mode],
           user=os.getenv("ASYNCPG_KES_USER", "system"),
           password=os.environ["ASYNCPG_KES_PASSWORD"],
           database=os.getenv("ASYNCPG_KES_DATABASE", "test"),
           kes_mode=mode,
           ssl=False,
           timeout=5,
       )
       try:
           sql = "SELECT 1 FROM dual" if mode == "oracle" else "SELECT 1"
           value = await connection.fetchval(sql)
           print(mode, value, connection.get_server_version())
       finally:
           await connection.close()


   async def main():
       for mode in ("mysql", "oracle", "sqlserver"):
           await check(mode)


   asyncio.run(main())

附录：相关文档
--------------

* ``README.rst``：项目定位、快速使用和兼容边界；
* ``docs/installation.rst``：安装和源码构建；
* ``docs/usage.rst``：继承的 asyncpg 使用说明和类型转换；
* ``docs/api/index.rst``：完整 API 参考；
* ``docs/kes-testing/TEST_PLAN.md``：三模式测试方案；
* ``docs/kes-testing/COVERAGE_MATRIX.md``：测试覆盖矩阵；
* ``docs/DELIVERY.md``：GitHub、CI 和发布流程。
