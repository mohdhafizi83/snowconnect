"""Pipeline: source -> transform -> sink with run bookkeeping."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .source import HttpSource
from .transform import Transformer
from .sink import SnowflakeSQLSink


@dataclass
class RunResult:
    stream: str
    fetched: int = 0
    written: int = 0
    filtered: int = 0
    started_at: str = ""
    finished_at: str = ""
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"stream": self.stream, "fetched": self.fetched, "written": self.written,
                "filtered": self.filtered, "started_at": self.started_at,
                "finished_at": self.finished_at, "errors": self.errors}


class Pipeline:
    """Wire one ConnectorSpec into a runnable pipeline.

    sink_connection: any DB-API connection (Snowflake or sqlite adapter).
    Pass None for dry-run (SQL generated, not executed).
    """

    def __init__(self, spec, sink_connection=None, state_path=".snowconnect/state.json",
                 dialect: str = "snowflake"):
        self.spec = spec
        self.source = HttpSource(spec.source, state_path=state_path)
        self.transformer = Transformer(spec.transform)
        self.sink = SnowflakeSQLSink(spec.sink, connection=sink_connection, dialect=dialect) if spec.sink else None

    def run(self, stream: str = "main", batch_size: int = 500) -> RunResult:
        res = RunResult(stream=stream,
                        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        batch: list[dict] = []

        def flush(items):
            if self.sink and items:
                res.written += self.sink.write(items)

        try:
            for raw in self.source.stream(stream):
                res.fetched += 1
                rec = self.transformer.apply(raw)
                if rec is None:
                    res.filtered += 1
                    continue
                batch.append(rec)
                if len(batch) >= batch_size:
                    flush(batch)
                    batch = []
            flush(batch)
        except Exception as err:  # noqa: BLE001 — record and re-raise after bookkeeping
            res.errors.append(str(err))
            res.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            raise
        finally:
            res.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return res
