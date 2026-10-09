"""Snowflake sink: staging table + MERGE (upsert) SQL generation.

Executes via a DB-API-compatible connection (snowflake-connector-python is
NOT a hard dependency — inject any connection object, or use the built-in
sqlite adapter for local testing without a Snowflake account).
"""
from __future__ import annotations
from typing import Iterable


def _q_ident(name: str) -> str:
    parts = name.split(".")
    if not all(p.replace("_", "").isalnum() and p for p in parts):
        raise ValueError(f"unsafe identifier: {name}")
    return name.upper()


class SnowflakeSQLSink:
    """Generates and executes MERGE-based upserts.

    sink spec:
      table: ANALYTICS.CUSTOMERS
      keys: [id]                # merge keys
      columns: [id, email, ...] # optional; default = union of record keys
    """

    def __init__(self, spec: dict, connection=None, dialect: str = "snowflake"):
        self.table = _q_ident(spec["table"])
        self.keys = [_q_ident(k) for k in spec.get("keys", ["id"])]
        self.columns = [_q_ident(c) for c in spec.get("columns", [])]
        self.conn = connection
        self.dialect = dialect

    def merge_sql(self, columns: list[str]) -> str:
        cols = [_q_ident(c) for c in columns]
        for k in self.keys:
            if k not in cols:
                raise ValueError(f"merge key {k} missing from columns")
        if self.dialect == "sqlite":
            col_list = ", ".join(f'"{c}"' for c in cols)
            val_list = ", ".join(f":{c.lower()}" for c in cols)
            return f'INSERT OR REPLACE INTO "{self.table}" ({col_list}) VALUES ({val_list})'
        on = " AND ".join(f"tgt.{k} = src.{k}" for k in self.keys)
        update_set = [c for c in cols if c not in self.keys]
        update_clause = ", ".join(f"tgt.{c} = src.{c}" for c in update_set) if update_set else None
        insert_cols = ", ".join(cols)
        insert_vals = ", ".join(f"src.{c}" for c in cols)
        matched = f"WHEN MATCHED THEN UPDATE SET {update_clause}" if update_clause else ""
        return (
            f"MERGE INTO {self.table} tgt USING (\n"
            f"  SELECT {', '.join(f'%({c.lower()})s AS {c}' for c in cols)}\n"
            f") src ON ({on})\n"
            f"  {matched}\n"
            f"  WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})"
        )

    def write(self, records: Iterable[dict]) -> int:
        records = list(records)
        if not records:
            return 0
        columns = self.columns or list(records[0].keys())
        sql = self.merge_sql(columns)
        rows = [{c.lower(): r.get(c) or r.get(c.lower()) for c in columns} for r in records]
        if self.conn is None:
            # dry-run mode: return the SQL + row count without executing
            self.last_sql = sql
            self.last_rows = rows
            return len(rows)
        cur = self.conn.cursor()
        cur.executemany(sql, rows)
        self.conn.commit()
        cur.close()
        return len(rows)


class SqliteAdapter:
    """Local sqlite stand-in for Snowflake so the whole pipeline is testable
    without cloud credentials. Translates :name params and MERGE -> INSERT OR REPLACE."""

    def __init__(self, db_path: str = ":memory:"):
        import sqlite3
        self.conn = sqlite3.connect(db_path)

    def ensure_table(self, table: str, columns: list[str], keys: list[str]):
        cols_sql = ", ".join(f'"{c}"' for c in columns)
        pk = ", ".join(f'"{k}"' for k in keys)
        self.conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({cols_sql}, PRIMARY KEY ({pk}))')
        self.conn.commit()

    def merge_sql(self, columns, table, keys):
        cols = ", ".join(f'"{c}"' for c in columns)
        vals = ", ".join(f":{c.lower()}" for c in columns)
        return f'INSERT OR REPLACE INTO "{table}" ({cols}) VALUES ({vals})'
