"""SQLAlchemy async dialects for KingbaseES compatibility modes."""

from __future__ import annotations

from collections import deque
import re

from . import kes
from sqlalchemy import exc
from sqlalchemy import pool
from sqlalchemy import util
from sqlalchemy.dialects.mysql.base import MySQLDialect
from sqlalchemy.dialects.mysql.base import MySQLDDLCompiler
from sqlalchemy.dialects.mysql.base import MySQLExecutionContext
from sqlalchemy.dialects.mysql.types import BIT
from sqlalchemy.dialects.mysql.enumerated import ENUM
from sqlalchemy.dialects.mysql.enumerated import SET
from sqlalchemy.dialects.mssql.base import MSDialect
from sqlalchemy.dialects.mssql.base import MSDDLCompiler
from sqlalchemy.dialects.mssql.base import MSSQLCompiler
from sqlalchemy.dialects.mssql.base import MSExecutionContext
from sqlalchemy.dialects.oracle.base import OracleDialect
from sqlalchemy.dialects.oracle.base import OracleCompiler
from sqlalchemy.dialects.oracle.base import OracleExecutionContext
from sqlalchemy.dialects.oracle.base import OracleIdentifierPreparer
from sqlalchemy.dialects.oracle.types import BINARY_DOUBLE
from sqlalchemy.dialects.oracle.types import BINARY_FLOAT
from sqlalchemy.dialects.oracle.types import DATE as ORACLE_DATE
from sqlalchemy.dialects.oracle.types import INTERVAL as ORACLE_INTERVAL
from sqlalchemy.dialects.oracle.types import TIMESTAMP as ORACLE_TIMESTAMP
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi
from sqlalchemy.dialects.postgresql.asyncpg import (
    AsyncAdapt_asyncpg_connection,
)
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_cursor
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_ss_cursor
from sqlalchemy.dialects.postgresql.asyncpg import (
    AsyncAdaptFallback_asyncpg_connection,
)
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.dialects.postgresql.base import (
    PGDeferrableConnectionCharacteristic,
)
from sqlalchemy.dialects.postgresql.base import (
    PGReadOnlyConnectionCharacteristic,
)
from sqlalchemy.engine import reflection
from sqlalchemy.sql.compiler import DDLCompiler
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql import sqltypes
from sqlalchemy.util.concurrency import await_fallback
from sqlalchemy.util.concurrency import await_only


_KES_VERSION_RE = re.compile(r'V(\d+)R(\d+)C(\d+)', re.IGNORECASE)
_KES_TRAILING_CAST_RE = re.compile(
    r'\A(?P<expression>.+)::'
    r'(?:"(?:[^"]|"")+"|[A-Za-z_][A-Za-z0-9_$]*)'
    r'(?:\s+(?:varying|precision))?'
    r'(?:\([^()]*\))?\Z',
    re.DOTALL | re.IGNORECASE)
_KES_PG_CAST_RE = re.compile(
    r'::\s*'
    r'(?:(?:"(?:[^"]|"")+")|[A-Za-z_][A-Za-z0-9_$]*)'
    r'(?:\s+(?:varying|precision|with(?:out)?\s+time\s+zone))?'
    r'(?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?',
    re.IGNORECASE)
_KES_CHECK_RE = re.compile(
    r'\A\s*CHECK\s*\((?P<expression>.*)\)\s*\Z',
    re.DOTALL | re.IGNORECASE)


def _parse_kes_version(value):
    match = _KES_VERSION_RE.search(value or '')
    if match is None:
        return (9, 0, 0)
    return tuple(int(part) for part in match.groups())


class _KESAsyncAdaptCursor(AsyncAdapt_asyncpg_cursor):

    async def _prepare_and_execute(self, operation, parameters):
        await super()._prepare_and_execute(operation, parameters)
        self._adapt_connection._handle_deallocate(operation)

    async def _executemany(self, operation, seq_of_parameters):
        adapt_connection = self._adapt_connection

        self._rows.clear()
        async with adapt_connection._execute_mutex:
            await adapt_connection._check_type_cache_invalidation(
                self._invalidate_schema_cache_asof)

            if not adapt_connection._started:
                await adapt_connection._start_transaction()

            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof)
                if not attributes:
                    self.description = None
                    self.rowcount = -1
                    return await self._connection.executemany(
                        operation, seq_of_parameters)

                self.description = [
                    (attribute.name, attribute.type.oid,
                     None, None, None, None, None)
                    for attribute in attributes
                ]
                self._rows = deque(
                    await prepared_stmt.fetchmany(seq_of_parameters))
                self.rowcount = len(self._rows)
            except Exception as error:
                self._handle_exception(error)
            else:
                adapt_connection._handle_deallocate(operation)


class _KESAsyncAdaptConnection(AsyncAdapt_asyncpg_connection):

    def _handle_deallocate(self, operation):
        deallocated = kes.deallocated_statement(operation)
        if deallocated is None:
            return

        if deallocated is True:
            self._connection._mark_stmts_as_closed()
        else:
            statement = self._connection._named_statements.pop(
                deallocated, None)
            if statement is not None:
                statement.mark_closed()

        cache = self._prepared_statement_cache
        if cache is not None:
            cache.clear()

    def cursor(self, server_side=False):
        if server_side:
            return AsyncAdapt_asyncpg_ss_cursor(self)
        return _KESAsyncAdaptCursor(self)


class _KESAsyncAdaptFallbackConnection(
        AsyncAdaptFallback_asyncpg_connection):

    _handle_deallocate = _KESAsyncAdaptConnection._handle_deallocate

    def cursor(self, server_side=False):
        if server_side:
            return AsyncAdapt_asyncpg_ss_cursor(self)
        return _KESAsyncAdaptCursor(self)


class _KESAsyncAdaptDBAPI(AsyncAdapt_asyncpg_dbapi):

    def connect(self, *args, **kwargs):
        async_fallback = kwargs.pop('async_fallback', False)
        creator_fn = kwargs.pop('async_creator_fn', self.asyncpg.connect)
        statement_cache_size = kwargs.pop(
            'prepared_statement_cache_size', 100)
        statement_name_func = kwargs.pop(
            'prepared_statement_name_func', None)

        if util.asbool(async_fallback):
            return _KESAsyncAdaptFallbackConnection(
                self,
                await_fallback(creator_fn(*args, **kwargs)),
                prepared_statement_cache_size=statement_cache_size,
                prepared_statement_name_func=statement_name_func,
            )
        return _KESAsyncAdaptConnection(
            self,
            await_only(creator_fn(*args, **kwargs)),
            prepared_statement_cache_size=statement_cache_size,
            prepared_statement_name_func=statement_name_func,
        )


