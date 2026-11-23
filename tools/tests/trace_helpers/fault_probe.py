import os

import pytest


def pytest_itemcollected(item):
    if item.originalname != "test_asynckb_imports_its_own_protocol_extension":
        return
    fault = os.environ["TRACE_FAULT"]
    if fault == "missing":
        item.own_markers[:] = [
            m for m in item.own_markers if m.name != "case_id"
        ]
    elif fault == "duplicate":
        item.add_marker(pytest.mark.case_id("KB-CONN-009"))
    elif fault == "wrong":
        item.own_markers[:] = [
            m for m in item.own_markers if m.name != "case_id"
        ]
        item.add_marker(pytest.mark.case_id("KB-EXEC-049"))
