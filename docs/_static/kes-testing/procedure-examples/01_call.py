import asyncio

from demo_support import connect, object_name, procedure_sql


async def main():
    for mode in ("mysql", "oracle", "sqlserver"):
        con = await connect(mode)
        name = object_name("call")
        created = False
        try:
            # The helper supplies the CREATE PROCEDURE SQL for each mode.
            await con.execute(procedure_sql(mode, name))
            created = True
            stmt = await con.prepare(
                f"CALL {name}($1, $2, $3)",
                parameter_modes=("in", "inout", "out"),
            )
            row = await stmt.fetchrow(2, 5, None)
            print(f"{mode}: {tuple(row)!r}")
            expected = (0, 7, "done") if mode == "sqlserver" else (7, "done")
            assert tuple(row) == expected
        finally:
            try:
                if created:
                    await con.execute(f"DROP PROCEDURE {name}")
            finally:
                await con.close()


asyncio.run(main())
