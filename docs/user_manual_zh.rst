.. _asynckb-user-manual-zh:

asynckb 用户手册
====================

文档信息
--------

.. list-table::
   :widths: 24 76
   :header-rows: 1

   * - 项目
     - 内容
   * - 产品名称
     - asynckb
   * - 文档版本
     - 0.31.0.post12
   * - 适用数据库
     - KingbaseES V009R001C010 MySQL、Oracle、SQL Server 兼容模式
   * - Python 版本
     - CPython 3.9 至 3.14
   * - 目标读者
     - Python 开发人员、测试人员、数据库管理员和运维人员

本文档说明如何安装、配置和使用 asynckb。文档中的 MySQL、Oracle 和
SQL Server 均表示 **KingbaseES 对应兼容模式**，不是连接官方 MySQL、Oracle
或 Microsoft SQL Server 数据库。

首次接入建议先按 :doc:`quickstart_zh` 完成安装、连通性、CRUD、连接池和
SQLAlchemy 验证，再回到本手册查询完整参数与能力边界。

产品说明
--------

asynckb 是基于 asyncpg 0.31.0 适配 KingbaseES 三种兼容模式的独立异步
Python 驱动。发行包名称和 Python 导入名均为 ``asynckb``。应用通过
PostgreSQL Wire Protocol 与 KingbaseES 通信，不依赖
``libkci``、ksycopg2 或官方 MySQL、Oracle、SQL Server 驱动。

运行链路如下：

.. code-block:: text

   asyncio 应用 / SQLAlchemy AsyncEngine
       -> asynckb Connection / Pool
       -> Cython 协议与 codec
       -> PostgreSQL Wire Protocol
       -> KingbaseES 兼容模式实例

驱动保留了 asynckb 的连接、预编译语句、游标、事务、连接池、COPY、通知、
自定义 codec 和异常体系。用户可以继续使用原 asynckb 的连接 URL 和参数；连接
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
* Python 环境应包含 ``venv`` 和 ``pip``；Debian/Ubuntu 最小安装通常需要先安装
  ``python3-venv``，也可能要求与解释器一致的 ``python3.10-venv`` 等版本包。
* 从源码构建时需要 C 编译器、Python 开发头文件和 Cython。
* 使用 SQLAlchemy 时需要 SQLAlchemy 2.x；使用 Alembic 时建议 Alembic 1.13
  或更高版本。

以下端口是本项目测试环境的默认值，不是所有 KingbaseES 安装的固定端口：

.. list-table:: KES 模式配置速查
   :widths: 18 18 20 44
   :header-rows: 1

   * - KES 模式
     - 可选校验值
     - 测试默认端口
     - SQLAlchemy URL 前缀
   * - MySQL 兼容模式
     - ``mysql``
     - ``54321``
     - ``kingbase+asynckb``
   * - Oracle 兼容模式
     - ``oracle``
     - ``54322``
     - ``kingbase+asynckb``
   * - SQL Server 兼容模式
     - ``sqlserver``
     - ``54323``
     - ``kingbase+asynckb``

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

不指定 schema 时，对象创建在当前用户的默认 schema。若使用 ``asynckb``
schema，应先由有权限的账号创建并授权。应用 SQL 中可以使用
``asynckb.table_name`` 这样的限定名称。

新机器交付清单
~~~~~~~~~~~~~~

在未安装本驱动的新机器上，至少应交付或提供以下资源：

* 与目标 CPython、操作系统和 CPU 匹配的 ``asynckb-*.whl``；当前随示例
  交付的 ``cp310-cp310-linux_x86_64`` 文件只适用于 CPython 3.10 Linux x86_64；
* 本用户手册和 ``asynckb_quickstart`` 示例项目；
* 可访问的 Python 制品仓库，或者用于离线安装的依赖 Wheel 集合；
* KES 主机、端口、数据库名、应用账号、密码和 TLS 证书信息。

Python 客户端不需要 Java、JAR、``libkci``，也不需要另外安装 MySQL、Oracle 或
SQL Server 厂商客户端。若新机器完全离线，只有一个驱动 Wheel 仍不足以运行
全部框架示例，还必须按下文准备 ``async_timeout``、SQLAlchemy、Alembic 及其
传递依赖。

安装与升级
----------

使用 wheel 安装
~~~~~~~~~~~~~~~~~~~~

交付时必须同时提供与目标 Python 和操作系统匹配的 ``asynckb`` wheel。
例如 ``cp310-cp310-linux_x86_64`` 只适用于 CPython 3.10 Linux x86_64，不能
安装到 CPython 3.11、PyPy 或其他 CPU/操作系统。推荐在独立虚拟环境中安装：

