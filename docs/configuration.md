# Configuration — snowconnect

Everything snowconnect is configured through is documented here: the
**connector spec** (one JSON file per connector), the CLI flags, and the
state file. There are no environment variables or `.env` files — the offline
demo needs none, and secrets are injected by your deployment (see
[Environment variables](#environment-variables)).

File format: JSON. `.yaml`/`.yml` specs also load if PyYAML is installed
(`pip install pyyaml`) — it is an optional dependency.

## Top-level spec

| Field | Required | Default | Description |
|---|---|---|---|
| `name` | Yes | — | Connector name (used in run output). |
| `source` | Yes | — | HTTP source definition — see below. |
| `transform` | No | `{}` | Field mapping / filters — see below. |
| `sink` | No | `{}` | Upsert target. If omitted, records are fetched and transformed but nothing is written. |
| `schedule` | No | `"0 * * * *"` | Cron expression stored in the spec for external schedulers. **The runner does not schedule anything itself** — it runs once per invocation. |

## `source` — HTTP source

| Field | Required | Default | Description |
|---|---|---|---|
| `base_url` | Yes | — | Scheme must be `http`/`https`, no `user:pass@`. Validated by the SSRF guard at load: the host is resolved and **every** address must be public. |
| `allow_private` | No | `false` | Skips the address checks (loopback, RFC1918, link-local incl. `169.254.169.254`). **Local testing only** — never in production specs. |
| `path` | No | `"/"` | Request path appended to `base_url`. |
| `method` | No | `"GET"` | HTTP method (uppercased). |
| `headers` | No | `{}` | Static request headers. Applied with `setdefault`, so auth-set headers win. |
| `params` | No | `{}` | Static query parameters merged into every request. |
| `records_path` | No | `null` | Dotted path to the record array in the response, e.g. `"data"` or `"data.items"`. List indices work too, including negative (`"data.-1.id"`). `null` = the response body is the array. |
| `watermark_field` | No | `null` | Field used for incremental loads. Values are compared as **strings** (epoch ints and ISO timestamps both sort correctly). Records ≤ the stored watermark are skipped; the max seen value is persisted after the run. |
| `auth` | No | none | See [Auth](#auth) below. |
| `max_retries` | No | `3` | Retries per request on connection errors, timeouts, HTTP 429 and 5xx. Backoff `min(2^attempt, 15)` s. |
| `timeout` | No | `30` | Per-request timeout in seconds. |
| `max_response_bytes` | No | `52428800` (50 MB) | Response size cap, enforced on `Content-Length` and while streaming. |

### Pagination (`source.pagination`)

Default `{"type": "none"}` — a single request.

| Field | Applies to | Default | Description |
|---|---|---|---|
| `type` | — | `"none"` | `"none"` \| `"page"` \| `"cursor"`. |
| `page_param` | `page` | `"page"` | Query param carrying the page number (starts at 1). |
| `max_pages` | `page` | `100` | Hard stop on page count. |
| `cursor_param` | `cursor` | `"cursor"` | Query param carrying the cursor. |
| `cursor_path` | `cursor` | `"next_cursor"` | Dotted path in the response to the next cursor; pagination stops when it is empty/missing. Stripe-style example: `"data.-1.id"`. |
| `watermark_param` | both | — | If set, the stored watermark is also sent as this query param, so the API can server-side filter (in addition to the client-side `watermark_field` skip). |

### Auth (`source.auth`)

`auth` omitted or `{"type": "none"}` = no auth.

| `type` | Fields | Behaviour |
|---|---|---|
| `api_key` | `key` (required), `header` and/or `query_param` (at least one) | Sends the key as a header (e.g. `Authorization`) and/or query param. |
| `bearer` | `token` (required) | `Authorization: Bearer <token>`. |
| `oauth2` | `token_url`, `client_id`, `client_secret` (required), `scopes` (list, optional) | Client-credentials flow; token auto-refreshed 60 s before expiry. `token_url` goes through the same SSRF guard as `base_url`. |

Any other `type` raises a spec error.

## `transform`

| Field | Default | Description |
|---|---|---|
| `fields` | `null` (pass records through unchanged) | Ordered list of output columns, each an object below. |
| `filter` | `null` | `{"field": "<dotted path>", "in": [...]}` and/or `{"not_in": [...]}`. Records failing the filter are dropped and counted as `filtered`. |

Each entry in `fields`:

| Key | Description |
|---|---|
| `name` | Output column name (required). |
| `from` | Dotted path in the raw record; defaults to `name`. |
| `cast` | `str` \| `int` \| `float` \| `bool` \| `iso`. `int` parses via `int(float(v))`; `bool` is true for `"1"/"true"/"yes"` (case-insensitive); `iso` normalises to UTC ISO-8601; empty/`null` values pass through as `null`. |
| `const` | Literal value (wins over `from`/`concat`). |
| `concat` | List of dotted paths joined with `sep` (default `""`); missing parts become empty strings. |

## `sink`

| Field | Required | Default | Description |
|---|---|---|---|
| `table` | Yes (if `sink` present) | — | Target table, e.g. `ANALYTICS.CUSTOMERS`. Identifiers are allowlist-validated (letters/digits/underscore, dot-separated) and uppercased — no SQL injection via spec. |
| `keys` | No | `["id"]` | Merge (upsert) keys. Must appear in the written columns or the run fails with a clear error. |
| `columns` | No | keys of the first record | Explicit column list for the `MERGE`. |

Generated SQL per batch (default 500 rows, library parameter):
Snowflake dialect → `MERGE INTO … USING (SELECT …) src ON (…) WHEN MATCHED
THEN UPDATE … WHEN NOT MATCHED THEN INSERT …` with bind parameters for
values. The sqlite stand-in (`--db`) switches the dialect to
`INSERT OR REPLACE`.

## CLI

```
snowconnect run <spec.json> [--stream NAME] [--dry-run] [--db FILE]
snowconnect demo
snowconnect --verbose run …        # full traceback instead of one-line error
```

- `--dry-run` — fetch + transform, print the generated MERGE SQL, execute no writes.
- `--db FILE` — use a local sqlite file as the sink stand-in (table is
  auto-created from the spec's fields/keys).
- `--stream` — stream name for watermark bookkeeping (default `main`).

Exit codes: `0` success · `1` run finished with recorded errors ·
`2` spec/config/SSRF/transport error (clean one-line message on stderr).

## State file

Watermarks persist in `.snowconnect/state.json` (one JSON object, key
`"<base_url><path>:<stream>"`). Delete the file to force a full reload;
keep it between runs for incremental loads. The library takes a custom
path: `Pipeline(spec, state_path="…")`.

## Environment variables

snowconnect reads **no** environment variables. `${STRIPE_KEY}` in
`examples/stripe_customers.json` is a placeholder convention — substitute
the real value before running (e.g. `envsubst`, your CI's secret injection,
or a small template step). Where secrets come from (env, vault, SSM) is the
deployment's job; see [SECURITY.md](../SECURITY.md).
