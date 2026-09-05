# Optional AgentCore Runtime image for the Mosaic retrieval service.
#
# This ships the same FastAPI process the workshop runs on the Code Editor host.
# Retrieval does not change when the harness moves: the agent's tools still read
# Aurora, and Aurora still decides which evidence exists and who may see it. The
# authorization that matters lives in service/retrieval_scope.py and
# service/agent_tools.py, not in whatever is hosting the process.
#
# The build context is the repository root:
#   docker buildx build --platform linux/arm64 -f deploy/agentcore/Dockerfile .
#
# AgentCore Runtime contract facts encoded below, HTTP protocol:
#   - ARM64 (Graviton). An x86 image will not start.
#   - Port 8080, bound to 0.0.0.0 so AgentCore can route to the container.
#   - Non-root process, no secrets in any layer.
# The endpoint names AgentCore checks are not the ones this app serves. See
# docs/agentcore-runtime.md, "Where the contract does not line up yet".

FROM --platform=linux/arm64 python:3.13.14-slim AS builder

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.21

# Dependencies resolve from the committed lock alone, so this layer stays cached
# until pyproject.toml or uv.lock changes. --no-dev leaves pytest and ruff out of
# the runtime image.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev


FROM --platform=linux/arm64 python:3.13.14-slim

RUN useradd --system --uid 1001 --create-home --home-dir /home/mosaic mosaic

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

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
COPY data/full/manifest.json ./data/full/manifest.json

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN chown -R mosaic:mosaic /app
USER mosaic

EXPOSE 8080

# 0.0.0.0 because AgentCore routes to the container over its internal network.
# Do not publish this port to the internet. Run it locally with
# `-p 127.0.0.1:8080:8080`, which is what `make agentcore-image-smoke` does.
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8080"]
