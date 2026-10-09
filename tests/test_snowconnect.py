"""End-to-end tests with mocked HTTP — no network, no Snowflake account needed."""
import json, sqlite3
import pytest
import responses

from snowconnect import ConnectorSpec, Pipeline
from snowconnect.auth import APIKeyAuth, BearerAuth, OAuth2ClientCredentials, build_auth
from snowconnect.sink import SnowflakeSQLSink, SqliteAdapter
from snowconnect.transform import Transformer


# ---------- auth ----------
def test_api_key_header():
    import requests
    s = requests.Session()
    APIKeyAuth("k123", header="X-Key").apply(s)
    assert s.headers["X-Key"] == "k123"

def test_bearer():
    import requests
    s = requests.Session()
    BearerAuth("tok").apply(s)
    assert s.headers["Authorization"] == "Bearer tok"

@responses.activate
def test_oauth2_client_credentials():
    responses.add(responses.POST, "https://auth.test/token",
                  json={"access_token": "abc", "expires_in": 3600}, status=200)
    auth = OAuth2ClientCredentials("https://auth.test/token", "cid", "sec")
    import requests
    s = requests.Session()
    auth.apply(s)
    assert s.headers["Authorization"] == "Bearer abc"

def test_build_auth_factory():
    assert build_auth(None).name == "none"
    assert build_auth({"type": "bearer", "token": "t"}).name == "bearer"
    with pytest.raises(ValueError):
        build_auth({"type": "magic"})


# ---------- transform ----------
def test_transform_fields_rename_cast():
    t = Transformer({"fields": [
        {"name": "ID", "from": "id"},
        {"name": "TOTAL", "from": "amount", "cast": "int"},
        {"name": "FULL", "concat": ["a", "b"], "sep": " "},
        {"name": "SRC", "const": "x"},
    ]})
    out = t.apply({"id": "1", "amount": "42.0", "a": "foo", "b": "bar"})
    assert out == {"ID": "1", "TOTAL": 42, "FULL": "foo bar", "SRC": "x"}

def test_transform_filter():
    t = Transformer({"filter": {"field": "status", "not_in": ["deleted"]}, "fields": None})
    assert t.apply({"status": "ok"}) == {"status": "ok"}
    assert t.apply({"status": "deleted"}) is None


# ---------- sink ----------
def test_merge_sql_contains_upsert():
    sink = SnowflakeSQLSink({"table": "DB.T", "keys": ["ID"], "columns": ["ID", "EMAIL"]})
    sql = sink.merge_sql(["ID", "EMAIL"])
    assert "MERGE INTO DB.T" in sql
    assert "WHEN MATCHED THEN UPDATE SET tgt.EMAIL = src.EMAIL" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql

def test_sink_rejects_missing_key_column():
    sink = SnowflakeSQLSink({"table": "DB.T", "keys": ["ID"]})
    with pytest.raises(ValueError):
        sink.merge_sql(["EMAIL"])


# ---------- end-to-end ----------
@responses.activate
def test_pipeline_end_to_end_incremental(tmp_path):
    page1 = {"data": [
        {"id": "c1", "email": "a@x.com", "created": 100},
        {"id": "c2", "email": "b@x.com", "created": 200},
    ]}
    page2 = {"data": [
        {"id": "c3", "email": "c@x.com", "created": 300},
    ]}
    responses.add(responses.GET, "https://api.test/customers", json=page1, status=200)
    responses.add(responses.GET, "https://api.test/customers", json=page2, status=200)

    spec = ConnectorSpec.from_dict({
        "name": "t",
        "source": {"base_url": "https://api.test", "path": "/customers",
                   "records_path": "data", "watermark_field": "created",
                   "pagination": {"type": "page", "page_param": "p", "max_pages": 2}},
        "transform": {"fields": [{"name": "ID", "from": "id"},
                                  {"name": "EMAIL", "from": "email"},
                                  {"name": "CREATED", "from": "created", "cast": "int"}]},
        "sink": {"table": "T", "keys": ["ID"], "columns": ["ID", "EMAIL", "CREATED"]},
    })
    adapter = SqliteAdapter(str(tmp_path / "t.db"))
    adapter.ensure_table("T", ["ID", "EMAIL", "CREATED"], ["ID"])
    pipe = Pipeline(spec, sink_connection=adapter.conn, state_path=tmp_path / "state.json", dialect="sqlite")
    res = pipe.run()
    assert res.fetched == 3 and res.written == 3 and not res.errors
    rows = adapter.conn.execute("SELECT COUNT(*) FROM T").fetchone()[0]
    assert rows == 3

    # second run: watermark at created=300 -> nothing new (page1+page2 served again)
    responses.reset()
    responses.add(responses.GET, "https://api.test/customers", json=page1, status=200)
    responses.add(responses.GET, "https://api.test/customers", json=page2, status=200)
    pipe2 = Pipeline(spec, sink_connection=adapter.conn, state_path=tmp_path / "state.json", dialect="sqlite")
    res2 = pipe2.run()
    assert res2.written == 0  # incremental: all below watermark

@responses.activate
def test_pipeline_upsert_updates_existing(tmp_path):
    responses.add(responses.GET, "https://api.test/items",
                  json={"data": [{"id": "1", "v": "old"}]}, status=200)
    spec = ConnectorSpec.from_dict({
        "name": "u",
        "source": {"base_url": "https://api.test", "path": "/items", "records_path": "data"},
        "transform": {"fields": [{"name": "ID", "from": "id"}, {"name": "V", "from": "v"}]},
        "sink": {"table": "T", "keys": ["ID"], "columns": ["ID", "V"]},
    })
    adapter = SqliteAdapter(str(tmp_path / "u.db"))
    adapter.ensure_table("T", ["ID", "V"], ["ID"])
    Pipeline(spec, sink_connection=adapter.conn, state_path=tmp_path / "s.json", dialect="sqlite").run()
    responses.reset()
    responses.add(responses.GET, "https://api.test/items",
                  json={"data": [{"id": "1", "v": "new"}]}, status=200)
    Pipeline(spec, sink_connection=adapter.conn, state_path=tmp_path / "s.json", dialect="sqlite").run()
    v = adapter.conn.execute("SELECT V FROM T WHERE ID='1'").fetchone()[0]
    assert v == "new"