.. code-block:: bash

   cd /home/rootdba/下载/asynckb_quickstart
   python3.10 --version
   uname -m
   ls asynckb-*.whl
   # Debian/Ubuntu 若 python3 -m venv 报 ensurepip 不可用，先安装：
   sudo apt-get install python3-venv
   # 若系统明确提示版本包，则改用：sudo apt-get install python3.10-venv
   python3.10 -m venv .venv
   . .venv/bin/activate
   which python
   python -m pip --version
   python -m pip install --upgrade pip
   python -m pip install \
       ./asynckb-0.31.0.post12-cp310-cp310-linux_x86_64.whl

当操作系统只提供 ``python3`` 而没有 ``python`` 命令时，激活前使用
``python3.10``；激活后虚拟环境会提供 ``python``。``which python`` 必须指向
当前项目的 ``.venv/bin/python``。不要在虚拟环境外直接运行
``python3 -m pip uninstall``，否则可能卸载用户环境中的驱动。

发行包名和 Python 导入名均为 ``asynckb``。安装后执行：

.. code-block:: bash

   python -c "import asynckb; print(asynckb.__version__, asynckb.__file__)"
   python -m pip show asynckb

输出版本应为 ``0.31.0.post12``，文件路径应位于当前环境的
``site-packages/asynckb``，而不是源码目录。

上面的 ``/path/to`` 必须替换为交付的实际 wheel 路径。若交付方已将包发布到
公司 Python 制品仓库，也可以直接执行 ``python -m pip install asynckb``；
新环境没有网络或没有配置该制品仓库时，不能只执行这个命令。Python 3.10 的 wheel 还需要
``async_timeout>=4.0.3``，联网安装会由 pip 自动获取；离线安装时应同时提供该
依赖的 wheel。

APT 若报 ``Network is unreachable``、镜像站连接拒绝或超时，应先修复
软件源、DNS、代理或网络路由；``--fix-missing`` 无法代替网络连通性。
失败的 ``venv`` 命令可能留下没有 pip 的半成品，可先保留它：

.. code-block:: bash

   mv .venv .venv.incomplete

标准离线部署应提供完整 wheelhouse：

.. code-block:: bash

   python -m pip install --no-index --find-links wheelhouse \
       wheelhouse/asynckb-0.31.0.post12-*.whl
   python -m pip install --no-index --find-links wheelhouse \
       'SQLAlchemy>=2.0' 'alembic>=1.13'

只有当断网机器的 Python 3.10 已经提供 pip 和全部运行依赖时，
才可使用下列验收环境兜底方案：

.. code-block:: bash

   python3.10 -m venv --without-pip --system-site-packages .venv
   . .venv/bin/activate
   python -m pip install --no-index --no-deps \
       ./asynckb-0.31.0.post12-cp310-cp310-linux_x86_64.whl

``--system-site-packages`` 会降低隔离性，``--no-deps`` 也不会检索或下载缺失
依赖，因此该方案仅用于受控的断网验收，不应代替完整的生产交付。

.. figure:: _static/user-manual/01-wheel-installation.png
   :width: 96%
   :align: center
   :alt: asynckb wheel 安装与导入验证终端截图

   图 1：从 wheel 安装 asynckb，并在源码目录外验证版本、导入位置、
   三种 KES 模式和 ``connect`` API。

安装可选功能
~~~~~~~~~~~~

联网并使用制品仓库时：

.. code-block:: bash

   # SQLAlchemy 异步方言
   python -m pip install 'asynckb[sqlalchemy]'

   # SQLAlchemy 和 Alembic
   python -m pip install 'asynckb[alembic]'

   # GSSAPI/SSPI 认证
   python -m pip install 'asynckb[gssauth]'

如果只有本地 ``asynckb`` wheel，则先安装驱动，再安装可选依赖；不要把下面
的 extras 命令当作离线安装命令：

.. code-block:: bash

   python -m pip install 'SQLAlchemy>=2.0'
   python -m pip install 'SQLAlchemy>=2.0' 'alembic>=1.13'

离线环境应提前下载上述依赖及其传递依赖，或配置内部 Python 制品仓库。

从源码构建
~~~~~~~~~~

在 Linux 上先安装编译环境。Debian/Ubuntu 示例：

.. code-block:: bash

   sudo apt install build-essential python3-dev
   python -m pip install --upgrade pip build
   python -m build --wheel

构建结果位于 ``dist/``。交付前必须在源码目录外创建干净环境安装 wheel，并
确认 ``asynckb.connect``、版本信息和 SQLAlchemy entry point 均存在。不要只
使用 ``pip install -e .`` 验证发布包，因为 editable 安装会直接读取源码。

快速开始
--------

交付示例项目
~~~~~~~~~~~~~~~~

``/home/rootdba/下载/asynckb_quickstart`` 是可独立交付的从零验收项目，
不依赖驱动源码目录。首次使用应按以下顺序执行：

.. code-block:: bash

   cd /home/rootdba/下载/asynckb_quickstart
   python3.10 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install \
       ./asynckb-0.31.0.post12-cp310-cp310-linux_x86_64.whl
   python -m pip install -r requirements.txt
   python -c \
       'import asynckb; print(asynckb.__version__); print(asynckb.__file__)'

