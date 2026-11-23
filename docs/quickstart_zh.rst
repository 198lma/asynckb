.. _asynckb-quickstart-zh:

asynckb 快速上手
=====================

本教程带你从空白 Python 环境开始，完成驱动安装、KingbaseES 连接、模式自动
识别、异步 CRUD、连接池、SQLAlchemy 和 Alembic 验证。完整参数和能力边界请
查阅 :doc:`user_manual_zh`。

适用范围
--------

asynckb 0.31.0.post12 适配 KingbaseES V009R001C010 的 MySQL、Oracle 和
SQL Server 兼容模式，要求 CPython 3.9 至 3.14。本文中的 MySQL、Oracle 和
SQL Server 均指 **KingbaseES 兼容模式**，不是对应厂商的独立数据库。

驱动保留 asynckb 的异步 API 和 PostgreSQL Wire Protocol。认证成功后自动执行
``SHOW DATABASE_MODE``，业务代码不需要配置模式入口：

.. code-block:: text

   Python 应用
       -> asynckb.connect() / create_pool()
       -> SHOW DATABASE_MODE
       -> 加载 MySQL、Oracle 或 SQL Server 类型与协议适配
       -> execute() / fetch() / cursor() / copy_*() / add_listener()

准备连接信息
------------

开始前向数据库管理员取得主机、端口、数据库名、用户名、密码和 TLS 要求。端口
由部署决定，以下是本文示例使用的测试值：

.. list-table:: 示例连接信息
   :widths: 24 20 24 32
   :header-rows: 1

   * - 兼容模式
     - 示例端口
     - 最小验证 SQL
     - 常用类型
   * - MySQL
     - ``54321``
     - ``SELECT 1``
     - ``INT``、``VARCHAR``
   * - Oracle
     - ``54322``
     - ``SELECT 1 FROM dual``
     - ``NUMBER``、``VARCHAR2``
   * - SQL Server
     - ``54323``
     - ``SELECT 1``
     - ``INT``、``VARCHAR``

先确认 Python 和目标端口可用：

.. code-block:: bash

   python3 --version
   nc -vz 127.0.0.1 54321

若系统没有 ``nc``，可以跳过端口检查，直接运行后面的 Python 连通性程序。

安装驱动
--------

以交付的 CPython 3.10 Linux x86_64 Wheel 为例，先确认解释器、
CPU 和 Wheel 文件：

.. code-block:: bash

   cd /home/rootdba/下载/asynckb_quickstart
   python3.10 --version
   uname -m
   ls asynckb-*.whl

``cp310-cp310-linux_x86_64`` 要求 CPython 3.10、Linux x86_64。匹配后再
创建独立虚拟环境安装交付包：

.. code-block:: bash

   python3.10 -m venv .venv
   source .venv/bin/activate
   which python
   python -m pip --version
   python -m pip install --upgrade pip
   python -m pip install \
       ./asynckb-0.31.0.post12-cp310-cp310-linux_x86_64.whl
   python -m pip install -r requirements.txt

系统不存在 ``python`` 命令并不表示 Python 未安装。激活前用
``python3.10``，激活后 ``python`` 应指向当前项目的
``.venv/bin/python``。不要在虚拟环境外盲目将命令改成
``python3 -m pip uninstall``，否则会操作用户或系统环境。

Debian/Ubuntu 最小安装若提示 ``ensurepip is not available``，先安装虚拟环境
组件，再重新创建环境：

.. code-block:: bash

   sudo apt-get install python3-venv
   # 若系统明确提示版本包，则改用：sudo apt-get install python3.10-venv

如果 APT 报 ``Network is unreachable``、镜像站连接拒绝或超时，根因是
软件源不可达；``--fix-missing`` 不能修复网络。应修复软件源/代理，
或使用交付方准备的离线环境和 wheelhouse。创建失败可能留下只有
``bin/python`` 而没有 pip 的不完整 ``.venv``，重试前应先将它改名保留：

.. code-block:: bash

   mv .venv .venv.incomplete

