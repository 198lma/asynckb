import asyncio

import asynckb

from demo_support import connect


async def main():
    con = await connect("sqlserver")
    try:
        for sql in ("select 1; select 2;", "select 1 select 2"):
            print("SQL:", sql)
            print("execute:", await con.execute(sql))
            rows = await con.fetch(sql)
            print("fetch:", [tuple(row) for row in rows])
            assert [tuple(row) for row in rows] == [(1,), (2,)]
        rows = await con.fetch(
            "SELECT 1 AS first_value; "
            "SELECT 2 AS empty_value WHERE 1=0; "
            "SELECT 'last' AS last_value"
        )
        print("WITH EMPTY SET:", [dict(row) for row in rows])
        for setting in ("ON", "OFF"):
            try:
                await con.execute(f"SET NOCOUNT {setting}")
            except asynckb.PostgresSyntaxError as exc:
                print(f"SET NOCOUNT {setting}: {type(exc).__name__}, SQLSTATE={exc.sqlstate}")
            else:
                raise AssertionError(
                    "The server now accepts NOCOUNT; review the documented limitation"
                )
    finally:
        await con.close()


asyncio.run(main())
