# Copyright (C) 2016-present the asyncpg authors and contributors
# <see AUTHORS file>

"""KingbaseES compatibility-mode support for asyncpg."""

from __future__ import annotations

import datetime
from decimal import Decimal
import re
import uuid

from . import exceptions


MODES = frozenset({'mysql', 'oracle', 'sqlserver'})

_PG_EPOCH_DATE = datetime.date(2000, 1, 1)
_PG_EPOCH_DATETIME = datetime.datetime(2000, 1, 1)
_DATE_POS_INFINITY = 2**31 - 1
_DATE_NEG_INFINITY = -(2**31)
_TIMESTAMP_POS_INFINITY = 2**63 - 1
_TIMESTAMP_NEG_INFINITY = -(2**63)

_MYSQL_TIME_RE = re.compile(
    r'(?P<sign>-?)(?P<hours>\d{1,3}):(?P<minutes>\d{2}):'
    r'(?P<seconds>\d{2})(?:\.(?P<fraction>\d{1,6}))?\Z')
_DEALLOCATE_RE = re.compile(
    r'\A\s*DEALLOCATE(?:\s+PREPARE)?\s+'
    r'(?P<name>ALL|"(?:[^"]|"")+"|[A-Za-z_][A-Za-z0-9_$]*)\s*;?\s*\Z',
    re.IGNORECASE)


TYPE_LOOKUP_QUERY = '''\
SELECT
    t.oid,
    n.nspname AS schema_name,
    t.typname AS type_name,
    t.typtype AS type_kind,
    base_ns.nspname AS base_schema_name,
    base.typname AS base_type_name
FROM pg_catalog.pg_type AS t
JOIN pg_catalog.pg_namespace AS n ON n.oid = t.typnamespace
LEFT JOIN pg_catalog.pg_type AS base ON base.oid = t.typbasetype
LEFT JOIN pg_catalog.pg_namespace AS base_ns
    ON base_ns.oid = base.typnamespace
WHERE n.nspname IN ('pg_catalog', 'sys')
  AND t.typname IN (
      'binary', 'varbinary', 'tinyint', 'uint4', 'uint8',
      'bpcharbyte', 'varcharbyte', 'bit', 'json', 'mysql_json',
      'date', 'time', 'datetime', 'timestamp',
      'datetime2', 'smalldatetime', 'uniqueidentifier',
      'money', 'smallmoney', 'nchar', 'nvarchar', 'rowversion',
      'dsinterval', 'yminterval', 'rowid', 'urowid', 'bfile'
  )
'''


def normalize_mode(mode):
    if mode is None:
        return None
    if not isinstance(mode, str) or mode.lower() not in MODES:
        raise exceptions.ClientConfigurationError(
            "kes_mode is expected to be 'mysql', 'oracle', "
            "'sqlserver', or None, "
            'got {!r}'.format(mode))
    return mode.lower()


def adapt_introspection_query(query, mode):
    if mode == 'sqlserver':
        return query.replace('$1::oid[]', '$1::pg_catalog._oid')
    return query


def deallocated_statement(query):
    match = _DEALLOCATE_RE.fullmatch(query)
    if match is None:
        return None
    name = match.group('name')
    if name.upper() == 'ALL':
        return True
    if name.startswith('"'):
        return name[1:-1].replace('""', '"')
    return name


def _encode_date(value):
    if isinstance(value, datetime.datetime):
        value = value.date()
    elif not isinstance(value, datetime.date):
        raise TypeError(
            'expected a datetime.date or datetime.datetime instance, '
            'got {!r}'.format(type(value).__name__))
    return value.isoformat()


def _decode_date(value):
    if value == 'infinity':
        return datetime.date.max
    if value == '-infinity':
        return datetime.date.min
    return datetime.date.fromisoformat(value)


def _encode_time(value):
    if isinstance(value, datetime.timedelta):
        total_microseconds = (
            value.days * 86400_000000
            + value.seconds * 1_000000
            + value.microseconds
        )
        sign = '-' if total_microseconds < 0 else ''
        total_microseconds = abs(total_microseconds)
        total_seconds, microseconds = divmod(total_microseconds, 1_000000)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        result = '{}{}:{:02d}:{:02d}'.format(
            sign, hours, minutes, seconds)
        if microseconds:
            result += '.{:06d}'.format(microseconds).rstrip('0')
        return result
    if not isinstance(value, datetime.time):
        raise TypeError(
            'expected a datetime.time or datetime.timedelta instance, '
            'got {!r}'.format(type(value).__name__))
    return value.isoformat()