若断网机器的 Python 3.10 已有 pip 和全部运行依赖，可作为验收环境
临时使用：

.. code-block:: bash

   python3.10 -m venv --without-pip --system-site-packages .venv
   source .venv/bin/activate
   python -m pip install --no-index --no-deps \
       ./asynckb-0.31.0.post12-cp310-cp310-linux_x86_64.whl

该方式会读取系统和用户已安装的包，隔离性弱，不是生产部署首选。

如果交付方已将包发布到公司 Python 制品仓库，将最后一条命令改为：

.. code-block:: bash

   python -m pip install asynckb

该命令需要能访问配置的 Python 制品仓库。完全离线交付时，除驱动 Wheel 外，
Python 3.10 还应提供 ``async_timeout>=4.0.3`` 的 Wheel；执行后续 SQLAlchemy 和
Alembic 章节时，还应提供 SQLAlchemy、Alembic 及其传递依赖的 Wheel。可将所有
Wheel 放入 ``wheelhouse`` 后执行：

.. code-block:: bash

   python -m pip install --no-index --find-links wheelhouse \
       wheelhouse/asynckb-0.31.0.post12-*.whl
   python -m pip install --no-index --find-links wheelhouse \
       'SQLAlchemy>=2.0' 'alembic>=1.13'

发行包名和代码导入名都是 ``asynckb``。验证安装结果：

.. code-block:: bash

   python -c "import asynckb; print(asynckb.__version__); print(asynckb.__file__)"
   python -m pip show asynckb

版本应为 ``0.31.0.post12``，模块路径应位于当前虚拟环境。

.. figure:: _static/user-manual/01-wheel-installation.png
   :width: 96%
   :align: center
   :alt: asynckb wheel 安装和导入验证

   从 wheel 安装并确认版本、模块位置和 ``connect`` API。

使用交付示例项目
--------------------

交付目录 ``asynckb_quickstart`` 已将配置、原生 API、SQLAlchemy、
Alembic 和测试组织好。首次使用先复制配置模板：

.. code-block:: bash

   cd /home/rootdba/下载/asynckb_quickstart
   cp .env.example .env

编辑 ``.env``，把 ``change-me`` 替换为真实密码，并修改主机、数据库、
用户和各模式端口。项目不会自动读取 ``.env``，每次新开终端都要
激活环境并显式加载：

.. code-block:: bash

   source .venv/bin/activate
   set -a
   source .env
   set +a
   test -n "$KES_PASSWORD" && echo "数据库配置已加载"

``source .env`` 报文件不存在，表示尚未从 ``.env.example`` 复制。
认证堆栈若显示 ``password='change-me'``，表示仍在使用模板密码，需要
修改 ``.env`` 后重新 ``source .env``。

先列出步骤并只测一个已部署的模式：

.. code-block:: bash

   ./run.sh --list
   ./run.sh --mode mysql --step connection

连接通过后再运行单模式全部步骤、三模式验收和 pytest：

.. code-block:: bash

   ./run.sh --mode mysql
   ./run.sh --mode all
   python -m pytest -q tests

``--mode all`` 和完整 pytest 都会连接 MySQL、Oracle、SQL Server 三个
端口。只部署了一个模式时，应先用对应的 ``--mode`` 运行示例。

项目自带 Python 文件
~~~~~~~~~~~~~~~~~~~~~~~

``.venv/`` 中的 Python 文件属于第三方包，不是示例源码。项目自带的
Python 文件职责如下：

