# Security Policy

## Threat model

snowconnect executes **spec files** (JSON) that describe an HTTP source, a
transform, and a Snowflake sink. Who authors the spec determines the trust
level:

| Context | Spec author | Trust |
|---|---|---|
| Single operator, own repo (the common case) | repo owner | spec is trusted input; the guard is defence-in-depth |
| Multi-tenant / pipeline-of-pipelines (specs generated or reviewed by others, CI that runs third-party specs) | third parties | spec is **untrusted input** — this is what the SSRF guard defends against |

### Threats and controls

| # | Threat | Control | Test |
|---|---|---|---|
| 1 | Malicious spec points `source.base_url` at internal services (cloud metadata `169.254.169.254`, RFC1918, loopback admin ports) to exfiltrate credentials/data via the connector's response handling | `snowconnect/ssrf.py`: scheme allowlist (http/https), userinfo rejected, host resolved via `getaddrinfo` and **every** address checked against `ipaddress` flags (private/loopback/link-local/multicast/reserved/unspecified; also catches decimal/hex IP encodings) | `test_ssrf_rejects`, `test_httpsource_blocks_loopback_by_default`, `test_httpsource_blocks_metadata_ip_by_default` |
| 2 | OAuth2 `token_url` used as an SSRF bypass around the source guard | same resolver policy applied to `token_url` at construction | `test_oauth_token_url_is_guarded` |
| 3 | Public URL 302-redirects to an internal address (guard validated only the first hop) | redirects are **refused** (not followed): any 3xx raises `ConnectorError`. Refusing was chosen over per-hop re-validation because it removes the rebind/redirect race entirely and connectors control their own endpoints | `test_redirect_refused` |
| 4 | Hostile endpoint returns a huge body to exhaust memory | response size cap, default 50 MB, spec field `max_response_bytes`; enforced on `Content-Length` and while streaming | `test_size_cap_*` |
| 5 | Unreachable/slow endpoint hangs the pipeline forever | 30 s default timeout, spec field `timeout`; bounded retries | `test_timeout_defaults_and_spec_override` |
| 6 | SQL identifier injection via spec `sink.table`/`keys`/`columns` | `_q_ident()` allowlist (alnum/underscore only) before any interpolation; values are always bind parameters | `test_sink_rejects_missing_key_column`, existing sink tests |
| 7 | Error messages leak internals (stack traces, URLs with credentials) in CLI output | CLI catches expected failure classes and prints one clean line; full traceback only with `--verbose` | `test_cli_clean_error_no_traceback`, `test_cli_verbose_shows_traceback` |
| 8 | Secrets committed to the repo | gitleaks on every push/PR (full history); CI pins actions by SHA and scanners by version | CI `security` job |

### The `allow_private` escape hatch

`"allow_private": true` in a source spec skips the address checks so the
built-in demo (localhost mock API) works. **It is local-testing-only**: it
allows loopback *and* link-local, so a spec with it set can reach
`169.254.169.254`. Never set it in a production spec; treat it like
`--dangerously-*` flags. The demo spec sets it explicitly and is covered by
`test_httpsource_allow_private_allows_loopback` and
`test_allow_private_documented_to_allow_metadata_too`.

### Known limitations

- **DNS rebinding (TOCTOU):** validation and the actual connection are
  separate `getaddrinfo` lookups; a hostile authoritative DNS server with a
  ~0 s TTL could answer public at validation time and private at connect
  time. Mitigate in deployment: run connectors in a network namespace /
  security group with no route to internal ranges.
- Redirects are refused rather than followed; APIs that require redirect
  following need the final URL in the spec (validated at load).
- `requests` connection pooling can reuse a connection to a previously
  validated address for the same host; same trust assumption as above.

## Out of scope

- Snowflake-side privileges, warehouse cost controls, and Native App
  packaging trust (handled by Snowflake RBAC / the Native App framework).
- Transform expressions are a fixed field-mapping DSL, not user code — no
  sandbox needed; if `eval`-style transforms are ever added, they need their
  own sandbox design.
- Secrets management: specs reference env vars (`${STRIPE_KEY}`); where
  secrets come from (env, vault) is deployment's job.
- Data-at-rest encryption and transport TLS termination: delegated to
  `requests`/certifi and the sink connection.

## Reporting a vulnerability

Open a [private security advisory](https://github.com/mohdhafizi83/snowconnect/security/advisories/new).
Expect a response within 7 days.
