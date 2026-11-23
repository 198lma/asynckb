"""Package identity checks for the standalone KES driver distribution."""

import importlib

import pytest


@pytest.mark.case_id("KB-CONN-008")
@pytest.mark.unit
def test_asynckb_imports_its_own_protocol_extension():
    package = importlib.import_module("asynckb")
    protocol = importlib.import_module("asynckb.protocol.protocol")

    assert package.__name__ == "asynckb"
    assert protocol.__name__ == "asynckb.protocol.protocol"


@pytest.mark.case_id("KB-CONN-009")
@pytest.mark.unit
def test_sqlalchemy_uses_the_asynckb_driver_entry_point():
    pytest.importorskip("sqlalchemy")
    from sqlalchemy.dialects import registry

    dialect = registry.load("kingbase.asynckb")

    assert dialect.__module__ == "asynckb.sa_dialect"


@pytest.mark.case_id("KB-CONN-010")
@pytest.mark.unit
def test_sqlalchemy_error_translation_uses_asynckb_exceptions():
    pytest.importorskip("sqlalchemy")
    from asynckb import exceptions
    from asynckb.sa_dialect import KESDialect_asynckb

    dbapi = KESDialect_asynckb.import_dbapi()

    assert (
        dbapi._asyncpg_error_translate[exceptions.PostgresError]
        is dbapi.Error
    )
    assert (
        dbapi._asyncpg_error_translate[exceptions.InterfaceError]
        is dbapi.InterfaceError
    )
