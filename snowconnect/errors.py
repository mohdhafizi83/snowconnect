"""Exception types for connector failures.

``ConnectorError`` subclasses ``RuntimeError`` so callers that previously
caught ``RuntimeError`` (v0.1 behaviour) keep working.
"""
from __future__ import annotations


class ConnectorError(RuntimeError):
    """A connector failed for a policy, transport, or configuration reason."""


class SSRFError(ConnectorError, ValueError):
    """A spec-provided URL was rejected by the SSRF guard.

    Subclasses ``ValueError`` as well for backwards compatibility with v0.1,
    where unsafe URLs raised ``ValueError``.
    """