def _encode_datetime(value):
    if isinstance(value, datetime.datetime):
        if value.utcoffset() is not None:
            raise TypeError(
                "can't subtract offset-naive and offset-aware datetimes")
    elif isinstance(value, datetime.date):
        value = datetime.datetime(value.year, value.month, value.day)
    else:
        raise TypeError(
            'expected a datetime.date or datetime.datetime instance, '
            'got {!r}'.format(type(value).__name__))
    return value.isoformat(' ')


def _normalize_fractional_seconds(value):
    head, separator, fraction = value.rpartition('.')
    if not separator or not fraction.isdigit():
        return value
    if len(fraction) < 6:
        fraction = fraction.ljust(6, '0')
    return head + separator + fraction


def _decode_time(value):
    match = _MYSQL_TIME_RE.fullmatch(value)
    if match is None:
        return datetime.time.fromisoformat(
            _normalize_fractional_seconds(value))

    hours = int(match.group('hours'))
    minutes = int(match.group('minutes'))
    seconds = int(match.group('seconds'))
    if minutes >= 60 or seconds >= 60:
        raise ValueError('invalid MySQL TIME value: {!r}'.format(value))
    fraction = match.group('fraction') or ''
    microseconds = int(fraction.ljust(6, '0')) if fraction else 0

    if not match.group('sign') and hours < 24:
        return datetime.time(hours, minutes, seconds, microseconds)

    result = datetime.timedelta(
        hours=hours, minutes=minutes, seconds=seconds,
        microseconds=microseconds)
    if match.group('sign'):
        result = -result
    return result


def _decode_datetime(value):
    if value == 'infinity':
        return datetime.datetime.max
    if value == '-infinity':
        return datetime.datetime.min
    return datetime.datetime.fromisoformat(
        _normalize_fractional_seconds(value))


def _require_singleton_tuple(value, type_name):
    if not isinstance(value, tuple) or len(value) != 1:
        raise TypeError(
            '{} tuple codec encoder must return a one-element tuple'.format(
                type_name))
    return value[0]


def _require_singleton_integer_tuple(value, type_name):
    item = _require_singleton_tuple(value, type_name)
    if isinstance(item, (str, bytes, bytearray, memoryview)):
        raise TypeError('an integer is required')
    try:
        return int(item)
    except (TypeError, ValueError, OverflowError):
        raise TypeError('an integer is required') from None


def _adapt_date_tuple_codec(encoder, decoder):
    def encode_date_tuple(value):
        days = _require_singleton_integer_tuple(encoder(value), 'date')
        if days == _DATE_POS_INFINITY:
            return 'infinity'
        if days == _DATE_NEG_INFINITY:
            return '-infinity'
        return (_PG_EPOCH_DATE + datetime.timedelta(days=days)).isoformat()

    def decode_date_tuple(value):
        if value == 'infinity':
            raw = (_DATE_POS_INFINITY,)
        elif value == '-infinity':
            raw = (_DATE_NEG_INFINITY,)
        else:
            decoded = datetime.datetime.fromisoformat(value).date()
            raw = ((decoded - _PG_EPOCH_DATE).days,)
        return decoder(raw)

    return encode_date_tuple, decode_date_tuple


def _adapt_time_tuple_codec(encoder, decoder):
    def encode_time_tuple(value):
        microseconds = _require_singleton_integer_tuple(
            encoder(value), 'time')
        if not 0 <= microseconds < 86400_000000:
            raise ValueError(
                'time tuple value must be in the range [0, 86400000000)')
        hours, remainder = divmod(microseconds, 3600_000000)
        minutes, remainder = divmod(remainder, 60_000000)
        seconds, fraction = divmod(remainder, 1_000000)
        result = '{:02d}:{:02d}:{:02d}'.format(hours, minutes, seconds)
        if fraction:
            result += '.{:06d}'.format(fraction).rstrip('0')
        return result

    def decode_time_tuple(value):
        decoded = _decode_time(value)
        if not isinstance(decoded, datetime.time):
            raise ValueError(
                'KES MySQL TIME outside the PostgreSQL time range')
        raw = ((
            decoded.hour * 3600_000000
            + decoded.minute * 60_000000
            + decoded.second * 1_000000
            + decoded.microsecond
        ),)
        return decoder(raw)

    return encode_time_tuple, decode_time_tuple


