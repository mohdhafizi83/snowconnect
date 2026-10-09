"""snowconnect — declarative ETL connectors for Snowflake Native Apps.

A connector is a spec (dict/YAML): source (HTTP API + auth + pagination),
transform (field mapping / renames / casts), sink (Snowflake staging + MERGE).
State (watermarks) persists between runs for incremental loads.
"""
from .auth import APIKeyAuth, BearerAuth, OAuth2ClientCredentials, NoAuth
from .spec import ConnectorSpec, load_spec
from .source import HttpSource
from .transform import Transformer
from .sink import SnowflakeSQLSink
from .pipeline import Pipeline, RunResult

__all__ = [
    "APIKeyAuth", "BearerAuth", "OAuth2ClientCredentials", "NoAuth",
    "ConnectorSpec", "load_spec", "HttpSource", "Transformer",
    "SnowflakeSQLSink", "Pipeline", "RunResult",
]
__version__ = "0.1.0"