class _KESAsyncpgDialectMixin:
    driver = 'asyncpg'
    is_async = True
    has_terminate = True
    supports_statement_cache = True
    kes_mode = None
    _isolation_lookup = {}
    _split_multihost_from_url = PGDialect._split_multihost_from_url
    connection_characteristics = (
        PGDialect.connection_characteristics.union({
            'postgresql_readonly': PGReadOnlyConnectionCharacteristic(),
            'postgresql_deferrable': PGDeferrableConnectionCharacteristic(),
        })
    )

    @classmethod
    def import_dbapi(cls):
        return _KESAsyncAdaptDBAPI(__import__('asyncpg'))

    @classmethod
    def get_pool_class(cls, url):
        if util.asbool(url.query.get('async_fallback', False)):
            return pool.FallbackAsyncAdaptedQueuePool
        return pool.AsyncAdaptedQueuePool

    def create_connect_args(self, url):
        options = url.translate_connect_args(username='user')
        multihosts, multiports = self._split_multihost_from_url(url)
        options.update(url.query)
        options['kes_mode'] = self.kes_mode

        if multihosts:
            assert multiports
            if len(multihosts) == 1:
                options['host'] = multihosts[0]
                if multiports[0] is not None:
                    options['port'] = multiports[0]
            elif not all(multihosts):
                raise exc.ArgumentError(
                    'All hosts are required to be present '
                    'for asyncpg multiple host URL')
            elif not all(multiports):
                raise exc.ArgumentError(
                    'All ports are required to be present '
                    'for asyncpg multiple host URL')
            else:
                options['host'] = list(multihosts)
                options['port'] = list(multiports)
        else:
            util.coerce_kw_type(options, 'port', int)

        if 'sslmode' in options:
            if 'ssl' in options:
                raise exc.ArgumentError(
                    "Use either 'sslmode' or 'ssl', not both")
            options['ssl'] = options.pop('sslmode')

        util.coerce_kw_type(options, 'prepared_statement_cache_size', int)
        util.coerce_kw_type(options, 'statement_cache_size', int)
        util.coerce_kw_type(options, 'max_cached_statement_lifetime', float)
        util.coerce_kw_type(options, 'max_cacheable_statement_size', int)
        util.coerce_kw_type(options, 'command_timeout', float)
        util.coerce_kw_type(options, 'timeout', float)
        util.coerce_kw_type(options, 'direct_tls', bool)
        return [], options

    def initialize(self, connection):
        super().initialize(connection)
        max_identifier_length = int(connection.exec_driver_sql(
            'SHOW max_identifier_length').scalar())
        self.max_identifier_length = max_identifier_length
        self.max_constraint_name_length = max_identifier_length
        self.max_index_name_length = max_identifier_length

    def get_driver_connection(self, connection):
        return connection._connection

    def do_terminate(self, dbapi_connection):
        dbapi_connection.terminate()

    def is_disconnect(self, error, connection, cursor):
        if connection is not None:
            return connection._connection.is_closed()
        return (
            isinstance(error, self.dbapi.InterfaceError)
            and 'connection is closed' in str(error).lower()
        )

    def get_isolation_level_values(self, dbapi_connection):
        return list(self._isolation_lookup)

    def get_isolation_level(self, dbapi_connection):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute('SHOW transaction isolation level')
            return cursor.fetchone()[0].upper()
        finally:
            cursor.close()

    def set_isolation_level(self, dbapi_connection, level):
        dbapi_connection.set_isolation_level(self._isolation_lookup[level])

    def detect_autocommit_setting(self, dbapi_connection):
        return bool(dbapi_connection.autocommit)

    def set_readonly(self, dbapi_connection, value):
        dbapi_connection.readonly = value

    def get_readonly(self, dbapi_connection):
        return dbapi_connection.readonly

    def set_deferrable(self, dbapi_connection, value):
        dbapi_connection.deferrable = value

    def get_deferrable(self, dbapi_connection):
        return dbapi_connection.deferrable

    def _kes_schema(self, schema):
        return schema or self.default_schema_name

    def _kes_oracle_owner(self, schema):
        default_schema = self.default_schema_name
        if (
            schema is None
            or (
                getattr(schema, 'quote', None) is not True
                and default_schema is not None
                and schema.lower() == default_schema.lower()
            )
        ):
            return getattr(self, '_kes_default_owner', None)
        return self.denormalize_schema_name(schema)

    def _kes_oracle_name(self, name):
        return self.denormalize_name(name)

    @staticmethod
    def _kes_oracle_named_row(rows, name):
        for row in rows:
            if row[0] == name:
                return row
        matches = [row for row in rows if row[0].lower() == name.lower()]
        if len(matches) == 1:
            return matches[0]
        return None

    def _kes_column_type(self, row):
        type_name = row[1].lower()
        if type_name == 'user-defined' and len(row) > 8 and row[8]:
            type_name = row[8].lower()
        unsigned = type_name.endswith(' unsigned')
        if unsigned:
            type_name = type_name[:-9]

        if self.kes_mode == 'mysql':
            type_name = {
                'bpchar': 'char',
                'character': 'char',
                'double precision': 'double',
                'float4': 'float',
                'number': 'decimal',
            }.get(type_name, type_name)
            type_class = self.ischema_names.get(type_name, sqltypes.String)
        else:
            type_class = {
                'bigint': sqltypes.BigInteger,
                'binary': sqltypes.LargeBinary,
                'blob': sqltypes.LargeBinary,
                'boolean': sqltypes.Boolean,
                'bytea': sqltypes.LargeBinary,
                'char': sqltypes.CHAR,
                'clob': sqltypes.Text,
                'date': sqltypes.Date,
                'decimal': sqltypes.Numeric,
                'double precision': sqltypes.Double,
                'float': sqltypes.Float,
                'integer': sqltypes.Integer,
                'nclob': sqltypes.UnicodeText,
                'numeric': sqltypes.Numeric,
                'real': sqltypes.REAL,
                'raw': sqltypes.LargeBinary,
                'smallint': sqltypes.SmallInteger,
                'text': sqltypes.Text,
                'timestamp': sqltypes.DateTime,
                'timestamp with time zone': sqltypes.DateTime,
                'varchar': sqltypes.String,
                'varchar2': sqltypes.String,
                'varbinary': sqltypes.LargeBinary,
                'dsinterval': sqltypes.String,
                'yminterval': sqltypes.String,
            }.get(type_name, sqltypes.String)

        type_args = {}
        length = row[4]
        if (
            self.kes_mode == 'mysql'
            and type_name in {'char', 'varchar'}
            and (length is None or length < 0)
            and len(row) > 8
            and row[8]
        ):
            match = re.search(r'\((\d+)\)', row[8])
            if match is not None:
                length = int(match.group(1))
        if length is not None:
            type_args['length'] = length
        if row[5] is not None:
            type_args['precision'] = row[5]
        if row[6] is not None:
            type_args['scale'] = row[6]
        if (
            self.kes_mode == 'mysql'
            and row[7] is not None
            and type_name in {'time', 'datetime', 'timestamp'}
        ):
            type_args['fsp'] = row[7]
        if unsigned:
            type_args['unsigned'] = True

        try:
            return type_class(**type_args)
        except TypeError:
            return type_class()

    def _kes_sqlserver_type(self, row):
        type_name = row[1].lower()
        type_name = {
            'bpcharbyte': 'char',
            'int4': 'int',
            'int8': 'bigint',
            'varcharbyte': 'varchar',
        }.get(type_name, type_name)
        type_class = self.ischema_names.get(type_name, sqltypes.String)

        length = row[4]
        formatted_type = row[12]
        if length is None and formatted_type:
            match = re.search(r'\((max|\d+)\)', formatted_type, re.IGNORECASE)
            if match is not None:
                value = match.group(1)
                length = value.lower() if not value.isdigit() else int(value)

        type_args = {}
        if type_name in {
                'binary', 'char', 'nchar', 'nvarchar', 'varbinary',
                'varchar'} and length is not None:
            type_args['length'] = length
        elif type_name in {'decimal', 'numeric'}:
            if row[5] is not None:
                type_args['precision'] = row[5]
            if row[6] is not None:
                type_args['scale'] = row[6]
        elif type_name in {'datetime2', 'datetimeoffset', 'time'}:
            if row[7] is not None:
                type_args['precision'] = row[7]

        try:
            return type_class(**type_args)
        except TypeError:
            return type_class()

    @staticmethod
    def _kes_catalog_char(value):
        if isinstance(value, bytes):
            value = value.decode('ascii')
        if value == '\x00':
            return ''
        return value

    @staticmethod
    def _kes_mysql_default(value):
        if value is None:
            return None
        match = _KES_TRAILING_CAST_RE.fullmatch(value.strip())
        if match is None:
            return value
        return match.group('expression')

    @staticmethod
    def _kes_oracle_type(row):
        type_name = row[1].upper()
        length = int(row[4]) if row[4] is not None else None
        precision = int(row[5]) if row[5] is not None else None
        scale = int(row[6]) if row[6] is not None else None

        if type_name in {'INT4', 'INTEGER'}:
            return sqltypes.Integer()
        if type_name == 'SMALLINT':
            return sqltypes.SmallInteger()
        if type_name == 'BIGINT':
            return sqltypes.BigInteger()
        if type_name in {'NUMBER', 'NUMERIC', 'DECIMAL'}:
            return sqltypes.Numeric(precision=precision, scale=scale)
        if type_name in {'BINARY_FLOAT', 'FLOAT4', 'REAL'}:
            return BINARY_FLOAT(precision=precision)
        if type_name in {
                'BINARY_DOUBLE', 'DOUBLE PRECISION', 'FLOAT', 'FLOAT8'}:
            return BINARY_DOUBLE(precision=precision)
        if type_name in {'VARCHAR', 'VARCHAR2'}:
            return sqltypes.VARCHAR(length=length)
        if type_name == 'NVARCHAR2':
            return sqltypes.NVARCHAR(length=length)
        if type_name == 'CHAR':
            return sqltypes.CHAR(length=length)
        if type_name == 'NCHAR':
            return sqltypes.NCHAR(length=length)
        if type_name in {'CLOB', 'TEXT'}:
            return sqltypes.CLOB()
        if type_name == 'NCLOB':
            return sqltypes.UnicodeText()
        if type_name in {'BINARY', 'BLOB', 'BYTEA', 'VARBINARY'}:
            return sqltypes.LargeBinary(length=length)
        if type_name == 'DATE':
            return ORACLE_DATE()
        if type_name == 'TIMESTAMP':
            return ORACLE_TIMESTAMP()
        if type_name in {'TIMESTAMPTZ', 'TIMESTAMP WITH TIME ZONE'}:
            return ORACLE_TIMESTAMP(timezone=True)
        if type_name in {
                'TIMESTAMPLTZ', 'TIMESTAMP WITH LOCAL TIME ZONE'}:
            return ORACLE_TIMESTAMP(local_timezone=True)
        if type_name == 'DSINTERVAL':
            return ORACLE_INTERVAL()
        if type_name == 'YMINTERVAL':
            return sqltypes.String()
        if type_name == 'BOOLEAN':
            return sqltypes.Boolean()
        return sqltypes.String(length=length)

    @staticmethod
    def _kes_oracle_expression(value, *, check=False):
        if value is None:
            return None
        value = _KES_PG_CAST_RE.sub('', value).strip()
        if check:
            match = _KES_CHECK_RE.fullmatch(value)
            if match is not None:
                value = match.group('expression').strip()
        return value

    def _kes_oracle_columns(
            self, connection, table_name, schema=None, **kw):
        owner = self._kes_oracle_owner(schema)
        catalog_table_name = self._kes_oracle_name(table_name)
        rows = connection.exec_driver_sql(
            'SELECT column_name, data_type, nullable, data_default, '
            'coalesce(nullif(char_length, 0), data_length), '
            'data_precision, data_scale, NULL AS identity_column, '
            'NULL AS default_on_null '
            'FROM all_tab_columns '
            'WHERE lower(owner) = '
            'lower(coalesce($1, upper(current_user))) '
            'AND table_name = $2 '
            'ORDER BY column_id',
            (owner, catalog_table_name),
        ).all()
        if not rows:
            raise exc.NoSuchTableError(table_name)

        info_rows = connection.exec_driver_sql(
            'SELECT column_name, is_identity, identity_generation '
            'FROM information_schema.columns '
            'WHERE table_schema = $1 AND table_name = $2',
            (self._kes_schema(schema), table_name),
        ).all()
        attr_rows = connection.exec_driver_sql(
            'SELECT attr.attname, attr.attidentity, attr.attgenerated, '
            'col_description(attr.attrelid, attr.attnum) '
            'FROM pg_catalog.pg_attribute AS attr '
            'JOIN pg_catalog.pg_class AS cls ON cls.oid = attr.attrelid '
            'JOIN pg_catalog.pg_namespace AS ns '
            'ON ns.oid = cls.relnamespace '
            'WHERE ns.nspname = $1 AND cls.relname = $2 '
            'AND attr.attnum > 0 AND NOT attr.attisdropped '
            'ORDER BY attr.attnum',
            (self._kes_schema(schema), table_name),
        ).all()
        columns = []
        for row in rows:
            name = self.normalize_name(row[0])
            attr = self._kes_oracle_named_row(attr_rows, row[0])
            info = self._kes_oracle_named_row(info_rows, row[0])
            generated = (
                self._kes_catalog_char(attr[2]) if attr is not None else '')
            if info is None:
                info_identity, identity_generation = 'NO', None
            else:
                info_identity, identity_generation = info[1], info[2]
            is_identity = row[7] == 'YES' or info_identity == 'YES'
            column = {
                'name': name,
                'type': self._kes_oracle_type(row),
                'nullable': row[2] == 'Y',
                'default': (
                    None if generated
                    else self._kes_oracle_expression(row[3])),
                'autoincrement': is_identity,
            }
            if is_identity:
                column['identity'] = {
                    'always': identity_generation == 'ALWAYS',
                    'on_null': row[8] == 'YES',
                }
            if generated:
                column['computed'] = {
                    'sqltext': self._kes_oracle_expression(row[3]),
                    'persisted': True,
                }
            if attr is not None and attr[3] is not None:
                column['comment'] = attr[3]
            columns.append(column)
        return columns

    def has_table(self, connection, table_name, schema=None, **kw):
        self._ensure_has_table_connection(connection)
        if self.kes_mode == 'oracle':
            catalog_table_name = self._kes_oracle_name(table_name)
            row = connection.exec_driver_sql(
                'SELECT 1 FROM ('
                'SELECT owner, table_name FROM all_tables '
                'UNION ALL '
                'SELECT owner, view_name AS table_name FROM all_views'
                ') objects '
                'WHERE lower(owner) = '
                'lower(coalesce($1, upper(current_user))) '
                'AND table_name = $2',
                (self._kes_oracle_owner(schema), catalog_table_name),
            ).first()
            return row is not None
        row = connection.exec_driver_sql(
            'SELECT 1 FROM information_schema.tables '
            'WHERE table_schema = $1 AND table_name = $2',
            (self._kes_schema(schema), table_name),
        ).first()
        return row is not None

    @reflection.cache
    def get_schema_names(self, connection, **kw):
        if self.kes_mode == 'oracle':
            rows = connection.exec_driver_sql(
                'SELECT username FROM all_users ORDER BY username')
            return [self.normalize_name(row[0]) for row in rows]
        rows = connection.exec_driver_sql(
            'SELECT schema_name FROM information_schema.schemata '
            'ORDER BY schema_name')
        return [row[0] for row in rows]

    @reflection.cache
    def get_table_names(self, connection, schema=None, **kw):
        if self.kes_mode == 'oracle':
            rows = connection.exec_driver_sql(
                'SELECT table_name FROM all_tables '
                'WHERE lower(owner) = '
                'lower(coalesce($1, upper(current_user))) '
                'ORDER BY table_name',
                (self._kes_oracle_owner(schema),),
            )
            return [self.normalize_name(row[0]) for row in rows]
        rows = connection.exec_driver_sql(
            'SELECT table_name FROM information_schema.tables '
            "WHERE table_schema = $1 AND table_type = 'BASE TABLE' "
            'ORDER BY table_name',
            (self._kes_schema(schema),),
        )
        return [row[0] for row in rows]

    @reflection.cache
    def get_view_names(self, connection, schema=None, **kw):
        if self.kes_mode == 'oracle':
            rows = connection.exec_driver_sql(
                'SELECT view_name FROM all_views '
                'WHERE lower(owner) = '
                'lower(coalesce($1, upper(current_user))) '
                'ORDER BY view_name',
                (self._kes_oracle_owner(schema),),
            )
            return [self.normalize_name(row[0]) for row in rows]
        rows = connection.exec_driver_sql(
            'SELECT table_name FROM information_schema.tables '
            'WHERE table_schema = $1 '
            "AND table_type IN ('VIEW', 'SYSTEM VIEW') "
            'ORDER BY table_name',
            (self._kes_schema(schema),),
        )
        return [row[0] for row in rows]

    @reflection.cache
    def get_view_definition(
            self, connection, view_name, schema=None, **kw):
        if self.kes_mode == 'oracle':
            catalog_view_name = self._kes_oracle_name(view_name)
            row = connection.exec_driver_sql(
                'SELECT text FROM all_views '
                'WHERE lower(owner) = '
                'lower(coalesce($1, upper(current_user))) '
                'AND view_name = $2',
                (self._kes_oracle_owner(schema), catalog_view_name),
            ).first()
            if row is None:
                from sqlalchemy import exc
                raise exc.NoSuchTableError(view_name)
            return row[0]
        row = connection.exec_driver_sql(
            'SELECT view_definition FROM information_schema.views '
            'WHERE table_schema = $1 AND table_name = $2',
            (self._kes_schema(schema), view_name),
        ).first()
        if row is None:
            from sqlalchemy import exc
            raise exc.NoSuchTableError(view_name)
        return row[0]

    @reflection.cache
    def get_materialized_view_names(
            self, connection, schema=None, **kw):
        return []

    def get_multi_columns(self, connection, **kw):
        return self._default_multi_reflect(
            self.get_columns, connection, **kw)

    def get_multi_pk_constraint(self, connection, **kw):
        return self._default_multi_reflect(
            self.get_pk_constraint, connection, **kw)

    def get_multi_foreign_keys(self, connection, **kw):
        return self._default_multi_reflect(
            self.get_foreign_keys, connection, **kw)

    def get_multi_indexes(self, connection, **kw):
        return self._default_multi_reflect(
            self.get_indexes, connection, **kw)

    def get_multi_unique_constraints(self, connection, **kw):
        return self._default_multi_reflect(
            self.get_unique_constraints, connection, **kw)

    def get_multi_check_constraints(self, connection, **kw):
        return self._default_multi_reflect(
            self.get_check_constraints, connection, **kw)

    def get_multi_table_comment(self, connection, **kw):
        return self._default_multi_reflect(
            self.get_table_comment, connection, **kw)

    def get_multi_table_options(self, connection, **kw):
        return self._default_multi_reflect(
            self.get_table_options, connection, **kw)

    @reflection.cache
    def get_columns(self, connection, table_name, schema=None, **kw):
        if self.kes_mode == 'oracle':
            return self._kes_oracle_columns(
                connection, table_name, schema=schema, **kw)

        if self.kes_mode == 'sqlserver':
            rows = connection.exec_driver_sql(
                'SELECT cols.column_name, cols.data_type, '
                'cols.is_nullable, cols.column_default, '
                'cols.character_maximum_length, cols.numeric_precision, '
                'cols.numeric_scale, cols.datetime_precision, '
                'cols.udt_name, attr.attidentity, attr.attgenerated, '
                'col_description(attr.attrelid, attr.attnum), '
                'pg_catalog.format_type(attr.atttypid, attr.atttypmod) '
                'FROM information_schema.columns AS cols '
                'JOIN pg_catalog.pg_namespace AS ns '
                'ON ns.nspname = cols.table_schema '
                'JOIN pg_catalog.pg_class AS cls '
                'ON cls.relnamespace = ns.oid '
                'AND cls.relname = cols.table_name '
                'JOIN pg_catalog.pg_attribute AS attr '
                'ON attr.attrelid = cls.oid '
                'AND attr.attname = cols.column_name '
                'WHERE cols.table_schema = $1 AND cols.table_name = $2 '
                'ORDER BY cols.ordinal_position',
                (self._kes_schema(schema), table_name),
            ).all()
            if not rows:
                raise exc.NoSuchTableError(table_name)
            columns = []
            for row in rows:
                identity = self._kes_catalog_char(row[9])
                column = {
                    'name': row[0],
                    'type': self._kes_sqlserver_type(row),
                    'nullable': row[2] == 'YES',
                    'default': row[3],
                    'autoincrement': bool(identity),
                }
                if identity:
                    column['identity'] = {'always': False}
                if row[11] is not None:
                    column['comment'] = row[11]
                columns.append(column)
            return columns

        type_detail_column = (
            'column_type' if self.kes_mode == 'mysql' else 'udt_name')
        if self.kes_mode != 'mysql':
            rows = connection.exec_driver_sql(
                'SELECT column_name, data_type, is_nullable, column_default, '
                'character_maximum_length, numeric_precision, numeric_scale, '
                'datetime_precision, {} '
                'FROM information_schema.columns '
                'WHERE table_schema = $1 AND table_name = $2 '
                'ORDER BY ordinal_position'.format(type_detail_column),
                (self._kes_schema(schema), table_name),
            ).all()
            return [{
                'name': row[0],
                'type': self._kes_column_type(row),
                'nullable': row[2] == 'YES',
                'default': row[3],
                'autoincrement': 'auto',
            } for row in rows]

        rows = connection.exec_driver_sql(
            'SELECT cols.column_name, cols.data_type, cols.is_nullable, '
            'cols.column_default, cols.character_maximum_length, '
            'cols.numeric_precision, cols.numeric_scale, '
            'cols.datetime_precision, cols.{}, attr.atttypid, '
            'typ.typcategory, typ.typtype, attr.attidentity, '
            'attr.attgenerated, '
            'cols.extra, cols.column_comment, cols.generation_expression '
            'FROM information_schema.columns AS cols '
            'JOIN pg_catalog.pg_namespace AS ns '
            'ON ns.nspname = cols.table_schema '
            'JOIN pg_catalog.pg_class AS cls '
            'ON cls.relnamespace = ns.oid '
            'AND cls.relname = cols.table_name '
            'JOIN pg_catalog.pg_attribute AS attr '
            'ON attr.attrelid = cls.oid '
            'AND attr.attname = cols.column_name '
            'JOIN pg_catalog.pg_type AS typ ON typ.oid = attr.atttypid '
            'WHERE cols.table_schema = $1 AND cols.table_name = $2 '
            'ORDER BY cols.ordinal_position'.format(type_detail_column),
            (self._kes_schema(schema), table_name),
        ).all()
        if not rows:
            raise exc.NoSuchTableError(table_name)
        labels = {}
        if self.kes_mode == 'mysql' and rows:
            label_rows = connection.exec_driver_sql(
                'SELECT attr.atttypid, labels.label '
                'FROM pg_catalog.pg_namespace AS ns '
                'JOIN pg_catalog.pg_class AS cls '
                'ON cls.relnamespace = ns.oid '
                'JOIN pg_catalog.pg_attribute AS attr '
                'ON attr.attrelid = cls.oid '
                'JOIN ('
                'SELECT enumtypid AS type_oid, enumsortorder AS sort_order, '
                'enumlabel AS label FROM pg_catalog.pg_enum '
                'UNION ALL '
                'SELECT settypid AS type_oid, setsortorder AS sort_order, '
                'setlabel AS label FROM pg_catalog.pg_set'
                ') AS labels ON labels.type_oid = attr.atttypid '
                'WHERE ns.nspname = $1 AND cls.relname = $2 '
                'AND attr.attnum > 0 AND NOT attr.attisdropped '
                'ORDER BY attr.atttypid, labels.sort_order',
                (self._kes_schema(schema), table_name),
            ).all()
            for type_oid, label in label_rows:
                labels.setdefault(type_oid, []).append(label)

        columns = []
        for row in rows:
            type_category = self._kes_catalog_char(row[10])
            type_kind = self._kes_catalog_char(row[11])
            if (
                self.kes_mode == 'mysql'
                and (type_category == 'E' or type_kind in {'e', 'l'})
            ):
                column_type = ENUM(*labels.get(row[9], ()))
            elif (
                self.kes_mode == 'mysql'
                and (type_category == 'M' or type_kind == 'y')
            ):
                column_type = SET(*labels.get(row[9], ()))
            elif self.kes_mode == 'mysql' and row[1].lower() == 'bit':
                match = re.fullmatch(r'bit\((\d+)\)', row[8].lower())
                column_type = BIT(int(match.group(1))) if match else BIT()
            else:
                column_type = self._kes_column_type(row)

            identity = self._kes_catalog_char(row[12])
            generated = self._kes_catalog_char(row[13])
            column = {
                'name': row[0],
                'type': column_type,
                'nullable': row[2] == 'YES',
                'default': (
                    None if generated else self._kes_mysql_default(row[3])),
                'autoincrement': identity == 'i',
            }
            if row[15] is not None:
                column['comment'] = row[15]
            if generated or row[16]:
                column['computed'] = {
                    'sqltext': row[16] or row[3],
                    'persisted': 'STORED' in (row[14] or '').upper(),
                }
            columns.append(column)
        return columns

    @reflection.cache
    def get_table_comment(self, connection, table_name, schema=None, **kw):
        if self.kes_mode == 'mysql':
            row = connection.exec_driver_sql(
                'SELECT table_comment FROM information_schema.tables '
                'WHERE table_schema = $1 AND table_name = $2',
                (self._kes_schema(schema), table_name),
            ).first()
        elif self.kes_mode == 'sqlserver':
            row = connection.exec_driver_sql(
                "SELECT obj_description(cls.oid, 'pg_class') "
                'FROM pg_catalog.pg_class AS cls '
                'JOIN pg_catalog.pg_namespace AS ns '
                'ON ns.oid = cls.relnamespace '
                'WHERE ns.nspname = $1 AND cls.relname = $2',
                (self._kes_schema(schema), table_name),
            ).first()
        else:
            catalog_table_name = self._kes_oracle_name(table_name)
            row = connection.exec_driver_sql(
                'SELECT comments FROM all_tab_comments '
                'WHERE lower(owner) = '
                'lower(coalesce($1, upper(current_user))) '
                'AND table_name = $2',
                (self._kes_oracle_owner(schema), catalog_table_name),
            ).first()
        if row is None:
            if (
                self.kes_mode == 'oracle'
                and self.has_table(
                    connection, table_name, schema=schema, **kw
                )
            ):
                return {'text': None}
            from sqlalchemy import exc
            raise exc.NoSuchTableError(table_name)
        return {'text': row[0] or None}

    @reflection.cache
    def get_table_options(self, connection, table_name, schema=None, **kw):
        if not self.has_table(
                connection, table_name, schema=schema, **kw):
            from sqlalchemy import exc
            raise exc.NoSuchTableError(table_name)
        # KES exposes storage details that do not map cleanly back to MySQL
        # CREATE TABLE options.  Returning no options keeps reflected DDL
        # portable within KES MySQL mode.
        return {}

    def _kes_key_rows(
            self, connection, table_name, schema, constraint_type):
        if self.kes_mode == 'oracle':
            type_code = {
                'PRIMARY KEY': 'P',
                'UNIQUE': 'U',
            }[constraint_type]
            catalog_table_name = self._kes_oracle_name(table_name)
            rows = connection.exec_driver_sql(
                'SELECT cons.constraint_name, cols.column_name, '
                'cols.position '
                'FROM all_constraints cons JOIN all_cons_columns cols '
                'ON lower(cons.owner) = lower(cols.owner) '
                'AND lower(cons.constraint_name) = '
                'lower(cols.constraint_name) '
                'WHERE lower(cons.owner) = '
                'lower(coalesce($1, upper(current_user))) '
                'AND cons.table_name = $2 '
                'AND cons.constraint_type = $3 '
                'ORDER BY cons.constraint_name, cols.position',
                (self._kes_oracle_owner(schema), catalog_table_name,
                 type_code),
            ).all()
            return [(
                self.normalize_name(row[0]),
                self.normalize_name(row[1]),
                row[2],
            ) for row in rows]

        return connection.exec_driver_sql(
            'SELECT tc.constraint_name, kcu.column_name, '
            'kcu.ordinal_position '
            'FROM information_schema.table_constraints AS tc '
            'JOIN information_schema.key_column_usage AS kcu '
            'ON tc.constraint_catalog = kcu.constraint_catalog '
            'AND tc.constraint_schema = kcu.constraint_schema '
            'AND tc.constraint_name = kcu.constraint_name '
            'WHERE tc.table_schema = $1 AND tc.table_name = $2 '
            'AND tc.constraint_type = $3 '
            'ORDER BY tc.constraint_name, kcu.ordinal_position',
            (self._kes_schema(schema), table_name, constraint_type),
        ).all()

    @reflection.cache
    def get_pk_constraint(
            self, connection, table_name, schema=None, **kw):
        rows = self._kes_key_rows(
            connection, table_name, schema, 'PRIMARY KEY')
        if not rows:
            return {'name': None, 'constrained_columns': []}
        return {
            'name': rows[0][0],
            'constrained_columns': [row[1] for row in rows],
        }

    @reflection.cache
    def get_unique_constraints(
            self, connection, table_name, schema=None, **kw):
        rows = self._kes_key_rows(
            connection, table_name, schema, 'UNIQUE')
        constraints = {}
        for name, column, _ in rows:
            constraints.setdefault(name, []).append(column)
        return [{
            'name': name,
            'column_names': columns,
            'duplicates_index': name,
        } for name, columns in sorted(constraints.items())]

    @reflection.cache
    def get_foreign_keys(
            self, connection, table_name, schema=None, **kw):
        if self.kes_mode == 'mysql':
            rows = connection.exec_driver_sql(
                'SELECT kcu.constraint_name, kcu.column_name, '
                'kcu.referenced_table_schema, kcu.referenced_table_name, '
                'kcu.referenced_column_name, rc.update_rule, '
                'rc.delete_rule, rc.match_option '
                'FROM information_schema.key_column_usage AS kcu '
                'JOIN information_schema.referential_constraints AS rc '
                'ON kcu.constraint_catalog = rc.constraint_catalog '
                'AND kcu.constraint_schema = rc.constraint_schema '
                'AND kcu.constraint_name = rc.constraint_name '
                'WHERE kcu.table_schema = $1 AND kcu.table_name = $2 '
                'ORDER BY kcu.constraint_name, kcu.ordinal_position',
                (self._kes_schema(schema), table_name),
            ).all()
        elif self.kes_mode == 'sqlserver':
            rows = connection.exec_driver_sql(
                'SELECT con.conname, src_attr.attname, ref_ns.nspname, '
                'ref.relname, ref_attr.attname, con.confupdtype, '
                'con.confdeltype, con.confmatchtype '
                'FROM pg_catalog.pg_constraint AS con '
                'JOIN pg_catalog.pg_class AS src ON src.oid = con.conrelid '
                'JOIN pg_catalog.pg_namespace AS src_ns '
                'ON src_ns.oid = src.relnamespace '
                'JOIN pg_catalog.pg_class AS ref ON ref.oid = con.confrelid '
                'JOIN pg_catalog.pg_namespace AS ref_ns '
                'ON ref_ns.oid = ref.relnamespace '
                'JOIN LATERAL unnest(con.conkey) WITH ORDINALITY '
                'AS src_key(attnum, position) ON true '
                'JOIN LATERAL unnest(con.confkey) WITH ORDINALITY '
                'AS ref_key(attnum, position) '
                'ON ref_key.position = src_key.position '
                'JOIN pg_catalog.pg_attribute AS src_attr '
                'ON src_attr.attrelid = src.oid '
                'AND src_attr.attnum = src_key.attnum '
                'JOIN pg_catalog.pg_attribute AS ref_attr '
                'ON ref_attr.attrelid = ref.oid '
                'AND ref_attr.attnum = ref_key.attnum '
                "WHERE con.contype = 'f' AND src_ns.nspname = $1 "
                'AND src.relname = $2 '
                'ORDER BY con.conname, src_key.position',
                (self._kes_schema(schema), table_name),
            ).all()
            action_names = {
                'a': 'NO ACTION',
                'r': 'RESTRICT',
                'c': 'CASCADE',
                'n': 'SET NULL',
                'd': 'SET DEFAULT',
            }
            match_names = {'f': 'FULL', 'p': 'PARTIAL', 's': None}
            rows = [(
                row[0], row[1], row[2], row[3], row[4],
                action_names[self._kes_catalog_char(row[5])],
                action_names[self._kes_catalog_char(row[6])],
                match_names[self._kes_catalog_char(row[7])],
            ) for row in rows]
        else:
            catalog_table_name = self._kes_oracle_name(table_name)
            rows = connection.exec_driver_sql(
                'SELECT fk.constraint_name, fkc.column_name, '
                'pk.owner, pk.table_name, pkc.column_name, '
                'NULL, fk.delete_rule, NULL '
                'FROM all_constraints fk '
                'JOIN (SELECT owner, constraint_name, column_name, '
                'position, ROW_NUMBER() OVER ('
                'PARTITION BY owner, constraint_name ORDER BY position) '
                'AS key_position FROM all_cons_columns) fkc '
                'ON lower(fk.owner) = lower(fkc.owner) '
                'AND lower(fk.constraint_name) = '
                'lower(fkc.constraint_name) '
                'JOIN all_constraints pk '
                'ON lower(fk.r_owner) = lower(pk.owner) '
                'AND lower(fk.r_constraint_name) = '
                'lower(pk.constraint_name) '
                'JOIN (SELECT owner, constraint_name, column_name, '
                'position, ROW_NUMBER() OVER ('
                'PARTITION BY owner, constraint_name ORDER BY position) '
                'AS key_position FROM all_cons_columns) pkc '
                'ON lower(pk.owner) = lower(pkc.owner) '
                'AND lower(pk.constraint_name) = '
                'lower(pkc.constraint_name) '
                'AND fkc.key_position = pkc.key_position '
                "WHERE fk.constraint_type = 'R' "
                'AND lower(fk.owner) = '
                'lower(coalesce($1, upper(current_user))) '
                'AND fk.table_name = $2 '
                'ORDER BY fk.constraint_name, fkc.key_position',
                (self._kes_oracle_owner(schema), catalog_table_name),
            ).all()
        constraints = {}
        for row in rows:
            if self.kes_mode == 'oracle':
                referred_owner = self.normalize_name(row[2])
                row = (
                    self.normalize_name(row[0]),
                    self.normalize_name(row[1]),
                    referred_owner,
                    self.normalize_name(row[3]),
                    self.normalize_name(row[4]),
                    row[5], row[6], row[7],
                )
            item = constraints.setdefault(row[0], {
                'name': row[0],
                'constrained_columns': [],
                'referred_schema': row[2],
                'referred_table': row[3],
                'referred_columns': [],
                'options': {},
            })
            item['constrained_columns'].append(row[1])
            item['referred_columns'].append(row[4])
            if row[5] not in {None, 'NO ACTION'}:
                item['options']['onupdate'] = row[5]
            if row[6] not in {None, 'NO ACTION'}:
                item['options']['ondelete'] = row[6]
            if row[7] not in {None, 'NONE'}:
                item['options']['match'] = row[7]
        return [constraints[name] for name in sorted(constraints)]

    @reflection.cache
    def get_check_constraints(
            self, connection, table_name, schema=None,
            include_all=False, **kw):
        if self.kes_mode == 'oracle':
            catalog_table_name = self._kes_oracle_name(table_name)
            rows = connection.exec_driver_sql(
                'SELECT constraint_name, search_condition, generated '
                'FROM all_constraints '
                'WHERE lower(owner) = '
                'lower(coalesce($1, upper(current_user))) '
                'AND table_name = $2 '
                "AND constraint_type = 'C' "
                'ORDER BY constraint_name',
                (self._kes_oracle_owner(schema), catalog_table_name),
            ).all()
            if not include_all:
                rows = [row for row in rows if row[2] != 'GENERATED NAME']
            return [{
                'name': self.normalize_name(row[0]),
                'sqltext': self._kes_oracle_expression(
                    row[1], check=True),
            } for row in rows]

        rows = connection.exec_driver_sql(
            'SELECT tc.constraint_name, cc.check_clause '
            'FROM information_schema.table_constraints AS tc '
            'JOIN information_schema.check_constraints AS cc '
            'ON tc.constraint_catalog = cc.constraint_catalog '
            'AND tc.constraint_schema = cc.constraint_schema '
            'AND tc.constraint_name = cc.constraint_name '
            'WHERE tc.table_schema = $1 AND tc.table_name = $2 '
            "AND tc.constraint_type = 'CHECK' "
            'ORDER BY tc.constraint_name',
            (self._kes_schema(schema), table_name),
        ).all()
        if not include_all:
            rows = [row for row in rows
                    if not row[0].lower().endswith('_not_null')]
        return [{'name': row[0], 'sqltext': row[1]} for row in rows]

    @reflection.cache
    def get_indexes(self, connection, table_name, schema=None, **kw):
        if self.kes_mode in {'mysql', 'sqlserver'}:
            rows = connection.exec_driver_sql(
                'SELECT idx.relname, attr.attname, NOT ind.indisunique, '
                'ord.position, NULL, '
                'CASE WHEN ord.attnum = 0 THEN '
                'pg_get_indexdef(ind.indexrelid, ord.position, true) '
                'ELSE NULL END '
                'FROM pg_catalog.pg_class AS tbl '
                'JOIN pg_catalog.pg_namespace AS ns '
                'ON ns.oid = tbl.relnamespace '
                'JOIN pg_catalog.pg_index AS ind ON ind.indrelid = tbl.oid '
                'JOIN pg_catalog.pg_class AS idx '
                'ON idx.oid = ind.indexrelid '
                'JOIN LATERAL unnest(ind.indkey) WITH ORDINALITY '
                'AS ord(attnum, position) ON true '
                'LEFT JOIN pg_catalog.pg_attribute AS attr '
                'ON attr.attrelid = tbl.oid AND attr.attnum = ord.attnum '
                'WHERE ns.nspname = $1 AND tbl.relname = $2 '
                'AND NOT ind.indisprimary '
                'ORDER BY idx.relname, ord.position',
                (self._kes_schema(schema), table_name),
            ).all()
        else:
            catalog_table_name = self._kes_oracle_name(table_name)
            rows = connection.exec_driver_sql(
                'SELECT i.index_name, c.column_name, '
                "CASE i.uniqueness WHEN 'UNIQUE' THEN 0 ELSE 1 END, "
                'c.column_position, NULL, NULL '
                'FROM all_indexes i JOIN all_ind_columns c '
                'ON lower(i.owner) = lower(c.index_owner) '
                'AND lower(i.index_name) = lower(c.index_name) '
                'WHERE lower(i.table_owner) = '
                'lower(coalesce($1, upper(current_user))) '
                'AND i.table_name = $2 '
                'ORDER BY i.index_name, c.column_position',
                (self._kes_oracle_owner(schema), catalog_table_name),
            ).all()

        primary = self.get_pk_constraint(
            connection, table_name, schema=schema, **kw)['name']
        unique_names = {
            item['name'].lower() for item in self.get_unique_constraints(
                connection, table_name, schema=schema, **kw)
            if item['name'] is not None
        }
        indexes = {}
        for name, column, non_unique, _, sub_part, expression in rows:
            if self.kes_mode == 'oracle':
                name = self.normalize_name(name)
                column = self.normalize_name(column)
            if name == primary or name.lower() == str(primary).lower():
                continue
            item = indexes.setdefault(name, {
                'name': name,
                'column_names': [],
                'unique': not bool(non_unique),
            })
            item['column_names'].append(column)
            if expression is not None:
                item.setdefault('expressions', []).append(expression)
            if sub_part is not None:
                lengths = item.setdefault(
                    'dialect_options', {}).setdefault('mysql_length', {})
                lengths[column] = sub_part
            if name.lower() in unique_names:
                item['duplicates_constraint'] = name
        return [indexes[name] for name in sorted(indexes)]