def _adapt_timestamp_tuple_codec(encoder, decoder):
    def encode_timestamp_tuple(value):
        microseconds = _require_singleton_integer_tuple(
            encoder(value), 'timestamp')
        if microseconds == _TIMESTAMP_POS_INFINITY:
            return 'infinity'
        if microseconds == _TIMESTAMP_NEG_INFINITY:
            return '-infinity'
        result = _PG_EPOCH_DATETIME + datetime.timedelta(
            microseconds=microseconds)
        return result.isoformat(' ')

    def decode_timestamp_tuple(value):
        if value == 'infinity':
            raw = (_TIMESTAMP_POS_INFINITY,)
        elif value == '-infinity':
            raw = (_TIMESTAMP_NEG_INFINITY,)
        else:
            delta = _decode_datetime(value) - _PG_EPOCH_DATETIME
            raw = ((
                delta.days * 86400_000000
                + delta.seconds * 1_000000
                + delta.microseconds
            ),)
        return decoder(raw)

    return encode_timestamp_tuple, decode_timestamp_tuple


def _encode_binary(value):
    try:
        return memoryview(value).tobytes()
    except TypeError:
        raise TypeError(
            "a bytes-like object is required, not {!r}".format(
                type(value).__name__)) from None


def _encode_text(value):
    if not isinstance(value, str):
        raise TypeError(
            'expected str, got {}'.format(type(value).__name__))
    return value


def _encode_text_binary(value):
    return _encode_text(value).encode('utf-8')


def _decode_text_binary(value):
    return value.decode('utf-8')


def _encode_integer(value):
    if isinstance(value, (str, bytes, bytearray, memoryview)):
        raise TypeError(
            "{!r} object cannot be interpreted as an integer".format(
                type(value).__name__))
    return str(int(value))


def _encode_boolean(value):
    if not isinstance(value, bool):
        raise TypeError(
            'expected bool, got {}'.format(type(value).__name__))
    return '1' if value else '0'


def _decode_boolean(value):
    if value in {'1', 't', 'true', 'TRUE'}:
        return True
    if value in {'0', 'f', 'false', 'FALSE'}:
        return False
    raise ValueError('invalid boolean value: {!r}'.format(value))


def _encode_decimal(value):
    if isinstance(value, (str, bytes, bytearray, memoryview)):
        raise TypeError(
            'expected a number, got {}'.format(type(value).__name__))
    try:
        return str(Decimal(value))
    except (TypeError, ValueError, ArithmeticError):
        raise TypeError(
            'expected a number, got {}'.format(type(value).__name__)) from None


def _encode_uuid(value):
    if not isinstance(value, uuid.UUID):
        raise TypeError(
            'expected uuid.UUID, got {}'.format(type(value).__name__))
    return str(value)


def _encode_dsinterval(value):
    if isinstance(value, datetime.timedelta):
        total_microseconds = (
            value.days * 86400_000000
            + value.seconds * 1_000000
            + value.microseconds
        )
        sign = '-' if total_microseconds < 0 else ''
        total_microseconds = abs(total_microseconds)
        days, remainder = divmod(total_microseconds, 86400_000000)
        hours, remainder = divmod(remainder, 3600_000000)
        minutes, remainder = divmod(remainder, 60_000000)
        seconds, microseconds = divmod(remainder, 1_000000)
        return '{}{} {:02d}:{:02d}:{:02d}.{:06d}'.format(
            sign, days, hours, minutes, seconds, microseconds)
    return _encode_text(value)


def _decode_mysql_bit(value):
    if value.startswith(('0x', '0X')):
        return bytes.fromhex(value[2:])
    return value.encode('ascii')


