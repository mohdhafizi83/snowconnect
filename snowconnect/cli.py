"""CLI: snowconnect run <spec.json> [--dry-run] [--db sqlite_path]"""
from __future__ import annotations
import argparse, json, sys

from .spec import load_spec
from .pipeline import Pipeline
from .sink import SqliteAdapter


def main(argv=None):
    ap = argparse.ArgumentParser(prog="snowconnect")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run one connector spec")
    run.add_argument("spec")
    run.add_argument("--stream", default="main")
    run.add_argument("--dry-run", action="store_true", help="generate SQL, do not execute")
    run.add_argument("--db", help="local sqlite file to use as sink stand-in")
    sub.add_parser("demo", help="run the built-in offline demo (mock API -> sqlite)")
    args = ap.parse_args(argv)

    if args.cmd == "demo":
        from .demo import run_demo
        return run_demo()

    spec = load_spec(args.spec)
    conn = None
    dialect = "snowflake"
    if args.db:
        adapter = SqliteAdapter(args.db)
        cols = [f["name"] for f in spec.transform.get("fields", [])] or ["id"]
        adapter.ensure_table(spec.sink["table"], cols, spec.sink.get("keys", ["id"]))
        conn = adapter.conn
        dialect = "sqlite"
    pipe = Pipeline(spec, sink_connection=conn, dialect=dialect)
    result = pipe.run(stream=args.stream)
    print(json.dumps(result.to_dict(), indent=1))
    if args.dry_run and pipe.sink is not None:
        print("--- generated MERGE SQL ---")
        print(getattr(pipe.sink, "last_sql", "(no rows fetched)"))
    return 0 if not result.errors else 1


if __name__ == "__main__":
    sys.exit(main())
