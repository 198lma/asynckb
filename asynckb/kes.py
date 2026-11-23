# Copyright (C) 2016-present the asyncpg authors and contributors
# <see AUTHORS file>

"""为 asynckb 提供 KingbaseES 兼容模式支持。"""

from __future__ import annotations

import datetime
from decimal import Decimal
import ipaddress
import re
import socket
import struct
import sys
import uuid

from . import exceptions


MODES = frozenset({'mysql', 'oracle', 'sqlserver'})


def client_mac_address(local_address):
    ("""Resolve the interface of the connected socket, """
     """never a guessed node ID.""")
    if sys.platform != 'linux':
        raise exceptions.InterfaceError(
            'KES client MAC upload currently requires Linux')
    if not isinstance(local_address, tuple):
        raise exceptions.InterfaceError(
            'KES client MAC upload requires a TCP connection')

    import fcntl

    address = ipaddress.ip_address(local_address[0].split('%', 1)[0])
    ipv6_interfaces = {}
    if address.version == 6:
        try:
            with open('/proc/net/if_inet6', encoding='ascii') as interfaces:
                for line in interfaces:
                    fields = line.split()
                    ipv6_interfaces[ipaddress.IPv6Address(
                        int(fields[0], 16))] = (fields[-1])
        except OSError as exc:
            raise exceptions.InterfaceError(
                'could not resolve the KES client IPv6 interface') from exc

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for _, name in socket.if_nameindex():
            request = struct.pack('256s', name.encode()[:15])
            try:
                if address.version == 4:
                    local_ip = socket.inet_ntoa(fcntl.ioctl(
                        sock, 0x8915, request)[20:24])  # SIOCGIFADDR
                    matches = local_ip == str(address)
                else:
                    matches = ipv6_interfaces.get(address) == name
                if matches:
                    mac = fcntl.ioctl(sock, 0x8927, request)[18:24]
                    return ':'.join(f'{octet:02x}' for octet in mac)
            except OSError:
                continue
    raise exceptions.InterfaceError(
        'could not resolve the KES client MAC address for the local socket')


_DETECTED_MODE_ALIASES = {
    'mysql': 'mysql',
    'oracle': 'oracle',
    'mssql': 'sqlserver',
    'sqlserver': 'sqlserver',
}

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
_CALL_RE = re.compile(r'\A\s*CALL\b', re.IGNORECASE)
_SQLSERVER_TOKEN_RE = re.compile(r'''
    --[^\r\n]*
    | (?P<comment>/\*)
    | (?P<string>[eE]?'|')
    | "(?:[^"]|"")*"
    | \[(?:[^\]]|\]\])*\]
    | (?P<dollar>\$(?:[^\W\d][\w]*)?\$)
    | (?P<parameter>\$[0-9]+)
    | [^\W\d][\w$]*
    | .
''', re.VERBOSE | re.DOTALL)
_PLACEHOLDER_TOKEN_RE = re.compile(r'''
    (?P<space>\s+)
    | (?P<line>--[^\r\n]*)
    | (?P<comment>/\*)
    | (?P<quote>[eEqQ]'|['"`])
    | (?P<dollar>\$(?:[^\W\d][\w]*)?\$)
    | (?P<parameter>\$[0-9]+)
    | (?P<colon>::|:=|:[0-9]+|:[^\W\d][\w$]*)
    | (?P<at>@@?[^\W\d][\w$]*)
    | (?P<question>\?\?|\?[|&]|\?)
    | (?P<word>[^\W\d][\w$]*)
    | (?P<other>.)
''', re.VERBOSE | re.DOTALL)


# KES 保留 PostgreSQL 类型目录，同时增加兼容模式类型。
# 认证后读取实际 OID，因为 OID 在不同数据库或物理连接之间不可移植，不能硬编码。
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
      'smallint', 'int', 'bigint',
      'numeric', 'real', 'float', 'text', 'ntext', 'sysname', 'image', 'xml',
      'bpcharbyte', 'varcharbyte', 'bit', 'json', 'mysql_json',
      'date', 'time', 'datetime', 'timestamp',
      'datetime2', 'smalldatetime', 'uniqueidentifier',
      'money', 'smallmoney', 'nchar', 'nvarchar', 'rowversion',
      'sql_variant',
      'dsinterval', 'yminterval', 'rowid', 'urowid', 'bfile'
  )
