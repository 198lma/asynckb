import os
import uuid

import asynckb


async def connect(mode):
    ports = {"mysql": 54321, "oracle": 54322, "sqlserver": 54323}
    return await asynckb.connect(
        host=os.getenv("ASYNCKB_KES_HOST", "127.0.0.1"),
        port=int(os.getenv(f"ASYNCKB_KES_{mode.upper()}_PORT", ports[mode])),
        user=os.getenv("ASYNCKB_KES_USER", "system"),
        password=os.environ["ASYNCKB_KES_PASSWORD"],
        database=os.getenv("ASYNCKB_KES_DATABASE", "test"),
        kes_mode=mode, ssl=False, timeout=5, command_timeout=10,
    )


def object_name(prefix):
    return f"demo_{prefix}_{uuid.uuid4().hex[:8]}"


def procedure_sql(mode, name, query_results=False):
    if mode == "mysql":
        queries = ("SELECT p_add AS first_value; "
                   "SELECT 'inside' AS second_value; ") if query_results else ""
        return (
            f"CREATE PROCEDURE {name}(IN p_add INT, INOUT p_total INT, "
            "OUT p_text VARCHAR(30)) BEGIN " + queries +
            "SET p_total=p_total+p_add; SET p_text='done'; END"
        )
    if mode == "oracle":
        declaration = "c SYS_REFCURSOR; " if query_results else ""
        queries = (
            "OPEN c FOR SELECT p_add AS first_value; DBMS_SQL.RETURN_RESULT(c); "
            "OPEN c FOR SELECT 'inside' AS second_value; DBMS_SQL.RETURN_RESULT(c); "
        ) if query_results else ""
        return (
            f"CREATE PROCEDURE {name}(p_add IN INTEGER, "
            "p_total IN OUT INTEGER, p_text OUT VARCHAR2) AS " + declaration +
            "BEGIN " + queries + "p_total:=p_total+p_add; p_text:='done'; END;"
        )
    queries = ("SELECT @p_add AS first_value; "
               "SELECT 'inside' AS second_value; ") if query_results else ""
    return (
        f"CREATE PROCEDURE {name} @p_add INT, @p_total INT OUTPUT, "
        "@p_text VARCHAR(30) OUTPUT AS BEGIN " + queries +
        "SET @p_total=@p_total+@p_add; SET @p_text='done'; END"
    )
