# Agent Audit Proxy. Default command: the free live demo (fake Claude).
# For the real proxy, see docs/deploy.md.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
# Runtime dependencies only (the dev extra isn't installed), exactly as locked.
RUN uv sync --locked

ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown -R app /app /data
USER app

EXPOSE 8080
CMD ["shugo", "spend", "demo", "--host", "0.0.0.0", "--port", "8080"]
