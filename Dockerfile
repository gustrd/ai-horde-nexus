# Use a slim Python image
FROM python:3.12-slim

# Install uv for speed
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
RUN uv sync --frozen

# Copy source code
COPY src/ ./src/
COPY configs/ ./configs/

# Ensure the config exists (even if empty example)
RUN cp configs/config.example.yaml configs/config.yaml || true

# Environment variables can be overridden at runtime
ENV PYTHONUNBUFFERED=1

# Command to run the worker
CMD ["uv", "run", "python", "-m", "src.main"]
