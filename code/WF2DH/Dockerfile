#
# docker build -t dhservice:latest .
#

FROM python:3.12-slim

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system dependencies.
# Curl is needed for health checks.
RUN apt-get update && apt-get install -y curl

# Copy the application into the container.
COPY . /app

# Install the application dependencies.
WORKDIR /app
RUN uv sync --frozen --no-cache

EXPOSE 8000

# Run the application.
# NOTE! the host is set to 0.0.0.0 which means that it will be accessible from outside the container.
CMD ["/app/.venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]