def _encode_mysql_bit(value):
    if isinstance(value, int):
        if value < 0:
            raise ValueError('BIT values cannot be negative')
        width = max(1, (value.bit_length() + 7) // 8)
        value = value.to_bytes(width, 'big')
    if isinstance(value, (bytes, bytearray, memoryview)):
        return '0x' + bytes(value).hex()
    return _encode_text(value)


# (schema, type): (encoder, decoder, wire format)
_MYSQL_CODECS = {
    ('pg_catalog', 'binary'): (_encode_binary, bytes, 'binary'),
    ('pg_catalog', 'varbinary'): (_encode_binary, bytes, 'binary'),
    ('pg_catalog', 'tinyint'): (_encode_integer, int, 'text'),
    ('pg_catalog', 'uint4'): (_encode_integer, int, 'text'),
    ('pg_catalog', 'uint8'): (_encode_integer, int, 'text'),
    ('pg_catalog', 'bpcharbyte'): (_encode_text, str, 'text'),
    ('pg_catalog', 'varcharbyte'): (_encode_text, str, 'text'),
    ('sys', 'binary'): (_encode_binary, bytes, 'binary'),
    ('sys', 'varbinary'): (_encode_binary, bytes, 'binary'),
    ('sys', 'tinyint'): (_encode_integer, int, 'text'),
    ('sys', 'uint4'): (_encode_integer, int, 'text'),
    ('sys', 'uint8'): (_encode_integer, int, 'text'),
    ('sys', 'bpcharbyte'): (_encode_text, str, 'text'),
    ('sys', 'varcharbyte'): (_encode_text, str, 'text'),
    ('sys', 'bit'): (_encode_mysql_bit, _decode_mysql_bit, 'text'),
    ('sys', 'json'): (_encode_text, str, 'text'),
    ('sys', 'mysql_json'): (_encode_text, str, 'text'),
    ('sys', 'date'): (_encode_date, _decode_date, 'text'),
    ('sys', 'time'): (_encode_time, _decode_time, 'text'),
    ('sys', 'datetime'): (
        _encode_datetime, _decode_datetime, 'text'),
    ('sys', 'timestamp'): (
        _encode_datetime, _decode_datetime, 'text'),
}


_ORACLE_CODECS = {
    ('sys', 'dsinterval'): (_encode_dsinterval, str, 'text'),
    ('sys', 'yminterval'): (_encode_text, str, 'text'),
    ('sys', 'varbinary'): (_encode_binary, bytes, 'binary'),
    ('sys', 'bpcharbyte'): (_encode_text, str, 'text'),
    ('sys', 'varcharbyte'): (_encode_text, str, 'text'),
    ('pg_catalog', 'rowid'): (_encode_text, str, 'text'),
    ('pg_catalog', 'urowid'): (_encode_text, str, 'text'),
    ('pg_catalog', 'bfile'): (_encode_text, str, 'text'),
}


_SQLSERVER_CODECS = {
    ('sys', 'binary'): (_encode_binary, bytes, 'binary'),
    ('sys', 'varbinary'): (_encode_binary, bytes, 'binary'),
    ('sys', 'rowversion'): (_encode_binary, bytes, 'binary'),
    ('sys', 'bpcharbyte'): (
        _encode_text_binary, _decode_text_binary, 'binary'),
    ('sys', 'varcharbyte'): (
        _encode_text_binary, _decode_text_binary, 'binary'),
    ('sys', 'bit'): (_encode_boolean, _decode_boolean, 'text'),
    ('sys', 'tinyint'): (_encode_integer, int, 'text'),
    ('sys', 'money'): (_encode_decimal, Decimal, 'text'),
    ('sys', 'date'): (_encode_date, _decode_date, 'text'),
    ('sys', 'time'): (_encode_time, _decode_time, 'text'),
    ('sys', 'datetime'): (
        _encode_datetime, _decode_datetime, 'text'),
    ('sys', 'datetime2'): (
        _encode_datetime, _decode_datetime, 'text'),
    ('sys', 'smalldatetime'): (
        _encode_datetime, _decode_datetime, 'text'),
    ('sys', 'nchar'): (
        _encode_text_binary, _decode_text_binary, 'binary'),
    ('sys', 'nvarchar'): (
        _encode_text_binary, _decode_text_binary, 'binary'),
    ('sys', 'uniqueidentifier'): (_encode_uuid, uuid.UUID, 'text'),
}


_CODECS_BY_MODE = {
    'mysql': _MYSQL_CODECS,
    'oracle': _ORACLE_CODECS,
    'sqlserver': _SQLSERVER_CODECS,
}


_MODE_MARKERS = {
    'mysql': frozenset({('sys', 'json'), ('sys', 'mysql_json')}),
    'oracle': frozenset({('sys', 'dsinterval')}),
    'sqlserver': frozenset({('sys', 'uniqueidentifier')}),
}

_MYSQL_CODEC_ALIAS_CANDIDATES = {
    ('pg_catalog', 'binary'): (('sys', 'binary'),),
    ('pg_catalog', 'bit'): (('sys', 'bit'),),
    ('pg_catalog', 'bpcharbyte'): (('sys', 'bpcharbyte'),),
    ('pg_catalog', 'date'): (('sys', 'date'),),
    ('pg_catalog', 'json'): (
        ('sys', 'json'), ('sys', 'mysql_json')),
    ('pg_catalog', 'time'): (('sys', 'time'),),
    ('pg_catalog', 'time without timezone'): (('sys', 'time'),),
    ('pg_catalog', 'timestamp'): (('sys', 'timestamp'),),
    ('pg_catalog', 'timestamp without timezone'): (('sys', 'timestamp'),),
    ('pg_catalog', 'tinyint'): (('sys', 'tinyint'),),
    ('pg_catalog', 'uint4'): (('sys', 'uint4'),),
    ('pg_catalog', 'uint8'): (('sys', 'uint8'),),
    ('pg_catalog', 'varbinary'): (('sys', 'varbinary'),),
    ('pg_catalog', 'varcharbyte'): (('sys', 'varcharbyte'),),
}

_ORACLE_CODEC_ALIASES = {
    ('pg_catalog', 'date'): ('pg_catalog', 'timestamp'),
}


def register_codecs(settings, rows, mode):
    discovered = {
        (row['schema_name'], row['type_name'].lower()) for row in rows
    }
    server_mode = getattr(settings, 'compatdb_mode', None)
    mode_matches = (
        server_mode.lower() == mode
        if isinstance(server_mode, str)
        else bool(_MODE_MARKERS[mode] & discovered)
    )
    if not mode_matches:
        raise exceptions.ClientConfigurationError(
            'kes_mode={!r} does not match the connected KingbaseES '
            'instance'.format(mode))

    for row in rows:
        register_codec(
            settings,
            row['oid'],
            row['type_name'],
            row['schema_name'],
            mode,
        )
    return (
        discover_codec_aliases(rows, mode),
        discover_codec_mirrors(rows, mode),
    )


def discover_codec_aliases(discovered, mode):
    if mode != 'mysql':
        return {}

    if isinstance(discovered, set):
        available = discovered
    else:
        available = {
            (row['schema_name'], row['type_name'].lower())
            for row in discovered
        }

    aliases = {}
    for requested, candidates in _MYSQL_CODEC_ALIAS_CANDIDATES.items():
        for candidate in candidates:
            if candidate in available:
                aliases[requested] = candidate
                break
    return aliases


def discover_codec_mirrors(discovered, mode):
    if mode != 'mysql' or isinstance(discovered, set):
        return {}

    mirrors = {}
    for row in discovered:
        if row.get('type_kind') not in {'d', b'd'}:
            continue
        base_schema = row.get('base_schema_name')
        base_name = row.get('base_type_name')
        if base_schema and base_name:
            mirrors[(
                row['schema_name'], row['type_name'].lower()
            )] = (base_schema, base_name.lower())
    return mirrors


def register_codec(settings, oid, name, schema, mode):
    codecs = _CODECS_BY_MODE[mode]
    codec = codecs.get((schema, name.lower()))
    if codec is None:
        return False

    encoder, decoder, data_format = codec
    settings.add_python_codec(
        oid, name, schema, None, 'scalar',
        encoder, decoder, data_format)
    return True


def codec_wire_format(mode, name, schema):
    codecs = _CODECS_BY_MODE.get(mode)
    if codecs is None:
        return None

    codec = codecs.get((schema, name.lower()))
    return codec[2] if codec is not None else None


def resolve_codec_type(mode, name, schema, aliases=None):
    if mode == 'mysql':
        key = (schema, name.lower())
        if aliases is not None:
            return aliases.get(key, (schema, name))
        candidates = _MYSQL_CODEC_ALIAS_CANDIDATES.get(key)
        if candidates:
            return candidates[0]
        return schema, name
    if mode == 'oracle':
        return _ORACLE_CODEC_ALIASES.get(
            (schema, name.lower()), (schema, name))
    return schema, name


def adapt_custom_codec(mode, requested_name, requested_schema,
                       encoder, decoder, data_format):
    requested_name = requested_name.lower()
    is_mysql_json_alias = (
        mode == 'mysql'
        and requested_schema == 'pg_catalog'
        and requested_name == 'json'
    )
    if is_mysql_json_alias and data_format == 'binary':
        def encode_mysql_json(value):
            return _encode_binary(encoder(value)).decode('utf-8')

        def decode_mysql_json(value):
            return decoder(value.encode('utf-8'))

        # KES MySQL rejects binary JSON array elements.  Preserve asyncpg's
        # bytes-facing custom codec API while using the supported text wire
        # representation for both scalar and array values.
        return encode_mysql_json, decode_mysql_json, 'text'

    is_temporal_tuple_alias = (
        mode in {'mysql', 'oracle'}
        and requested_schema == 'pg_catalog'
        and data_format == 'tuple'
    )
    if is_temporal_tuple_alias:
        if requested_name == 'date':
            encoder, decoder = _adapt_date_tuple_codec(encoder, decoder)
        elif (
            mode == 'mysql'
            and requested_name in {'time', 'time without timezone'}
        ):
            encoder, decoder = _adapt_time_tuple_codec(encoder, decoder)
        elif (
            mode == 'mysql'
            and requested_name in {
                'timestamp', 'timestamp without timezone'
            }
        ):
            encoder, decoder = _adapt_timestamp_tuple_codec(
                encoder, decoder)
        else:
            return encoder, decoder, data_format
        return encoder, decoder, 'text'

    return encoder, decoder, data_format


def start_transaction(mode, isolation, readonly, deferrable):
    if mode == 'mysql':
        if deferrable:
            raise exceptions.UnsupportedClientFeatureError(
                'KES MySQL mode does not support deferrable transactions')

        statements = []
        if isolation:
            statements.append(
                'SET TRANSACTION ISOLATION LEVEL ' +
                isolation.replace('_', ' ').upper())

        start = 'START TRANSACTION'
        if readonly:
            start += ' READ ONLY'
        statements.append(start)
        return ';\n'.join(statements) + ';'

    if mode == 'oracle':
        if isolation in {'read_uncommitted', 'repeatable_read'}:
            raise exceptions.UnsupportedClientFeatureError(
                'KES Oracle mode supports only read_committed and '
                'serializable isolation')
        if deferrable:
            raise exceptions.UnsupportedClientFeatureError(
                'KES Oracle mode does not support deferrable transactions')

        options = []
        if isolation:
            options.append(
                'ISOLATION LEVEL ' + isolation.replace('_', ' ').upper())
        if readonly:
            options.append('READ ONLY')

        statements = []
        if options:
            statements.append('SET TRANSACTION ' + ' '.join(options))

        # KES does not expose Oracle's implicit transaction start through
        # the PostgreSQL wire transaction status.  START TRANSACTION keeps
        # asyncpg's transaction/savepoint state synchronized with the server.
        statements.append('START TRANSACTION')
        return ';\n'.join(statements) + ';'

    if mode == 'sqlserver':
        if deferrable:
            raise exceptions.UnsupportedClientFeatureError(
                'KES SQL Server mode does not support deferrable '
                'transactions')

        statements = []
        if isolation:
            statements.append(
                'SET TRANSACTION ISOLATION LEVEL ' +
                isolation.replace('_', ' ').upper())

        start = 'BEGIN TRANSACTION'
        if readonly:
            start += ' READ ONLY'
        statements.append(start)
        return ';\n'.join(statements) + ';'

    raise exceptions.InternalClientError(
        'unexpected KES compatibility mode {!r}'.format(mode))


def savepoint(mode, name):
    if mode == 'sqlserver':
        return 'SAVE TRANSACTION {};'.format(name)
    return 'SAVEPOINT {};'.format(name)


def release_savepoint(mode, name):
    if mode in {'oracle', 'sqlserver'}:
        # These modes have no RELEASE SAVEPOINT statement.  A nested commit
        # simply keeps the changes in the enclosing transaction.
        return None
    return 'RELEASE SAVEPOINT {};'.format(name)


def rollback_to_savepoint(mode, name):
    if mode == 'mysql':
        return 'ROLLBACK TO SAVEPOINT {};'.format(name)
    if mode == 'sqlserver':
        return 'ROLLBACK TRANSACTION {};'.format(name)
    return 'ROLLBACK TO {};'.format(name)
