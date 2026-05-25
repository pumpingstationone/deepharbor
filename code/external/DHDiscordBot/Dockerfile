FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY . /app
WORKDIR /app
RUN uv sync --frozen --no-cache

CMD ["/app/.venv/bin/python", "bot.py"]