class _KESMySQLExecutionContext(MySQLExecutionContext):

    def create_server_side_cursor(self):
        return self._dbapi_connection.cursor(server_side=True)

    def get_lastrowid(self):
        return self.root_connection.exec_driver_sql(
            'SELECT LAST_INSERT_ID()').scalar()


class _KESMySQLDDLCompiler(MySQLDDLCompiler):

    def visit_computed_column(self, generated, **kw):
        text = super().visit_computed_column(generated, **kw)
        if generated.persisted is None:
            text += ' STORED'
        return text

    def visit_drop_index(self, drop, **kw):
        return DDLCompiler.visit_drop_index(self, drop, **kw)


class _KESOracleCompiler(OracleCompiler):

    def returning_clause(
            self, stmt, returning_cols, *, populate_result_map, **kw):
        return SQLCompiler.returning_clause(
            self, stmt, returning_cols,
            populate_result_map=populate_result_map, **kw)


class _KESSQLServerCompiler(MSSQLCompiler):

    returning_precedes_values = False
    visit_insert = SQLCompiler.visit_insert
    visit_update = SQLCompiler.visit_update
    visit_delete = SQLCompiler.visit_delete

    def returning_clause(
            self, stmt, returning_cols, *, populate_result_map, **kw):
        return SQLCompiler.returning_clause(
            self, stmt, returning_cols,
            populate_result_map=populate_result_map, **kw)