然后从模板创建配置文件，修改 ``.env`` 中的主机、用户、密码、
数据库和端口。不要将真实密码写回 ``.env.example`` 或提交到仓库：

.. code-block:: bash

   cp .env.example .env
   # 在编辑器中将 KES_PASSWORD='change-me' 改为真实密码
   set -a
   source .env
   set +a
   test -n "$KES_PASSWORD" && echo "数据库配置已加载"

该项目故意不在 Python 中自动读取 ``.env``，以避免应用在不知情的
情况下从当前目录注入密码。每次打开新终端都需要重新
``source .venv/bin/activate`` 和 ``source .env``。

建议先运行一个连接步骤，再执行完整验收：

.. code-block:: bash

   ./run.sh --list
   ./run.sh --mode mysql --step connection
   ./run.sh --mode all
   python -m pytest -q tests

``--mode all`` 和完整 pytest 会连接三个模式的端口。未设置
``KES_PASSWORD`` 时数据库测试会跳过；仍为 ``change-me`` 时会真正发起
连接，并以 ``InvalidPasswordError`` 失败。

示例项目 Python 文件说明
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. list-table:: 示例项目的 Python 文件
   :widths: 38 62
   :header-rows: 1

   * - 文件
     - 职责
   * - ``src/kes_quickstart/__init__.py``
     - 定义示例包，对外导出 ``DemoConfig``。
   * - ``src/kes_quickstart/config.py``
     - 将 ``KES_*`` 环境变量转为 ``DemoConfig``，选择模式端口并保护密码。
   * - ``src/kes_quickstart/cli.py``
     - 定义命令行参数和十个步骤的调度，输出 PASS 摘要和 JSON 结果。
   * - ``src/kes_quickstart/native.py``
     - 实现八个原生 asynckb 示例，并负责临时表、连接和 Pool 清理。
   * - ``src/kes_quickstart/framework.py``
     - 实现 SQLAlchemy Core/反射与 Alembic 升级/回退示例。
   * - ``steps/01_connection.py``
     - 固定运行连接与模式自动识别。
   * - ``steps/02_crud.py``
     - 固定运行参数绑定和异步 CRUD。
   * - ``steps/03_prepared_cursor.py``
     - 固定运行 PreparedStatement 和事务游标。
   * - ``steps/04_transaction.py``
     - 固定运行异常下的事务回滚。
   * - ``steps/05_pool.py``
     - 固定运行连接池获取、并发和归还。
   * - ``steps/06_copy.py``
     - 固定运行 COPY 批量导入和 CSV 导出。
   * - ``steps/07_notification.py``
     - 固定运行 ``LISTEN/NOTIFY`` 通知。
   * - ``steps/08_types.py``
     - 固定运行 Decimal、日期时间和二进制类型往返。
   * - ``steps/09_sqlalchemy.py``
     - 固定运行 SQLAlchemy 建表、CRUD 和列反射。
   * - ``steps/10_alembic.py``
     - 固定运行 Alembic 建表、加列、索引和回退。
   * - ``tests/conftest.py``
     - 将 ``src/`` 加入 pytest 导入路径。
   * - ``tests/test_config.py``
     - 不连数据库，验证配置解析、端口选择和密码脱敏。
   * - ``tests/test_cli.py``
     - 验证用户可见步骤、MySQL 连接命令和输出脱敏。
   * - ``tests/test_native_demos.py``
     - 在三个模式上验收八个原生 asynckb 工作流。
   * - ``tests/test_framework_demos.py``
     - 在三个模式上验收 SQLAlchemy 和 Alembic。

