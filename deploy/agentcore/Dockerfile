# AgentCore Runtime image shared by the HTTP agent and MCP SQL tools.
#
# This ships the same FastAPI process the workshop runs on the Code Editor host.
# Retrieval does not change when the harness moves: the agent's tools still read
# Aurora, and Aurora still decides which evidence exists and who may see it. The
# authorization that matters lives in service/retrieval_scope.py and
# service/agent_tools.py, not in whatever is hosting the process.
#
# Build from the repository root with `make agentcore-image`.
# The packaging script supplies an allowlisted context.
#
# AgentCore Runtime contract facts encoded below, HTTP protocol:
#   - ARM64 (Graviton). An x86 image will not start.
#   - Port 8080, bound to 0.0.0.0 so AgentCore can route to the container.
#   - Non-root process, no secrets in any layer.
#   - GET /ping and POST /invocations, served by deploy/agentcore/app.py. That
#     module mounts service.main:app whole and adds those two routes around it,
#     so the workshop application keeps its own surface unchanged. See
#     docs/agentcore-runtime.md, "How the contract routes are served".

# The digest pins the Amazon Linux 2023 minimal image and its package repository.
FROM --platform=linux/arm64 public.ecr.aws/amazonlinux/amazonlinux@sha256:68b1e82cd69ade271c092bc1959fa6fc820945d0c8dbb7a88cf6c1824a184688 AS base

RUN dnf install -y python3.13 shadow-utils libstdc++ && dnf clean all

FROM base AS builder

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
RUN dnf install -y python3.13-pip && dnf clean all
RUN python3.13 -m pip install --no-cache-dir uv==0.11.21

# Dependencies resolve from the committed lock alone, so this layer stays cached
# until pyproject.toml or uv.lock changes. --no-dev leaves pytest and ruff out of
# the runtime image.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --python /usr/bin/python3.13
RUN python3.13 -c "from urllib.request import urlretrieve; urlretrieve('https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem', '/app/rds-ca-bundle.pem')"


FROM base

RUN useradd --system --uid 1001 --create-home --home-dir /home/mosaic mosaic

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY pyproject.toml uv.lock ./
COPY --from=builder /app/rds-ca-bundle.pem /app/rds-ca-bundle.pem

# Every path is named. There is no `COPY . .` here on purpose: the build context
# root holds a real .env with a live Aurora DSN on a facilitator machine, and a
# recursive copy would bake it into a layer. DATABASE_URL arrives at run time
# from Secrets Manager instead. tests/test_agentcore_artifacts.py enforces this.
#
# The service reads more than its own package. db/ backs the retrieval
# fingerprint and the retrieval config; the named scripts are hashed into the
# same fingerprint; data/evals and data/benchmarks are the measured artifacts the
# scorecard and HNSW instrument replay; data/media and data/full carry the asset
# labels and the dataset manifest. The UI is deliberately absent: the storefront
# stays on the workshop host and talks to this service over HTTP.
COPY service/ ./service/
COPY db/ ./db/
COPY scripts/ ./scripts/
COPY data/benchmarks/ ./data/benchmarks/
COPY data/evals/ ./data/evals/
COPY data/media/asset_labels_200.json ./data/media/asset_labels_200.json
COPY data/media/workspace_collection.json ./data/media/workspace_collection.json
COPY data/full/manifest.json ./data/full/manifest.json

# Public downloads are part of the API, including when Runtime hosts it.
COPY skills/mosaic-hybrid-retrieval/ ./skills/mosaic-hybrid-retrieval/
COPY docs/build-retrieval-tool.md docs/use-in-your-app.md docs/mcp-interoperability.md docs/security-boundaries.md ./docs/
COPY examples/call_headphones.py ./examples/call_headphones.py

# Both native protocols share this image; the stack selects their entry point.
COPY deploy/agentcore/ ./deploy/agentcore/
COPY labs/ ./labs/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Runtime may create per-session files; dependencies and shipped source stay read-only.
RUN chown mosaic:mosaic /app
USER mosaic

EXPOSE 8080 8000

ENV MOSAIC_RUNTIME_MODE=agent
ENTRYPOINT ["python", "-m", "deploy.agentcore.entrypoint"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import os,socket; socket.create_connection(('127.0.0.1', 8000 if os.environ['MOSAIC_RUNTIME_MODE'] == 'tools' else 8080), timeout=3).close()"
