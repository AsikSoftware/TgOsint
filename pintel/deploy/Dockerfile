FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY pintel_core ./pintel_core
COPY pintel_server ./pintel_server
RUN pip install --quiet ".[server]"
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn pintel_server.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
