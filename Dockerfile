# snowconnect — offline demo image (CLI/library, no web UI).
# The container runs the built-in demo once: mock SaaS API on localhost ->
# full pipeline -> sqlite stand-in -> prints Snowflake MERGE SQL. Exit 0 = OK.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

# Install the package first (better layer cache: source edits don't re-resolve deps).
COPY pyproject.toml README.md ./
COPY snowconnect/ snowconnect/
RUN pip install --no-cache-dir .

COPY examples/ examples/

# Non-root: the demo writes .snowconnect/demo_state.json under the workdir.
RUN useradd --create-home --uid 10001 demo && chown -R demo:demo /app
USER demo
WORKDIR /home/demo

ENTRYPOINT ["snowconnect"]
CMD ["demo"]