.. list-table:: Python 文件用途
   :widths: 38 62
   :header-rows: 1

   * - 文件
     - 用途
   * - ``src/kes_quickstart/__init__.py``
     - 定义示例包，对外导出 ``DemoConfig``。
   * - ``src/kes_quickstart/config.py``
     - 读取 ``KES_*`` 环境变量，按模式选端口，生成连接参数并隐藏密码。
   * - ``src/kes_quickstart/cli.py``
     - 解析 ``--mode``、``--step``、``--list``，调度示例并输出 PASS/JSON。
   * - ``src/kes_quickstart/native.py``
     - 实现连接、CRUD、预编译/游标、事务、连接池、COPY、通知和类型示例。
   * - ``src/kes_quickstart/framework.py``
     - 实现 SQLAlchemy 统一方言和 Alembic 升级/回退示例。
   * - ``steps/01_connection.py``
     - 启动连接与模式自动识别步骤。
   * - ``steps/02_crud.py``
     - 启动参数绑定和异步 CRUD 步骤。
   * - ``steps/03_prepared_cursor.py``
     - 启动预编译语句和事务游标步骤。
   * - ``steps/04_transaction.py``
     - 启动事务异常回滚步骤。
   * - ``steps/05_pool.py``
     - 启动连接池与并发步骤。
   * - ``steps/06_copy.py``
     - 启动 COPY 批量导入导出步骤。
   * - ``steps/07_notification.py``
     - 启动 ``LISTEN/NOTIFY`` 通知步骤。
   * - ``steps/08_types.py``
     - 启动 Decimal、日期时间和二进制类型步骤。
   * - ``steps/09_sqlalchemy.py``
     - 启动 SQLAlchemy Core CRUD 和反射步骤。
   * - ``steps/10_alembic.py``
     - 启动 Alembic 建表、加列、索引和回退步骤。
   * - ``tests/conftest.py``
     - 将 ``src/`` 加入 pytest 的导入路径。
   * - ``tests/test_config.py``
     - 不连数据库，测试配置解析、模式端口和密码脱敏。
   * - ``tests/test_cli.py``
     - 测试步骤列表、MySQL 连接入口和输出脱敏。
   * - ``tests/test_native_demos.py``
     - 在三个模式上验收八个原生 asynckb 流程。
   * - ``tests/test_framework_demos.py``
     - 在三个模式上验收 SQLAlchemy 和 Alembic。

