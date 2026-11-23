import json


def pytest_collection_finish(session):
    records = [
        {"nodeid": item.nodeid,
         "case_id": [m.args[0] for m in item.iter_markers("case_id")],
         "properties": dict(item.user_properties)}
        for item in session.items
    ]
    print("TRACE_RECORDS=" + json.dumps(records))
