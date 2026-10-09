"""Built-in demo: a mock SaaS API + full pipeline run, no credentials needed.

Run:  snowconnect demo
Serves fake paginated 'customers' data on localhost, runs the pipeline
end-to-end into a local sqlite stand-in, prints run results + MERGE SQL.
"""
from __future__ import annotations
import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

_CUSTOMERS = [
    {"id": f"c{i:03d}", "email": f"user{i}@example.com", "first_name": "Ali" if i % 2 else "Mei",
     "last_name": "Bin Abu" if i % 2 else "Ling", "created": 1_700_000_000 + i * 3600,
     "delinquent": False}
    for i in range(1, 26)
]


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        limit = int(q.get("limit", ["10"])[0])
        after = q.get("starting_after", [None])[0]
        start = 0
        if after:
            ids = [c["id"] for c in _CUSTOMERS]
            start = (ids.index(after) + 1) if after in ids else len(_CUSTOMERS)
        page = _CUSTOMERS[start:start + limit]
        body = json.dumps({"object": "list", "data": page, "has_more": start + limit < len(_CUSTOMERS)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


DEMO_SPEC = {
    "name": "demo_customers",
    "source": {
        "base_url": "http://127.0.0.1:{port}",
        "path": "/v1/customers",
        "auth": {"type": "bearer", "token": "demo"},
        "params": {"limit": 10},
        "records_path": "data",
        "pagination": {"type": "cursor", "cursor_param": "starting_after", "cursor_path": "data.-1.id"},
        "watermark_field": "created",
    },
    "transform": {
        "fields": [
            {"name": "ID", "from": "id"},
            {"name": "EMAIL", "from": "email"},
            {"name": "NAME", "concat": ["first_name", "last_name"], "sep": " "},
            {"name": "CREATED_AT", "from": "created", "cast": "int"},
            {"name": "SOURCE", "const": "demo"},
        ]
    },
    "sink": {"table": "CUSTOMERS", "keys": ["ID"], "columns": ["ID", "EMAIL", "NAME", "CREATED_AT", "SOURCE"]},
}


def run_demo() -> int:
    from .spec import ConnectorSpec
    from .pipeline import Pipeline
    from .sink import SqliteAdapter

    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        spec = ConnectorSpec.from_dict(json.loads(json.dumps(DEMO_SPEC).replace("{port}", str(port))))
        adapter = SqliteAdapter(":memory:")
        cols = [f["name"] for f in spec.transform["fields"]]
        adapter.ensure_table("CUSTOMERS", cols, ["ID"])
        pipe = Pipeline(spec, sink_connection=adapter.conn, dialect="sqlite",
                        state_path=".snowconnect/demo_state.json")
        res = pipe.run()
        print("run 1:", json.dumps(res.to_dict(), indent=1))
        rows = adapter.conn.execute("SELECT COUNT(*) FROM CUSTOMERS").fetchone()[0]
        print(f"rows in sink: {rows}")
        # incremental second run: watermark now at last created -> 0 new
        res2 = pipe.run()
        print("run 2 (incremental):", json.dumps(res2.to_dict(), indent=1))
        print("\nSnowflake MERGE the sink generates per batch:")
        from .sink import SnowflakeSQLSink
        print(SnowflakeSQLSink(spec.sink, dialect="snowflake").merge_sql(cols))
        return 0 if res.written == 25 and res2.written == 0 else 1
    finally:
        httpd.shutdown()
