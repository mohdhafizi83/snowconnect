"""Record transformation: field selection, renaming, casting, computed columns."""
from __future__ import annotations
from datetime import datetime, timezone


CASTS = {
    "str": str,
    "int": lambda v: int(float(v)) if v not in (None, "") else None,
    "float": lambda v: float(v) if v not in (None, "") else None,
    "bool": lambda v: str(v).lower() in ("1", "true", "yes") if v is not None else None,
    "iso": lambda v: datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat() if v else None,
}


class Transformer:
    """Apply spec['transform'] to raw records.

    transform:
      fields:            # ordered output columns
        - {name: id,        from: id,        cast: str}
        - {name: created_at, from: created,  cast: iso}
        - {name: full_name,  concat: [first_name, last_name], sep: ' '}
        - {name: source,     const: 'stripe'}
      filter: {field: status, not_in: [deleted]}
    """

    def __init__(self, spec: dict | None):
        spec = spec or {}
        self.fields = spec.get("fields")
        self.filter = spec.get("filter")

    def _dig(self, rec: dict, dotted: str):
        cur = rec
        for part in dotted.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    def apply(self, rec: dict) -> dict | None:
        if self.filter:
            f = self.filter
            val = self._dig(rec, f["field"])
            if "in" in f and val not in f["in"]:
                return None
            if "not_in" in f and val in f["not_in"]:
                return None
        if not self.fields:
            return dict(rec)
        out = {}
        for f in self.fields:
            name = f["name"]
            if "const" in f:
                out[name] = f["const"]
            elif "concat" in f:
                parts = [str(self._dig(rec, p) or "") for p in f["concat"]]
                out[name] = f.get("sep", "").join(parts)
            else:
                val = self._dig(rec, f.get("from", name))
                cast = f.get("cast")
                out[name] = CASTS[cast](val) if cast else val
        return out
