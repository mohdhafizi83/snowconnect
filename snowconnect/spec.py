"""Connector spec: declarative description of one ETL connector."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ConnectorSpec:
    name: str
    source: dict
    transform: dict = field(default_factory=dict)
    sink: dict = field(default_factory=dict)
    schedule: str = "0 * * * *"
    raw: dict = field(default_factory=dict, repr=False)

    @staticmethod
    def from_dict(d: dict) -> "ConnectorSpec":
        if "name" not in d or "source" not in d:
            raise ValueError("spec requires 'name' and 'source'")
        return ConnectorSpec(
            name=d["name"], source=d["source"],
            transform=d.get("transform", {}), sink=d.get("sink", {}),
            schedule=d.get("schedule", "0 * * * *"), raw=d)


def load_spec(path: str | Path) -> ConnectorSpec:
    """Load a connector spec from JSON or YAML (.yaml needs PyYAML, optional)."""
    p = Path(path)
    text = p.read_text()
    if p.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise RuntimeError("PyYAML not installed; use JSON or pip install pyyaml") from e
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return ConnectorSpec.from_dict(data)