``steps/*.py`` 不重复实现业务逻辑，它们只调用 ``cli.step_main()`` 固定
当前步骤。学习实现时应重点阅读 ``config.py``、``native.py``、
``framework.py`` 和 ``cli.py``。``.venv/`` 内的 Python 文件是第三方包，不是
本示例源码。

建立连接
~~~~~~~~

下面示例使用原 asynckb 连接方式。驱动认证后会自动识别 KES 兼容模式；请替换
主机、端口、用户、密码和数据库名：

.. code-block:: python

   import asyncio
   import asynckb


   async def main():
       connection = await asynckb.connect(
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
           mode = connection.get_kes_mode()
           sql = "SELECT 1 FROM dual" if mode == "oracle" else "SELECT 1"
           value = await connection.fetchval(sql)
           print(value, mode)
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

   图 2：同一个 asynckb wheel 分别连接 KingbaseES MySQL、Oracle 和
   SQL Server 兼容模式，模式自动识别与连通性查询均成功。

使用 DSN
~~~~~~~~

原生 asynckb DSN 继续使用 ``postgresql://`` 协议名，因为底层仍是 PostgreSQL
Wire Protocol：

.. code-block:: python

   connection = await asynckb.connect(
       "postgresql://system:your-password@127.0.0.1:54321/test"
       "?sslmode=disable"
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

连接代码：

.. code-block:: python

   connection = await asynckb.connect(
       service="kes_mysql",
       servicefile="/path/to/pg_service.conf",
   )

也可以使用 ``PGSERVICE`` 和 ``PGSERVICEFILE`` 环境变量。正常连接不需要
``kes_mode``；若部署需要阻止应用误连到其他兼容模式，可以在连接参数、DSN 或
服务文件中显式配置，驱动会将其与自动探测结果进行校验。

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
     - 可选的 ``mysql``、``oracle`` 或 ``sqlserver`` 模式校验值；省略时通过
       ``SHOW DATABASE_MODE`` 自动识别，显式配置时必须与服务端模式一致。
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

asynckb 使用 ``$1``、``$2`` 形式的位置参数。参数绑定只用于数据值，不能
用于表名、列名或 SQL 关键字。

参数化接口还支持按连接模式转换占位符：MySQL 的 ``?`` 按出现顺序编号；
Oracle 的 ``:n`` 保留编号，``:name`` 不区分大小写并复用同名参数；SQL Server
的 ``@name`` 按首次出现顺序编号，完全同名时复用。命名占位符仍使用位置参数
传值，不接收参数字典。命名参数分配时避开已有 ``$n`` 和 Oracle 数字参数的编号。

.. code-block:: python

   # 分别在对应模式连接上执行，三种写法均返回 42。
   await mysql_con.fetchval("SELECT CAST(? AS INT)", 42)
   await oracle_con.fetchval("SELECT CAST(:value AS INT)", 42)
   await sqlserver_con.fetchval("SELECT CAST(@value AS INT)", 42)

字符串、引用标识符及注释内的标记不转换。MySQL 不允许混用 ``?`` 与 ``$n``
绑定标记；参数化 SQL 中需要问号运算符时用 ``??``，``?|``、``?&`` 保持不变。
转换统一接入语句准备流程，缓存命中或复用 PreparedStatement 时不重复转换；
``get_query()`` 仍返回应用提交的 SQL。无参数 ``execute(sql)`` 原样发送 SQL。

SQL Server 的已声明局部变量、``@@`` 系统变量及 EXEC 命名参数标签保持不变。
含 ``@`` 变量的过程、函数、触发器定义应通过无参数 ``execute(sql)`` 提交；
未声明变量赋值在准备阶段返回 InterfaceError。当前实例的带绑定参数 DECLARE
批次、EXEC 命名参数赋值仍有服务端限制，不能因占位符转换完成而宣称支持。
这项转换与 OUT 参数方向声明相互独立。

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

传给原生 asynckb API 的 SQL **不会被跨模式翻译**。应用必须使用当前 KES 模式
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
     - 返回由 ``asynckb.Record`` 组成的列表。
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
   import asynckb


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
       except asynckb.UndefinedTableError:
           pass


   async def run(port: int):
       connection = await asynckb.connect(**SETTINGS, port=port)
       table = "asynckb_user_demo"
       try:
           mode = connection.get_kes_mode()
           columns = (
               "id NUMBER(10) PRIMARY KEY, "
               "username VARCHAR2(50) NOT NULL UNIQUE, age NUMBER(3)"
               if mode == "oracle"
               else
               "id INT PRIMARY KEY, "
               "username VARCHAR(50) NOT NULL UNIQUE, age INT"
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


   asyncio.run(run(54321))

示例通过捕获 ``asynckb.UndefinedTableError`` 兼容三个模式的清理行为。业务程序
不应在每次启动时重复建表和删表，生产 DDL 应由经过审查的迁移脚本统一管理。

.. figure:: _static/user-manual/03-async-crud.png
   :width: 96%
   :align: center
   :alt: asynckb 三模式异步 CRUD 执行截图

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
占用也会增加；该值必须大于 0。游标依赖当前事务的服务端 portal，不能在事务
提交或回滚后继续读取。不要在一个连接上并发推进多个游标。

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
     - ``BEGIN``
     - ``BEGIN``
     - ``BEGIN TRANSACTION``
   * - 常用隔离级别
     - read_uncommitted、read_committed、repeatable_read、serializable
     - read_uncommitted、read_committed、repeatable_read、serializable
     - read_uncommitted、read_committed、repeatable_read、serializable
   * - readonly
     - 支持，最终能力由服务端确认
     - 支持，最终能力由服务端确认
     - 支持，最终能力由服务端确认
   * - deferrable
     - 沿用 PG 事务选项，由服务端执行
     - 沿用 PG 事务选项，由服务端执行
     - 沿用 PG 事务选项，由服务端执行
   * - 嵌套事务
     - SAVEPOINT / RELEASE SAVEPOINT / ROLLBACK TO
     - SAVEPOINT / RELEASE SAVEPOINT / ROLLBACK TO
     - SAVEPOINT / RELEASE SAVEPOINT / ROLLBACK TO

事务对象、隔离级别选项、提交、回滚和保存点操作复用 asynckb 的 PG 实现，
仅 SQL Server 模式的事务开启关键字使用 ``BEGIN TRANSACTION``。
隔离级别、只读和 deferrable 选项随 BEGIN 发送，不修改会话默认设置。
上述路径已在 KES V009R001C010 三种模式验证；其他版本应运行对应事务测试。
不同模式的 DDL 事务语义可能不同，不应假设所有 DDL 都能随外层事务回滚。

连接池
------

创建和使用
~~~~~~~~~~

服务端应用应优先使用 ``create_pool()``：

.. code-block:: python

   import asynckb


   pool = await asynckb.create_pool(
       host="127.0.0.1",
       port=54321,
       user="system",
       password="your-password",
       database="test",
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
   :alt: asynckb 事务回滚和异步连接池并发截图

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

连接池复用 asynckb 原有 Holder、Proxy 和异步队列，在同一个事件循环内为协程
提供并发连接，并不是供多个线程直接共享的线程池。达到 ``max_size`` 后，新的
``acquire()`` 会等待连接归还或到达超时，不会突破上限继续创建。归还时会回滚
未完成事务、清理监听器并重置会话；连接已关闭、不可恢复或 reset 失败时不会
放回可用队列，而是在对应 Holder 槽位重新建立物理连接并加载 KES codec。

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

asynckb 保留 asynckb 的 COPY API，三种 KES 模式均已覆盖 text、CSV 和
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

   listener = await asynckb.connect(**settings)
   sender = await asynckb.connect(**settings)
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

本地和 KES 动态映射均未命中时，驱动继续使用 asynckb introspection 解析数组、
domain 和复合类型；KES 对递归类型查询的 depth 列已做整数类型一致性处理。
能够走文本 codec 的未知标量通常返回 ``str``，但不存在“所有未知类型都默认
转为 str”的保证：无法解析或不支持的类型仍会抛出 codec/introspection 异常，
此时应注册自定义 codec 或升级映射。实际可用类型由 KES 版本和兼容模式决定。

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

安装 ``asynckb[sqlalchemy]`` 后，使用统一的 ``kingbase+asynckb``
方言入口：

.. code-block:: python

   from sqlalchemy import Integer, bindparam, text
   from sqlalchemy.ext.asyncio import create_async_engine


   engine = create_async_engine(
       "kingbase+asynckb://system:your-password@"
       "127.0.0.1:54321/test?sslmode=disable",
       pool_pre_ping=True,
   )

   async with engine.connect() as connection:
       raw = await connection.get_raw_connection()
       mode = raw.driver_connection.get_kes_mode()
       sql = "SELECT :value FROM dual" if mode == "oracle" else "SELECT :value"
       statement = text(sql).bindparams(
           bindparam("value", type_=Integer())
       )
       result = await connection.execute(statement, {"value": 9})
       print(result.scalar_one())

   await engine.dispose()

.. figure:: _static/user-manual/05-sqlalchemy-dialects.png
   :width: 96%
   :align: center
   :alt: SQLAlchemy asynckb 三种异步方言截图

   图 5：SQLAlchemy 2.x 通过统一 ``kingbase+asynckb`` URL 建立连接，驱动
   识别 KES 兼容模式后动态加载对应 SQL 编译和反射方言。

三种模式使用同一 URL 格式：

.. code-block:: text

   kingbase+asynckb://user:password@host:port/database

asynckb 在认证后执行 ``SHOW DATABASE_MODE``，SQLAlchemy 方言通过
``get_kes_mode()`` 动态选择 MySQL、Oracle 或 SQL Server 实现。URL
不传递 ``kes_mode``。可在 query 中配置 ``sslmode``、``timeout``、``command_timeout``、
``statement_cache_size``、``prepared_statement_cache_size``、
``max_cached_statement_lifetime``、``max_cacheable_statement_size`` 和
``direct_tls``。

.. code-block:: text

   kingbase+asynckb://user:password@host:54321/database?sslmode=disable&prepared_statement_cache_size=0&command_timeout=5

多主机 URL 使用重复的 ``host=address:port`` 参数：

.. code-block:: text

   kingbase+asynckb://user:password@/database?host=host-a:54321&host=host-b:54321&sslmode=disable&timeout=5

统一入口在首次数据库连接完成后才能取得兼容模式，因此当前只保证 **online
路径**。``create_all``、目录反射、``MigrationContext``、autogenerate 和
``Operations`` 必须放在已建立的连接中，通过 ``await connection.run_sync(...)``
执行。不要在首个连接建立前使用 ``engine.sync_engine.dialect`` 离线编译，也不要
使用 Alembic ``--sql`` 离线模式；此时尚未探测模式，占位方言不能保证生成目标
MySQL、Oracle 或 SQL Server 兼容语法。

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

SQLAlchemy 的连接池与 asynckb 原生 Pool 是两套池。使用 AsyncEngine 时应配置
SQLAlchemy 池参数，不要在其下再套一层 asynckb Pool。服务启动时创建一个全局
Engine，关闭时调用 ``await engine.dispose()``。

Alembic
~~~~~~~

安装 ``asynckb[alembic]`` 后，Alembic 可使用上述 URL 进行 schema 比较和
迁移。使用 ``alembic init -t async migrations`` 创建异步模板，在 ``env.py``
中配置模型的 ``target_metadata``，并保留
``await connection.run_sync(do_run_migrations)`` 调用。迁移脚本中的 DDL 仍应
符合目标 KES 模式。上线前必须在同版本、同模式测试实例执行 ``upgrade`` 和
``downgrade`` 演练，不要假设三个模式的 DDL、identity/sequence 或事务行为
一致。当前不支持依赖首连前占位方言的 Alembic 离线 ``--sql`` 路径；
autogenerate 必须连接目标 KES 实例。完整初始步骤见
:ref:`asynckb-quickstart-zh` 的 Alembic 章节。

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

   connection = await asynckb.connect(
       **settings,
       ssl=context,
   )

证书、私钥和密码应由密钥管理系统、受限环境变量或挂载文件提供。不要记录完整
DSN；其中通常含明文密码。密码文件应限制为当前用户可读。

认证方式与客户端 MAC
~~~~~~~~~~~~~~~~~~~~

认证方式由服务端认证规则决定，不通过 ``kes_mode`` 选择。
当前三模式已实测 SCRAM-SHA-256、Cleartext Password、MD5、trust、cert、peer、
LDAP、RADIUS 和 ident。LDAP/RADIUS/ident 使用隔离的真实协议服务，
cert 使用临时 CA 与客户端证书，均包含成功和拒绝场景。
Cleartext Password 应配合 TLS；trust 不检查密码，不代表密码认证成功。

当前三套 KES 构建明确不支持 PAM，Linux 实例不提供 BSD 认证。
这两项仅验证服务端限制，不能列为已完成端到端认证；国密不在本轮验证范围。

MAC 上传不是独立认证方式。服务端请求客户端 MAC 时，驱动自动上传实际 TCP
连接所用本地接口的 MAC，不新增连接参数。当前仅实现 Linux，支持 IPv4/IPv6
接口识别；非 Linux 或无法确定接口时明确报错。回环接口上传全零 MAC，
不应把回环白名单测试等同于物理网卡环境的安全认证。
MAC 由客户端报告，不应单独作为可信身份凭证。

已通过三模式 ``src_restrict.add_rules`` 的 ``limited_info='mac=...'``
白名单放行、错误 MAC 拒绝、正确 MAC 但错误密码拒绝测试。
规则由隔离实例内置安全管理员 ``sso`` 配置，未修改业务实例管理员密码。
本轮未验证服务端登录记录中的 MAC 展示，不将上传报文冒充审计落库结果。
完整记录见 ``docs/kes-testing/AUTHENTICATION_RESULTS.md``，
复跑说明见 ``tests/kes/authentication/README.md``。

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

asynckb 本身不提供 Druid 式 Web 监控页面。应将 query logger、连接池指标和
应用日志接入现有日志/指标平台。数据库侧慢 SQL、会话和锁等待仍由 KingbaseES
监控工具负责。

异常处理
--------

asynckb 保留 asynckb 的异常层次。建议按可恢复性处理：

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

   pool = await asynckb.create_pool(
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

   connection = await asynckb.connect(
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

   tests/kes/connection_initialization/              连接与模式初始化
   tests/kes/protocol_and_async/                     协议自解析与异步调度
   tests/kes/types_and_codecs/                       类型 OID 与 Codec
   tests/kes/execution_transactions_statements/     查询、事务与语句资源
   tests/kes/pool/                                   连接池
   tests/kes/sqlalchemy_dialect/                     SQLAlchemy 异步方言与 Alembic
   tests/kes/authentication/                         补充认证与 MAC 专项（需显式启用）

测试环境变量：

.. code-block:: bash

   export ASYNCKB_KES_HOST=127.0.0.1
   export ASYNCKB_KES_USER=system
   export ASYNCKB_KES_PASSWORD='your-password'
   export ASYNCKB_KES_DATABASE=test
   export ASYNCKB_KES_MYSQL_PORT=54321
   export ASYNCKB_KES_ORACLE_PORT=54322
   export ASYNCKB_KES_SQLSERVER_PORT=54323

执行测试：

.. code-block:: bash

   ./run_kes_tests.sh unit -q
   ASYNCKB_KES_PASSWORD='<password>' ./run_kes_tests.sh connection -q
   ASYNCKB_KES_PASSWORD='<password>' ./run_kes_tests.sh protocol -q
   ASYNCKB_KES_PASSWORD='<password>' ./run_kes_tests.sh types -q
   ASYNCKB_KES_PASSWORD='<password>' ./run_kes_tests.sh execution -q
   ASYNCKB_KES_PASSWORD='<password>' ./run_kes_tests.sh pool -q
   ASYNCKB_KES_PASSWORD='<password>' ./run_kes_tests.sh sqlalchemy -q
   ASYNCKB_KES_PASSWORD='<password>' ./run_kes_tests.sh all -q

.. figure:: _static/user-manual/06-unit-tests.png
   :width: 96%
   :align: center
   :alt: asynckb 单元测试通过截图

   图 6：驱动单元测试在允许本地 TCP 套接字的正常宿主环境中全部通过。

集成测试会创建并清理临时对象。``asynckb`` schema 测试要求三个模式的 test
数据库中已经存在该 schema。生产发布至少应验证安装 wheel、三模式连接、CRUD、
事务回滚、连接池并发、类型映射、COPY、SQLAlchemy 反射和优雅关闭。

常见问题
--------

为什么系统找不到 python？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ubuntu/Debian 可能只安装 ``python3`` 或 ``python3.10`` 命令。创建环境时使用
``python3.10 -m venv .venv``；激活后虚拟环境会提供 ``python``。
应通过 ``which python`` 确认它指向当前项目。

为什么 source .env 提示文件不存在？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``.env.example`` 只是模板，Shell 不会把它当成 ``.env``。在示例项目根目录
执行 ``cp .env.example .env``，填写真实配置后再执行
``set -a; source .env; set +a``。

为什么测试已连到数据库但认证失败？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

先查看异常中实际使用的用户和主机。若参数显示
``password='change-me'``，说明 ``.env`` 仍是模板密码，或修改后没有重新
``source .env``。这类错误已进入数据库认证阶段，与 Wheel 安装无关。

如何安装并导入驱动？
~~~~~~~~~~~~~~~~~~~~~~

执行 ``python -m pip install asynckb``，然后在代码中使用
``import asynckb``。发行包名和导入名一致。

为什么连接时提示 kes_mode 与实例不匹配？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``kes_mode`` 是可选的显式安全校验，不是正常连接的必填参数。该错误表示端口
指向了其他兼容模式，或连接参数、DSN、服务文件中的校验值配置错误。无需固定
模式时删除该参数，让驱动自动识别；需要校验时应修正实例或配置。SQLAlchemy
只使用统一的 ``kingbase+asynckb`` URL，不在 URL 入口中区分模式。

为什么 MySQL、Oracle、SQL Server SQL 不能互相执行？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

驱动适配的是协议、类型、事务和 API，不会翻译传给原生 asynckb 的 SQL。使用
SQLAlchemy 方言可以获得模式化 SQL 编译；手写 SQL 必须符合目标 KES 模式。

Oracle 模式如何绑定 CALL 参数并获取 OUT 值？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

驱动已补充 KES Parse 报文的参数方向标记，支持 ``CALL`` 的 IN、OUT 和
IN OUT 参数，不需要拼接参数值。以下示例已在 KES V009R001C010 Oracle
模式验证；执行账号需要创建过程的权限：

.. code-block:: python

   from decimal import Decimal

   await con.execute('''
       CREATE PROCEDURE demo_call(
           p_add IN NUMBER, p_total IN OUT NUMBER, p_label OUT VARCHAR2
       ) AS BEGIN
           p_total := p_total + p_add;
           p_label := 'done';
       END;
   ''')
   try:
       row = await con.fetchrow("CALL demo_call($1, $2, $3)", 2, 5, None)
       assert tuple(row) == (Decimal('7'), 'done')
   finally:
       await con.execute("DROP PROCEDURE demo_call")

每个占位符都需提供参数：IN 传输入值，IN OUT 传初始值，OUT 传 ``None``。
``fetch()`` / ``fetchrow()`` 返回服务端提供的 OUT 和 IN OUT 结果列；
``execute()`` 只返回命令状态，``executemany()`` 丢弃结果，需要批量返回值时
使用 ``fetchmany()``。预编译语句也支持该调用方式。

asynckb 不提供 ``callproc()`` 或 ``registerOutParameter()`` 接口。上述自动
方向处理只适用于 Oracle CALL，不能据此推断其他模式的调用行为。

三模式如何显式声明输入、输出参数？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

KES 连接的 ``prepare()`` 新增可选参数 ``parameter_modes``，使用列表或元组
按 ``$1``、``$2`` 等绑定位置声明 ``'in'``、``'out'``、``'inout'``。
声明数量必须与绑定位置数相符，非法方向在发送 SQL 前抛出 ``InterfaceError``。
参数类型由服务端推断，不固定 OID，不将参数值拼接进 SQL。
普通 PostgreSQL 连接不支持该扩展。未指定时保留既有行为。

假设已创建 ``demo_call``，依次接收输入整数、输入输出整数和输出字符串，
将第二个参数加上第一个参数，并将第三个参数设为 ``'done'``：

.. code-block:: python

   stmt = await con.prepare(
       'CALL demo_call($1, $2, $3)',
       parameter_modes=('in', 'inout', 'out'),
   )
   row = await stmt.fetchrow(2, 5, None)
   print(tuple(row))

在当前 KES V009R001C010 上，MySQL、Oracle 的结果为 ``(7, 'done')``；
SQL Server 额外返回过程状态列 ``_retval_``，结果为 ``(0, 7, 'done')``。
实际 Python 数字类型由过程声明决定，例如 Oracle NUMBER 返回 Decimal。
SQL Server 也可使用 ``EXEC demo_call $1, $2, $3`` 并声明相同参数方向。
参数方向声明与前述按模式进行的占位符转换相互独立；不支持 ``%s``，
也不表示完整存储过程兼容。

Oracle 的 DML RETURNING INTO 如何获取输出值？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

当前服务器拒绝独立 SQL 上下文中的 ``INSERT ... RETURNING ... INTO``
（SQLSTATE ``42601``）。在 Oracle 匿名块中执行 DML，并显式声明输出参数：

.. code-block:: python

   await con.execute('CREATE TABLE demo_output(id INT PRIMARY KEY)')
   try:
       stmt = await con.prepare(
           'BEGIN INSERT INTO demo_output VALUES ($1) '
           'RETURNING id INTO $2; END;',
           parameter_modes=('in', 'out'),
       )
       print(await stmt.fetchval(42, None))  # 42
   finally:
       await con.execute('DROP TABLE demo_output')

UPDATE、DELETE 可按相同方式返回单行输出。未匹配行时服务端抛出
``NoDataFoundError``，单值输出匹配多行时抛出 ``TooManyRowsError``；
驱动保留这些错误，不伪造结果。事务中的异常仍需正常回滚。
不需要输出绑定时，可继续使用 ``INSERT ... RETURNING id`` 配合
``fetchval()``，不必使用匿名块。驱动不会自动改写业务 SQL。
输出参数也可通过预编译语句的 ``fetchmany()`` 获取；``executemany()``
丢弃输出结果。此能力不代表所有过程、游标或数据库版本均已验证。

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

asynckb 游标依赖服务端 portal，必须放在 ``async with connection.transaction()``
中。事务结束后不要继续使用该游标。

为什么预编译语句偶尔不存在或重名？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

先确认是否经过事务级或语句级代理，以及代理是否保持服务端会话。必要时设置
``statement_cache_size=0``。KES 模式中的命名语句生命周期已做适配，但代理仍
必须满足 asynckb 的会话要求。

为什么 wheel 安装后没有 connect？
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

这通常表示 wheel 只包含 C 扩展、没有 Python 包，或 Python 从错误目录导入。
检查：

.. code-block:: bash

   python -c "import asynckb; print(asynckb.__file__); print(asynckb.connect)"
   python -m pip show -f asynckb

应从干净 Git 归档构建，并在源码目录外安装验证。当前项目打包配置同时兼容
``setup.py`` 元数据和 PEP 517 构建。

项目结构与维护
--------------

.. code-block:: text

   asynckb-0.31.0-kes/
   |-- asynckb/                 驱动运行时代码
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
   import asynckb


   PORTS = {"mysql": 54321, "oracle": 54322, "sqlserver": 54323}


   async def check(mode):
       connection = await asynckb.connect(
           host=os.getenv("ASYNCKB_KES_HOST", "127.0.0.1"),
           port=PORTS[mode],
           user=os.getenv("ASYNCKB_KES_USER", "system"),
           password=os.environ["ASYNCKB_KES_PASSWORD"],
           database=os.getenv("ASYNCKB_KES_DATABASE", "test"),
           ssl=False,
           timeout=5,
       )
       try:
           sql = "SELECT 1 FROM dual" if mode == "oracle" else "SELECT 1"
           value = await connection.fetchval(sql)
           detected = connection.get_kes_mode()
           if detected != mode:
               raise RuntimeError(f"expected {mode}, detected {detected}")
           print(detected, value, connection.get_server_version())
       finally:
           await connection.close()


   async def main():
       for mode in ("mysql", "oracle", "sqlserver"):
           await check(mode)


   asyncio.run(main())

附录：相关文档
--------------

* ``README.rst``：项目定位、快速使用和兼容边界；
* ``docs/quickstart_zh.rst``：从安装到框架接入的可执行快速上手；
* ``docs/installation.rst``：安装和源码构建；
* ``docs/usage.rst``：继承的 asynckb 使用说明和类型转换；
* ``docs/api/index.rst``：完整 API 参考；
* ``docs/kes-testing/TEST_PLAN.md``：三模式测试方案；
* ``docs/kes-testing/COVERAGE_MATRIX.md``：测试覆盖矩阵；
* ``docs/DELIVERY.md``：GitHub、CI 和发布流程。
