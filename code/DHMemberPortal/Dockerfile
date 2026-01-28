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

# Set Flask environment variables
ENV FLASK_APP=app.py

EXPOSE 5002

# Run the application using waitress WSGI server
# --trusted-proxy '*' tells waitress to trust proxy headers from any source
# --trusted-proxy-headers 'x-forwarded-for x-forwarded-host x-forwarded-proto x-forwarded-port' tells waitress which headers to trust
CMD ["/app/.venv/bin/python", "-m", "waitress", "--host=0.0.0.0", "--port=5002", "--trusted-proxy=*", "--trusted-proxy-headers=x-forwarded-for x-forwarded-host x-forwarded-proto x-forwarded-port", "--log-untrusted-proxy-headers", "app:app"]