``steps/*.py`` 只是固定步骤的薄入口，真正实现在
``src/kes_quickstart/`` 中。测试则把预期行为写成可重复验收的断言。

建立第一个连接
--------------

用环境变量提供连接信息。不要把真实密码提交到源码仓库：

.. code-block:: bash

   export KES_HOST='127.0.0.1'
   export KES_PORT='54321'
   export KES_USER='system'
   export KES_PASSWORD='your-password'
   export KES_DATABASE='test'

创建 ``check_connection.py``：

.. code-block:: python

   import asyncio
   import os

   import asynckb


   async def main():
       connection = await asynckb.connect(
           host=os.getenv("KES_HOST", "127.0.0.1"),
           port=int(os.getenv("KES_PORT", "54321")),
           user=os.getenv("KES_USER", "system"),
           password=os.environ["KES_PASSWORD"],
           database=os.getenv("KES_DATABASE", "test"),
           ssl=False,
           timeout=5,
           command_timeout=30,
       )
       try:
           mode = connection.get_kes_mode()
           sql = "SELECT 1 FROM dual" if mode == "oracle" else "SELECT 1"
           value = await connection.fetchval(sql)
           print(f"mode={mode} result={value}")
       finally:
           await connection.close()


   asyncio.run(main())

运行：

.. code-block:: bash

   python check_connection.py

预期输出之一为 ``mode=mysql result=1``、``mode=oracle result=1`` 或
``mode=sqlserver result=1``。代码未传 ``kes_mode``，模式来自服务端探测。

.. figure:: _static/user-manual/02-three-mode-connectivity.png
   :width: 96%
   :align: center
   :alt: KingbaseES 三种兼容模式自动识别和连通性验证

   同一个 wheel 自动识别并连接三种 KingbaseES 兼容模式。

完成异步 CRUD
-------------

原生 asynckb 不翻译 SQL，因此建表语法按连接后识别到的模式选择；参数绑定、
CRUD API 和资源释放方式保持一致。创建 ``crud_demo.py``：

.. code-block:: python

   import asyncio
   import os

   import asynckb


   async def drop_table(connection, table):
       try:
           await connection.execute(f"DROP TABLE {table}")
       except asynckb.UndefinedTableError:
           pass


   async def main():
       connection = await asynckb.connect(
           host=os.getenv("KES_HOST", "127.0.0.1"),
           port=int(os.getenv("KES_PORT", "54321")),
           user=os.getenv("KES_USER", "system"),
           password=os.environ["KES_PASSWORD"],
           database=os.getenv("KES_DATABASE", "test"),
           ssl=False,
       )
       table = "asynckb_quickstart"
       try:
           mode = connection.get_kes_mode()
           columns = (
               "id NUMBER(10) PRIMARY KEY, "
               "name VARCHAR2(50) NOT NULL, age NUMBER(3)"
               if mode == "oracle"
               else
               "id INT PRIMARY KEY, name VARCHAR(50) NOT NULL, age INT"
           )
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
               f"SELECT id, name, age FROM {table} WHERE id = $1", 1
           )
           await connection.execute(
               f"UPDATE {table} SET age = $1 WHERE id = $2", 31, 2
           )
           await connection.execute(
               f"DELETE FROM {table} WHERE id = $1", 3
           )
           count = await connection.fetchval(f"SELECT count(*) FROM {table}")
           print(mode, dict(row), f"remaining={count}")
       finally:
           await drop_table(connection, table)
           await connection.close()


   asyncio.run(main())

所有业务值使用 ``$1``、``$2`` 参数传入；表名和列名不能作为绑定参数，动态
标识符必须来自应用白名单。Oracle ``NUMBER`` 默认可能返回 ``Decimal``，不要
假设三个模式的数值结果一定是同一个 Python 类型。

.. figure:: _static/user-manual/03-async-crud.png
   :width: 96%
   :align: center
   :alt: asynckb 三种兼容模式 CRUD 结果

   三种兼容模式执行相同异步 CRUD 流程。

使用事务和连接池
----------------

服务端应用通常在进程启动时创建一个 Pool，在请求中借用连接，在进程关闭时
关闭 Pool：

.. code-block:: python

   pool = await asynckb.create_pool(
       host=os.getenv("KES_HOST", "127.0.0.1"),
       port=int(os.getenv("KES_PORT", "54321")),
       user=os.getenv("KES_USER", "system"),
       password=os.environ["KES_PASSWORD"],
       database=os.getenv("KES_DATABASE", "test"),
       ssl=False,
       min_size=2,
       max_size=10,
       command_timeout=30,
   )
   try:
       async with pool.acquire(timeout=5) as connection:
           async with connection.transaction():
               await connection.execute(
                   "UPDATE account SET balance = balance - $1 WHERE id = $2",
                   100, 1,
               )
   finally:
       await pool.close()

Pool 复用 asynckb 的 Holder、Proxy 和异步队列。同一事件循环中，达到
``max_size`` 后新任务等待可用连接，不会突破上限继续创建。连接归还时会重置
会话；不可恢复或重置失败的连接会被淘汰，并在相应槽位重新建立。它不是供多个
线程直接共享的线程池。

游标必须在活动事务内使用，且不能跨事务继续读取：

.. code-block:: python

   async with pool.acquire() as connection:
       async with connection.transaction():
           async for row in connection.cursor(
               "SELECT id, name FROM app_user ORDER BY id", prefetch=50
           ):
               process(row)

``prefetch`` 必须大于 0；小值增加网络往返，大值增加批次内存。

接入 SQLAlchemy 2.x
-------------------

安装可选依赖：

.. code-block:: bash

   python -m pip install 'asynckb[sqlalchemy]'

三个模式只使用一个 URL 入口：

.. code-block:: text

   kingbase+asynckb://user:password@host:port/database

不要按模式拆分或维护多个 URL 入口。统一方言在首次建立连接后读取驱动探测
结果，动态切换到 MySQL、Oracle 或 SQL Server 编译与反射实现。

以下代码使用 ``URL.create()``，避免手动转义密码中的特殊字符：

.. code-block:: python

   import asyncio
   import os

   from sqlalchemy import text
   from sqlalchemy.engine import URL
   from sqlalchemy.ext.asyncio import create_async_engine


   async def main():
       url = URL.create(
           "kingbase+asynckb",
           username=os.getenv("KES_USER", "system"),
           password=os.environ["KES_PASSWORD"],
           host=os.getenv("KES_HOST", "127.0.0.1"),
           port=int(os.getenv("KES_PORT", "54321")),
           database=os.getenv("KES_DATABASE", "test"),
           query={"sslmode": "disable"},
       )
       engine = create_async_engine(
           url, pool_pre_ping=True, pool_size=5, max_overflow=5
       )
       try:
           async with engine.connect() as connection:
               raw = await connection.get_raw_connection()
               mode = raw.driver_connection.get_kes_mode()
               sql = "SELECT 1 FROM dual" if mode == "oracle" else "SELECT 1"
               result = await connection.execute(text(sql))
               print(
                   f"mode={mode} dialect={connection.dialect.name} "
                   f"result={result.scalar_one()}"
               )
       finally:
           await engine.dispose()


   asyncio.run(main())

.. figure:: _static/user-manual/05-sqlalchemy-dialects.png
   :width: 96%
   :align: center
   :alt: SQLAlchemy 统一 URL 自动加载三种 KES 方言

   ``kingbase+asynckb`` 统一入口自动加载三种模式方言。

使用 ORM 或 SQLAlchemy Core 创建表时，应在连接建立后通过
``await connection.run_sync(metadata.create_all)`` 执行。方言负责标识符、分页、
identity、类型和目录反射；传给 ``text()`` 或 ``exec_driver_sql()`` 的手写 SQL
仍由应用保证符合目标模式。

统一入口只有在首次连接后才能知道目标模式，因此只支持建连后的 online 路径。
不要在连接前使用 ``engine.sync_engine.dialect`` 做离线编译；建表、反射和 schema
操作都应放在 ``async with engine.begin()`` 中并调用 ``run_sync()``。

接入 Alembic
------------

安装并初始化异步模板：

.. code-block:: bash

   python -m pip install 'asynckb[alembic]'
   alembic init -t async migrations
   export KES_SQLALCHEMY_URL='kingbase+asynckb://system:your-password@127.0.0.1:54321/test?sslmode=disable'

在生成的 ``migrations/env.py`` 中导入模型的 ``Base.metadata``，并从环境变量设置
统一 URL：

.. code-block:: python

   import os

   from myapp.models import Base

   config.set_main_option(
       "sqlalchemy.url",
       os.environ["KES_SQLALCHEMY_URL"].replace("%", "%%"),
   )
   target_metadata = Base.metadata

异步模板内部通过 ``await connection.run_sync(do_run_migrations)`` 调用 Alembic
同步迁移上下文，这一结构应保留。autogenerate 必须连接目标 KES 实例；当前不
支持依赖首连前占位方言的 ``alembic upgrade --sql`` 离线 SQL 生成。随后执行：

.. code-block:: bash

   alembic revision --autogenerate -m 'create initial schema'
   alembic upgrade head
   alembic current
   alembic downgrade -1

必须人工审查自动生成脚本，并在相同 KES 版本、相同兼容模式的测试实例演练升级
和回退。三个模式的 DDL、identity/sequence 和事务语义不完全相同，一份迁移脚本
只有在三种目标实例全部验证后才能视为跨模式可用。

模式差异速查
------------

.. list-table:: 业务开发常见差异
   :widths: 21 27 27 25
   :header-rows: 1

   * - 功能
     - MySQL 模式
     - Oracle 模式
     - SQL Server 模式
   * - 字符串类型
     - ``VARCHAR``
     - ``VARCHAR2``
     - ``VARCHAR``
   * - 整数类型
     - ``INT``
     - ``NUMBER``
     - ``INT``
   * - 自增/标识列
     - ``AUTO_INCREMENT``
     - identity / sequence
     - ``IDENTITY``
   * - 分页
     - ``LIMIT/OFFSET``
     - ``OFFSET/FETCH FIRST``
     - ``TOP`` 或 ``OFFSET/FETCH``
   * - Upsert
     - ``ON DUPLICATE KEY UPDATE``
     - 使用目标版本支持的 ``MERGE``
     - 使用目标版本支持的 ``MERGE``
   * - DML 返回行
     - 按目标版本能力
     - KES ``RETURNING``，不加 Oracle ``INTO``
     - KES ``RETURNING``
   * - 最小查询
     - ``SELECT 1``
     - ``SELECT 1 FROM dual``
     - ``SELECT 1``

原生 asynckb 只负责执行提供的 SQL。SQLAlchemy 表达式 API 可调用模式方言生成
对应语法；原生 SQL、``text()`` 和迁移脚本不会自动完成跨模式语义转换。

上线前检查
----------

至少完成以下验收：

* 在源码目录外安装最终 wheel，并确认导入的是 ``asynckb``；
* 使用应用账号验证自动模式识别、CRUD、事务回滚和连接池并发；
* 验证业务实际使用的类型、存储过程、COPY、RETURNING 或 Upsert；
* SQLAlchemy 项目验证建表、查询、分页和反射；Alembic 演练升级与回退；
* 生产环境启用证书校验，配置连接、命令和获取连接超时；
* Pool 或 AsyncEngine 在进程启动时创建，在关闭时完整释放；
* 不记录密码、完整 DSN、证书私钥和敏感绑定参数。

常见故障
--------

.. list-table:: 快速排查
   :widths: 34 66
   :header-rows: 1

   * - 现象
     - 处理方法
   * - ``ModuleNotFoundError`` 或没有 ``connect``
     - 激活正确虚拟环境，卸载冲突的 ``asynckb``，检查 ``asynckb.__file__``。
   * - 系统提示找不到 ``python``
     - 激活前使用 ``python3.10``；执行 ``source .venv/bin/activate`` 后
       再使用 ``python``。
   * - ``ensurepip is not available``
     - 联网时安装匹配的 ``python3.10-venv``；离线时使用完整
       wheelhouse/预制环境，或仅在依赖齐全时使用断网验收兜底方案。
   * - APT 报镜像站网络不可达
     - 检查 DNS、IPv4/IPv6、代理和软件源；``--fix-missing`` 不能解决
       ``Network is unreachable``。
   * - ``source .env`` 提示文件不存在
     - 先在项目根目录执行 ``cp .env.example .env``，再编辑并加载
       ``.env``。
   * - 连接拒绝或超时
     - 核对主机、端口、防火墙、监听地址和数据库服务状态。
   * - 认证失败
     - 核对用户、密码、数据库名、认证规则和账号权限。若堆栈显示
       ``password='change-me'``，修改 ``.env`` 后重新 ``source .env``。
   * - ``kes_mode`` 不匹配
     - 删除不必要的显式 ``kes_mode``；若用于安全校验，确认端口指向预期模式。
   * - Oracle 执行 ``SELECT 1`` 失败
     - 使用 ``SELECT 1 FROM dual``。
   * - 参数类型推导失败
     - 在 SQL 中显式 ``CAST($1 AS 目标类型)``，不要改用字符串拼接。
   * - Pool 获取超时
     - 检查连接是否及时归还、慢 SQL 和事务时长，再评估池容量。
   * - 游标在事务结束后失败
     - 将游标创建和迭代全部放入同一个活动事务。
   * - Alembic 生成错误语法
     - 确认 URL 是 ``kingbase+asynckb``，并在目标模式上人工审查和演练迁移。

完成以上步骤后，应用已具备从单连接开发到连接池、SQLAlchemy 和迁移管理的
基本接入能力。生产参数、类型映射、COPY、通知、TLS 和行为限制请继续阅读
:doc:`user_manual_zh`。
