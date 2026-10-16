# Changelog

All notable changes to snowconnect are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `Dockerfile` + `docker-compose.yml`: one-shot offline demo container
  (`docker compose up` runs `snowconnect demo` and exits 0).
- `docs/getting-started.md` (Docker demo path, local install, pointing at a
  real Snowflake account) and `docs/configuration.md` (full connector-spec
  field reference).
- `.github/workflows/release.yml`: tag `v*` → GitHub Release with CHANGELOG
  notes + Docker image pushed to GHCR.

## [0.1.0] - 2026-10-09

Initial release: declarative ETL connector framework for Snowflake Native Apps.

### Added
- **Connector spec** (JSON, YAML optional via PyYAML): `source` / `transform`
  / `sink` / `schedule`, loaded via `load_spec()` or `snowconnect run <spec>`.
- **HTTP source**: API-key / bearer / OAuth2 client-credentials auth,
  page-number and cursor pagination, nested `records_path` extraction,
  incremental watermarks persisted per stream, bounded retries with backoff.
- **SSRF guard** (`snowconnect/ssrf.py`): http/https only, no userinfo, every
  resolved address must be public, redirects refused, 30 s timeout and 50 MB
  response cap (both spec-configurable); `allow_private` escape hatch for
  local testing only.
- **Transform**: field selection/renaming, casts (`str`/`int`/`float`/`bool`/
  `iso`), `concat` computed columns, `const` columns, `in`/`not_in` filters.
- **Sink**: Snowflake `MERGE` upsert SQL generation with identifier
  allowlisting; any DB-API connection can be injected, and the built-in
  `SqliteAdapter` runs the whole pipeline offline (MERGE → `INSERT OR REPLACE`).
- **CLI**: `snowconnect run <spec> [--dry-run] [--db path] [--stream name]`,
  `snowconnect demo` (built-in offline demo, no credentials), `--verbose` for
  full tracebacks.
- **Built-in offline demo**: mock paginated SaaS API on localhost → pipeline →
  sqlite stand-in → prints run results and the generated `MERGE` statement.
- CI: pytest matrix (Python 3.10/3.12/3.13), offline demo smoke test, and a
  security job (bandit, pip-audit on pinned requirements, gitleaks).
- `SECURITY.md` threat model (spec-as-untrusted-input, SSRF matrix,
  `allow_private` semantics, DNS-rebinding TOCTOU limitation).
- 39 tests, no Snowflake account or network access required.