class _KESSQLServerDDLCompiler(MSDDLCompiler):

    visit_drop_index = DDLCompiler.visit_drop_index
    visit_set_table_comment = DDLCompiler.visit_set_table_comment
    visit_drop_table_comment = DDLCompiler.visit_drop_table_comment
    visit_set_column_comment = DDLCompiler.visit_set_column_comment
    visit_drop_column_comment = DDLCompiler.visit_drop_column_comment


class _KESOracleExecutionContext(OracleExecutionContext):

    def create_server_side_cursor(self):
        return self._dbapi_connection.cursor(server_side=True)


class _KESSQLServerExecutionContext(MSExecutionContext):

    def create_server_side_cursor(self):
        return self._dbapi_connection.cursor(server_side=True)


class _KESOracleIdentifierPreparer(OracleIdentifierPreparer):

    def __init__(self, dialect, **kwargs):
        super().__init__(dialect, omit_schema=True, **kwargs)

    def schema_for_object(self, obj):
        return None


class KESMySQLDialect_asyncpg(_KESAsyncpgDialectMixin, MySQLDialect):
    """SQLAlchemy dialect using MySQL SQL with the asyncpg KES transport."""

    name = 'mysql'
    kes_mode = 'mysql'
    execution_ctx_cls = _KESMySQLExecutionContext
    ddl_compiler = _KESMySQLDDLCompiler
    supports_statement_cache = True
    supports_server_side_cursors = True
    _isolation_lookup = {
        'AUTOCOMMIT': 'autocommit',
        'READ COMMITTED': 'read_committed',
        'READ UNCOMMITTED': 'read_uncommitted',
        'REPEATABLE READ': 'repeatable_read',
        'SERIALIZABLE': 'serializable',
    }

    def _detect_charset(self, connection):
        return 'utf8'

    def _get_default_schema_name(self, connection):
        return connection.exec_driver_sql('SELECT current_schema').scalar()

    def _detect_sql_mode(self, connection):
        # KES MySQL mode does not expose MySQL's SHOW VARIABLES interface.
        self._sql_mode = ''

    def _detect_casing(self, connection):
        self._casing = 0
        return self._casing

    def _parse_server_version(self, value):
        version = _parse_kes_version(value)
        self._set_mariadb(False, version)
        self._mariadb_normalized_version_info = version
        self.server_version_info = version
        return version