'''

ROUTINE_LOOKUP_QUERY = '''\
SELECT p.proargtypes, p.proallargtypes, p.proargmodes
FROM pg_catalog.pg_proc AS p
JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
WHERE p.proname = $1
  AND (($2::pg_catalog.text IS NULL
        AND pg_catalog.pg_function_is_visible(p.oid)) OR n.nspname = $2)
'''


def normalize_mode(mode):
    # 在建立网络连接前校验客户端显式配置，避免拼写错误选择非预期的兼容模式。
    if mode is None:
        return None
    if not isinstance(mode, str) or mode.lower() not in MODES:
        raise exceptions.ClientConfigurationError(
            "kes_mode is expected to be 'mysql', 'oracle', "
            "'sqlserver', or None, "
            'got {!r}'.format(mode))
    return mode.lower()


def normalize_detected_mode(mode):
    """规范化 KES 报告的模式；PostgreSQL 返回 None。"""
    # 不同 KES 版本可能将 SQL Server 模式报告为 `mssql` 或 `sqlserver`；
    # 无法识别的值表示不适用自动 KES 处理，将继续使用 asynckb 常规路径。
    if not isinstance(mode, str):
        return None
    return _DETECTED_MODE_ALIASES.get(mode.strip().lower())


def adapt_introspection_query(query, mode):
    # SQL Server 模式将 OID 数组类型公开为 `_oid`，而 asynckb 默认内省查询
    # 会将参数转换为 `oid[]`。
    if mode == 'sqlserver':
        # 内省必须使用已知的目录类型，不能递归依赖待发现的 sys._text。
        return (query.replace('$1::oid[]', '$1::pg_catalog._oid')
                .replace('::text', '::pg_catalog.text')
                .replace(' AS BIGINT)', ' AS pg_catalog.int8)'))
    return query


def deallocated_statement(query):
    # 规范化 KES DEALLOCATE 语法，使 Connection 能够使匹配的 asynckb 命名语句失效，
    # 而无需修改应用程序 SQL。
    match = _DEALLOCATE_RE.fullmatch(query)
    if match is None:
        return None
    name = match.group('name')
    if name.upper() == 'ALL':
        return True
    if name.startswith('"'):
        return name[1:-1].replace('""', '"')
    return name


def is_oracle_call(mode, query):
    """识别需要 KES 参数方向标记的 CALL，不改写 SQL 或参数值。"""
    if mode != 'oracle':
        return False
    pos = 0
    while pos < len(query):
        if query[pos].isspace():
            pos += 1
        elif query.startswith('--', pos):
            end = query.find('\n', pos + 2)
            if end < 0:
                return False
            pos = end + 1
        elif query.startswith('/*', pos):
            pos += 2
            depth = 1
            while pos < len(query) and depth:
                if query.startswith('/*', pos):
                    depth += 1
                    pos += 2
                elif query.startswith('*/', pos):
                    depth -= 1
                    pos += 2
                else:
                    pos += 1
            if depth:
                return False
        else:
            return _CALL_RE.match(query[pos:]) is not None
    return False


def sqlserver_parameter_count(query, *, standard_conforming_strings=True):
    ("""Count bind slots without interpreting literals, identifiers """
     """or comments.""")
    count = 0
    pos = 0
    while pos < len(query):
        token = _SQLSERVER_TOKEN_RE.match(query, pos)
        pos = token.end()
        if token.lastgroup == 'string':
            escapes = len(
                token.group()) == 2 or not standard_conforming_strings
            while pos < len(query):
                if query[pos] == "'":
                    pos += 1
                    if pos >= len(query) or query[pos] != "'":
                        break
                elif escapes and query[pos] == '\\':
                    pos += 1
                pos += 1
        elif token.lastgroup == 'parameter':
            count = max(count, int(token.group()[1:]))
            if count > 32767:
                raise exceptions.InterfaceError(
                    'the number of query arguments cannot exceed 32767')
        elif token.lastgroup == 'dollar':
            end = query.find(token.group(), pos)
            pos = len(query) if end < 0 else end + len(token.group())
        elif token.lastgroup == 'comment':
            depth = 1
            while pos < len(query) and depth:
                if query.startswith('/*', pos):
                    depth += 1
                    pos += 2
                elif query.startswith('*/', pos):
                    depth -= 1
                    pos += 2
                else:
                    pos += 1
    return count


def bind_parameter_oids(query, modes, *, standard_conforming_strings=True):
    ("""Declare KES bind directions while leaving type inference to """
     """the server.""")
    flags = {'in': 0x20000000, 'out': 0x40000000, 'inout': 0x60000000}
    if not isinstance(modes, (list, tuple)):
        raise exceptions.InterfaceError(
            'parameter_modes must be a list or tuple of in, out or inout')
    count = sqlserver_parameter_count(
        query, standard_conforming_strings=standard_conforming_strings)
    if len(modes) != count:
        raise exceptions.InterfaceError(
            f'expected {count} parameter modes, got {len(modes)}')
    if any(not isinstance(mode, str) or mode not in flags for mode in modes):
        raise exceptions.InterfaceError(
            'parameter modes must be in, out or inout')
    return tuple(flags[mode] for mode in modes)


def _placeholder_tokens(query, mode, standard_conforming_strings):
    pos = 0
    while pos < len(query):
        start = pos
        token = _PLACEHOLDER_TOKEN_RE.match(query, pos)
        kind = token.lastgroup
        value = token.group()
        pos = token.end()
        if kind == 'comment':
            depth = 1
            while pos < len(query) and depth:
                if query.startswith('/*', pos):
                    depth += 1
                    pos += 2
                elif query.startswith('*/', pos):
                    depth -= 1
                    pos += 2
                else:
                    pos += 1
            kind = 'protected'
        elif kind == 'dollar':
            end = query.find(value, pos)
            pos = len(query) if end < 0 else end + len(value)
            kind = 'protected'
        elif mode == 'oracle' and value.lower() == "q'" and pos < len(query):
            delimiter = query[pos]
            end_delimiter = {'[': ']', '(': ')', '{': '}', '<': '>'}.get(
                delimiter, delimiter)
            end = query.find(end_delimiter + "'", pos + 1)
            pos = len(query) if end < 0 else end + 2
            kind = 'protected'
        elif kind == 'quote' or (mode == 'sqlserver' and value == '['):
            delimiter = ']' if value == '[' else value[-1]
            escapes = delimiter == "'" and (
                value.lower() == "e'" or not standard_conforming_strings)
            while pos < len(query):
                if query[pos] == delimiter:
                    pos += 1
                    if pos >= len(query) or query[pos] != delimiter:
                        break
                elif escapes and query[pos] == '\\':
                    pos += 1
                pos += 1
            kind = 'protected'
        elif mode == 'mysql' and value == '#':
            end = query.find('\n', pos)
            pos = len(query) if end < 0 else end
            kind = 'line'
        yield kind, query[start:pos]


def routine_bindings(query, mode, *, standard_conforming_strings=True):
    """Recognize a single direct invocation, not arbitrary SQL expressions."""
    tokens = [(kind, value) for kind, value in _placeholder_tokens(
        query, mode, standard_conforming_strings)
        if kind not in {'space', 'line'} and not value.startswith('/*')]
    if not tokens or tokens[0][1].upper() not in {
            'CALL', 'EXEC', 'EXECUTE', 'SELECT'}:
        return None
    command = tokens.pop(0)[1].upper()

    def identifier(token):
        kind, value = token
        if kind == 'word':
            return value.lower()
        if kind == 'protected' and value[0] in {'"', '[', '`'}:
            closing = ']' if value[0] == '[' else value[0]
            return value[1:-1].replace(closing * 2, closing)
        return None

    if not tokens or (name := identifier(tokens.pop(0))) is None:
        return None
    schema = None
    if tokens and tokens[0][1] == '.':
        tokens.pop(0)
        schema = name
        if not tokens or (name := identifier(tokens.pop(0))) is None:
            return None
    if command in {'CALL', 'SELECT'}:
        if not tokens or tokens.pop(0)[1] != '(':
            return None
        end = next((i for i, token in enumerate(tokens)
                    if token[1] == ')'), None)
        if end is None:
            return None
        arguments, suffix = tokens[:end], tokens[end + 1:]
        if (command == 'SELECT' and suffix
                and suffix[0][1].upper() == 'AS'
                and len(suffix) > 1 and identifier(suffix[1]) is not None):
            suffix = suffix[2:]
        if suffix and suffix != [('other', ';')]:
            return None
    else:
        arguments = tokens[:-1] if tokens[-1:] == [('other', ';')] else tokens

    slots, argument = [], []
    for token in arguments + [('other', ',')]:
        if token[1] != ',':
            argument.append(token)
            continue
        if len(argument) == 1 and argument[0][0] == 'parameter':
            slot = int(argument[0][1][1:])
            if not 1 <= slot <= 32767:
                return None
            slots.append(slot)
        elif argument and not any(
                kind == 'parameter' or value in {';', '(', ')'}
                for kind, value in argument):
            slots.append(None)
        elif not argument and not arguments:
            break
        else:
            return None
        argument = []
    return command, schema, name, tuple(slots)


def _sqlserver_local_positions(tokens):
    """Separate DECLARE locals and EXEC argument labels from bind markers."""
    significant = [i for i, (kind, _) in enumerate(tokens)
                   if kind not in {'space', 'line', 'protected'}]
    locals_ = set()
    preserved = set()
    declaring = False
    expect_local = False
    depth = 0
    command = None
    routine = False
    for index in significant:
        kind, value = tokens[index]
        upper = value.upper()
        if kind == 'word' and upper in {'CREATE', 'ALTER'}:
            command = upper
        elif command in {'CREATE', 'ALTER'} and upper in {
                'PROC', 'PROCEDURE', 'FUNCTION', 'TRIGGER'}:
            routine = True
        if upper == 'DECLARE':
            declaring, expect_local, depth = True, True, 0
        elif value == ';' or (kind == 'word' and upper in {
                'SELECT', 'SET', 'BEGIN', 'END', 'EXEC', 'EXECUTE',
                'INSERT', 'UPDATE', 'DELETE', 'RETURN'}):
            declaring = False
            command = upper if value != ';' else None
        elif declaring:
            if kind == 'at' and expect_local:
                locals_.add(value.casefold())
                expect_local = False
            elif value == '(':
                depth += 1
            elif value == ')':
                depth -= 1
            elif value == ',' and depth == 0:
                expect_local = True

    if routine and any(kind == 'at' for kind, _ in tokens):
        raise exceptions.InterfaceError(
            'SQL Server routine definitions with @ variables must use '
            'execute(sql) without arguments')

    command = None
    for offset, index in enumerate(significant):
        kind, value = tokens[index]
        if value == ';':
            command = None
        elif kind == 'word' and value.upper() in {
                'EXEC', 'EXECUTE', 'SELECT', 'SET', 'DECLARE'}:
            command = value.upper()
        if kind != 'at' or value.startswith('@@'):
            continue
        if value.casefold() in locals_:
            preserved.add(index)
        else:
            following = [tokens[i][1]
                         for i in significant[offset + 1:offset + 3]]
            assignment = following[:1] == ['='] or (
                len(following) == 2
                and following[0] in {'+', '-', '*', '/', '%', '&', '|', '^'}
                and following[1] == '=')
            if not assignment:
                continue
            previous = (tokens[significant[offset - 1]][1].upper()
                        if offset else None)
            if command in {'EXEC', 'EXECUTE'}:
                if previous not in {'EXEC', 'EXECUTE'}:
                    preserved.add(index)
                    continue
            elif not (command in {'SELECT', 'SET'} and previous in {
                    'SELECT', 'SET', ',', 'DISTINCT', 'ALL'}):
                continue
            raise exceptions.InterfaceError(
                f'cannot assign to undeclared SQL Server variable {value}')
    return preserved


def rewrite_query(query, mode, *, standard_conforming_strings=True):
    """Translate mode bind markers, never parameter values, before Parse."""
    if mode not in MODES:
        return query
    marker = {'mysql': '?', 'oracle': ':', 'sqlserver': '@'}[mode]
    if marker not in query:
        return query
    tokens = list(
        _placeholder_tokens(
            query,
            mode,
            standard_conforming_strings))
    preserved = _sqlserver_local_positions(
        tokens) if mode == 'sqlserver' else set()
    used = set()
    for kind, value in tokens:
        if kind == 'parameter' or (
                mode == 'oracle' and kind == 'colon' and value[1:].isdigit()):
            slot = int(value[1:])
            if not 1 <= slot <= 32767:
                raise exceptions.InterfaceError(
                    'query argument positions must be between 1 and 32767')
            used.add(slot)
    if mode == 'mysql' and used and ('question', '?') in tokens:
        raise exceptions.InterfaceError(
            'cannot mix MySQL ? and $n bind placeholders')
    names = {}
    next_slot = 1
    result = []
    for index, (kind, value) in enumerate(tokens):
        name = None
        if mode == 'mysql' and kind == 'question':
            if value == '??':
                value = '?'
            elif value == '?':
                name = index
        elif mode == 'oracle' and kind == 'colon':
            if value[1:].isdigit():
                value = '$' + str(int(value[1:]))
            elif value not in {'::', ':='}:
                name = value.casefold()
        elif (mode == 'sqlserver' and kind == 'at'
              and index not in preserved and not value.startswith('@@')):
            name = value
        if name is not None:
            if name not in names:
                while next_slot in used:
                    next_slot += 1
                if next_slot > 32767:
                    raise exceptions.InterfaceError(
                        'the number of query arguments cannot exceed 32767')
                names[name] = next_slot
                used.add(next_slot)
            value = '$' + str(names[name])
        result.append(value)
    return ''.join(result)


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
    elif len(fraction) > 6:
        fraction = fraction[:6]
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


def _encode_sqlserver_binary_text(value):
    return '0x' + _encode_binary(value).hex()


def _decode_sqlserver_binary_text(value):
    if not value.startswith(('0x', '0X')):
        raise ValueError('invalid SQL Server binary value')
    return bytes.fromhex(value[2:])


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


# (schema, type): (encoder, decoder, wire format)。面向 Python 的类型遵循 asynckb API，
# 线路格式则遵循已发现的 KES 类型。MySQL 兼容类型大多使用文本编码，面向字节的类型保留二进制。
# 同时列出 pg_catalog 和 sys 名称，因为 KES 可能通过任一模式公开相同的兼容类型。
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

# Oracle 兼容类型使用 KES 的 sys 目录名称；下面保留 PostgreSQL 名称，
# 用于 KES 在 pg_catalog 中报告的类型。
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

# SQL Server 兼容类型包括二进制文本类型、时间类型、货币类型和 uniqueidentifier，
# 并使用 asynckb 用户对相应 PostgreSQL 编解码器所期待的 Python 表示形式。
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
    ('sys', 'text'): (_encode_text_binary, _decode_text_binary, 'binary'),
    ('sys', 'ntext'): (_encode_text_binary, _decode_text_binary, 'binary'),
    ('sys', 'sysname'): (_encode_text_binary, _decode_text_binary, 'binary'),
    ('sys', 'image'): (_encode_binary, bytes, 'binary'),
    ('sys', 'xml'): (_encode_text, str, 'text'),
    ('sys', 'money'): (_encode_decimal, Decimal, 'text'),
    ('sys', 'smallmoney'): (_encode_decimal, Decimal, 'text'),
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
    # SQL_VARIANT 可保存不同基础类型；asynckb 的一列只能使用一种 Python 类型，
    # 因此将 KES 返回的文本作为 str 暴露，绑定值也使用文本形式。
    ('sys', 'sql_variant'): (_encode_text, str, 'text'),
}


# 这些 KES 系统类型复用 PG 二进制格式，保留复合类型成员的编解码能力。
_SQLSERVER_BUILTIN_CODECS = {
    ('sys', 'smallint'): 'int2',
    ('sys', 'int'): 'int4',
    ('sys', 'bigint'): 'int8',
    ('sys', 'numeric'): 'numeric',
    ('sys', 'real'): 'float4',
    ('sys', 'float'): 'float8',
}


_CODECS_BY_MODE = {
    'mysql': _MYSQL_CODECS,
    'oracle': _ORACLE_CODECS,
    'sqlserver': _SQLSERVER_CODECS,
}


_MODE_MARKERS = {
    # 当服务器属性不可用或驱动无法读取时，这些标记类型用于识别请求的 KES 兼容模式。
    'mysql': frozenset({('sys', 'json'), ('sys', 'mysql_json')}),
    'oracle': frozenset({('sys', 'dsinterval')}),
    'sqlserver': frozenset({('sys', 'uniqueidentifier')}),
}

# 现有 asynckb 编解码器名称可以解析为 sys 模式中的 KES 类型。
# 仅当连接的服务器存在该类型时才选择候选项。
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

    # 仅注册 OID 来自当前连接的编解码器。未知类型继续使用 asynckb 常规内省和编解码器路径。
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

    # MySQL DOMAIN 可能在查询中可见，但其基础类型才拥有 KES 编解码器。
    # 保留这种关系，使自定义编解码器同时影响两个 OID。
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
    if mode == 'sqlserver':
        builtin = _SQLSERVER_BUILTIN_CODECS.get((schema, name.lower()))
        if builtin is not None:
            settings.set_builtin_type_codec(
                oid, name, schema, 'scalar', builtin, None)
            return True
    codecs = _CODECS_BY_MODE[mode]
    codec = codecs.get((schema, name.lower()))
    if codec is None:
        return False

    encoder, decoder, data_format = codec
    settings.add_python_codec(
        oid, name, schema, None, 'scalar',
        encoder, decoder, data_format)
    if (mode == 'sqlserver' and schema == 'sys' and name.lower()
            in {'binary', 'varbinary', 'image', 'rowversion'}):
        settings.add_python_codec(
            oid, name, schema, None, 'scalar',
            _encode_sqlserver_binary_text, _decode_sqlserver_binary_text,
            'text', preserve_existing=True)
    return True


def codec_wire_format(mode, name, schema):
    if (mode == 'sqlserver'
            and (schema, name.lower()) in _SQLSERVER_BUILTIN_CODECS):
        return 'binary'
    codecs = _CODECS_BY_MODE.get(mode)
    if codecs is None:
        return None

    codec = codecs.get((schema, name.lower()))
    return codec[2] if codec is not None else None


def resolve_codec_type(mode, name, schema, aliases=None):
    # 保留 asynckb 接受的 PostgreSQL 编解码器名称，同时将其解析为当前物理连接上
    # 已发现的实际 KES 类型。
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
    # PostgreSQL 二进制/元组回调使用 PostgreSQL 表示形式。KES MySQL 接受这些值的文本形式，
    # 因此在此边界调整回调，同时保留 asynckb 的公开自定义编解码器 API。
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

        # KES MySQL 拒绝二进制 JSON 数组元素。保留 asynckb 面向 bytes 的自定义编解码器 API，
        # 同时对标量和数组值使用受支持的文本线路表示形式。
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
