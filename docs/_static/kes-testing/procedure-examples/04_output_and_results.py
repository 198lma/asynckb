import asyncio

import asynckb

from demo_support import connect, object_name, procedure_sql


async def main():
    for mode in ("mysql", "oracle", "sqlserver"):
        con = await connect(mode)
        name = object_name("mixed")
        created = False
        try:
            # This procedure emits two SELECT results before its OUT values.
            await con.execute(procedure_sql(mode, name, query_results=True))
            created = True
            stmt = await con.prepare(
                f"CALL {name}($1, $2, $3)",
                parameter_modes=("in", "inout", "out"),
            )
            try:
                await stmt.fetch(2, 5, None)
            except asynckb.ProtocolError as exc:
                print(f"{mode}: {type(exc).__name__}: {exc}")
            else:
                raise AssertionError("No ProtocolError; review the documented limitation")
        finally:
            try:
                if created:
                    await con.execute(f"DROP PROCEDURE {name}")
            finally:
                await con.close()


asyncio.run(main())
