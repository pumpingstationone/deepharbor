#
# docker build -t rfid2db:latest .
#

FROM python:3.12-slim

# Install system dependencies.
# Curl is needed for health checks.
RUN apt-get update && apt-get install -y curl

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy the application into the container.
COPY . /app

# Install the application dependencies.
WORKDIR /app
RUN uv sync --locked

CMD ["uv", "run", "/app/main.py"]
