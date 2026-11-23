import asyncio

from demo_support import connect, object_name


async def main():
    con = await connect("oracle")
    table = object_name("output")
    created = False
    try:
        await con.execute(f"CREATE TABLE {table}(id INT PRIMARY KEY)")
        created = True
        stmt = await con.prepare(
            f"BEGIN INSERT INTO {table} VALUES ($1) "
            "RETURNING id INTO $2; END;",
            parameter_modes=("in", "out"),
        )
        tx = con.transaction()
        await tx.start()
        value = await stmt.fetchval(42, None)
        print("OUT:", value)
        rows = await con.fetch(f"SELECT id FROM {table}")
        print("TABLE:", [tuple(row) for row in rows])
        assert value == 42 and [tuple(row) for row in rows] == [(42,)]
        await tx.rollback()
        rows = await con.fetch(f"SELECT id FROM {table}")
        print("AFTER ROLLBACK:", [tuple(row) for row in rows])
        assert rows == []
    finally:
        try:
            if con.is_in_transaction():
                await con.execute("ROLLBACK")
            if created:
                await con.execute(f"DROP TABLE {table}")
        finally:
            await con.close()


asyncio.run(main())
