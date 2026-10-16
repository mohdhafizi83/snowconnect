# Getting Started — snowconnect

Goal: you run a real end-to-end ETL run in under 10 minutes, with **no
Snowflake account and no credentials**.

## Requirements

- Docker + Docker Compose (recommended path), **or**
- Python ≥ 3.10 (native path)

## Quickstart (Docker — recommended)

```bash
git clone https://github.com/mohdhafizi83/snowconnect.git
cd snowconnect
docker compose up --build
```

No `.env`, no secrets, no network access needed: the demo serves a mock
paginated SaaS API on localhost inside the container, runs the full
pipeline (source → transform → sink) into a sqlite stand-in, and exits.

Expected output (abridged):

```
run 1: { "stream": "main", "fetched": 25, "written": 25, ... }
rows in sink: 25
run 2 (incremental): { "stream": "main", "fetched": 0, "written": 0, ... }

Snowflake MERGE the sink generates per batch:
MERGE INTO CUSTOMERS tgt USING (
  SELECT %(id)s AS ID, %(email)s AS EMAIL, ...
) src ON (tgt.ID = src.ID)
  WHEN MATCHED THEN UPDATE SET tgt.EMAIL = src.EMAIL, ...
  WHEN NOT MATCHED THEN INSERT (...) VALUES (...)
```

`run 1` is the initial load (25 records over 3 cursor-paginated pages);
`run 2` proves incremental loading — the watermark is at the last `created`
value, so nothing new is fetched. The container exits **0** when
`written == 25` on run 1 and `written == 0` on run 2.

Tear down afterwards:

```bash
docker compose down
```

## Install without Docker

```bash
git clone https://github.com/mohdhafizi83/snowconnect.git
cd snowconnect
python -m venv .venv && source .venv/bin/activate
pip install -e .
snowconnect demo        # same offline demo as the container
python -m pytest tests/ # 39 tests, fully offline
```

## Run your own spec

```bash
# Validate + show the generated MERGE SQL without touching any database:
snowconnect run examples/stripe_customers.json --dry-run

# Execute against a local sqlite stand-in:
snowconnect run myspec.json --db local.db
```

Every field of the spec format (source, auth, pagination, watermark,
transform, sink) is documented in [configuration.md](configuration.md).

## Pointing at a real Snowflake account

The CLI's `--db` option is a sqlite stand-in only. To write to Snowflake,
use the library API and inject any DB-API connection —
`snowflake-connector-python` is deliberately **not** a hard dependency:

```bash
pip install snowflake-connector-python
```

```python
import snowflake.connector
from snowconnect import load_spec, Pipeline

spec = load_spec("myspec.json")
conn = snowflake.connector.connect(          # or key-pair / OAuth, your choice
    account="xy12345.ap-southeast-1",
    user="ETL_USER",
    password="...",                          # or authenticator=...
    warehouse="WH", database="ANALYTICS", schema="PUBLIC",
)
result = Pipeline(spec, sink_connection=conn, dialect="snowflake").run()
print(result.to_dict())
```

Notes for real runs:

- The sink generates a standard Snowflake `MERGE INTO … USING (SELECT …)`
  per batch (default 500 rows); bind parameters are used for values, and
  table/column identifiers are allowlist-validated before interpolation.
- The target table must already exist (or be created by your deploy
  tooling); snowconnect upserts, it does not create Snowflake tables.
- Watermark state lives in `.snowconnect/state.json` (per stream). Keep that
  file between runs — deleting it forces a full reload.
- Keep `"allow_private": true` out of production specs (see
  [SECURITY.md](../SECURITY.md)).

## Next steps

- [configuration.md](configuration.md) — every connector-spec field
- [SECURITY.md](../SECURITY.md) — threat model, SSRF guard, `allow_private`
- [architecture diagram](architecture.svg) — how source/transform/sink fit together
