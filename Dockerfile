# Stage 1: Build
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

# Install uv
RUN apt-get update && apt-get install -y curl && \
    curl -LsSf https://astral.sh/uv/install.sh | sh

# Copy project files
COPY pyproject.toml uv.lock ./
COPY src ./src

# Install dependencies
RUN /root/.cargo/bin/uv sync --locked

# Stage 2: Runtime
FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /app/src ./src

# Expose the port FastAPI runs on
EXPOSE 8000

# Command to run the application
CMD ["python", "-m", "mcp_server_qdrant.main", "--transport", "streamable-http"]