class KESOracleDialect_asyncpg(_KESAsyncpgDialectMixin, OracleDialect):
    """SQLAlchemy dialect using Oracle SQL with the asyncpg KES transport."""

    name = 'oracle'
    kes_mode = 'oracle'
    statement_compiler = _KESOracleCompiler
    execution_ctx_cls = _KESOracleExecutionContext
    preparer = _KESOracleIdentifierPreparer
    supports_statement_cache = True
    supports_server_side_cursors = True
    supports_identity_columns = True
    _isolation_lookup = {
        'AUTOCOMMIT': 'autocommit',
        'READ COMMITTED': 'read_committed',
        'SERIALIZABLE': 'serializable',
    }

    # KES Oracle mode returns rows for RETURNING without an INTO clause.
    insert_returning = True
    insert_executemany_returning = True
    update_returning = True
    delete_returning = True

    def initialize(self, connection):
        self._kes_default_owner = connection.exec_driver_sql(
            'SELECT CASE WHEN current_user = lower(current_user) '
            'THEN upper(current_user) ELSE current_user END FROM dual'
        ).scalar()
        super().initialize(connection)
        # KES product versions are not Oracle compatibility versions.
        self.supports_identity_columns = True
        self._supports_offset_fetch = self.enable_offset_fetch

    @reflection.cache
    def get_sequence_names(self, connection, schema=None, **kw):
        rows = connection.exec_driver_sql(
            'SELECT sequence_name FROM all_sequences '
            'WHERE lower(sequence_owner) = '
            'lower(coalesce($1, upper(current_user))) '
            'ORDER BY sequence_name',
            (self._kes_oracle_owner(schema),))
        return [self.normalize_name(row[0]) for row in rows]

    @reflection.cache
    def has_sequence(
            self, connection, sequence_name, schema=None, **kw):
        catalog_sequence_name = self._kes_oracle_name(sequence_name)
        row = connection.exec_driver_sql(
            'SELECT 1 FROM all_sequences '
            'WHERE lower(sequence_owner) = '
            'lower(coalesce($1, upper(current_user))) '
            'AND sequence_name = $2',
            (self._kes_oracle_owner(schema), catalog_sequence_name),
        ).first()
        return row is not None

    def _get_server_version_info(self, connection):
        value = connection.exec_driver_sql('SELECT version()').scalar()
        return _parse_kes_version(value)


class KESSQLServerDialect_asyncpg(_KESAsyncpgDialectMixin, MSDialect):
    """SQLAlchemy dialect using SQL Server SQL with asyncpg KES transport."""

    name = 'mssql'
    kes_mode = 'sqlserver'
    statement_compiler = _KESSQLServerCompiler
    ddl_compiler = _KESSQLServerDDLCompiler
    execution_ctx_cls = _KESSQLServerExecutionContext
    supports_statement_cache = True
    supports_server_side_cursors = True
    _isolation_lookup = {
        'AUTOCOMMIT': 'autocommit',
        'READ COMMITTED': 'read_committed',
        'READ UNCOMMITTED': 'read_uncommitted',
        'REPEATABLE READ': 'repeatable_read',
        'SERIALIZABLE': 'serializable',
    }

    def _get_default_schema_name(self, connection):
        return connection.exec_driver_sql('SELECT current_schema()').scalar()

    def initialize(self, connection):
        super().initialize(connection)
        self.supports_comments = True

    def _get_server_version_info(self, connection):
        value = connection.exec_driver_sql('SELECT version()').scalar()
        return _parse_kes_version(value)
