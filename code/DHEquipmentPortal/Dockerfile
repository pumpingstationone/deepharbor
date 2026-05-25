#
# docker build -t dhequipmentportal:latest .
#

FROM python:3.14-slim

ARG GIT_VERSION=unknown

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system dependencies.
RUN apt-get update && apt-get install -y curl

# Copy the application into the container.
COPY . /app

# Write git version into config for footer display
RUN echo "[git]" > /app/git_version.ini && echo "version=${GIT_VERSION}" >> /app/git_version.ini

# Install the application dependencies.
WORKDIR /app
RUN uv sync --frozen --no-cache

EXPOSE 5003

# Run with gunicorn for production, or Flask dev server
CMD ["/app/.venv/bin/python", "-m", "flask", "run", "--host", "0.0.0.0", "--port", "5003"]
