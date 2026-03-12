# Patra backend API. Image: plalelab/patra-backend:latest
# Build/push: ./scripts/build-push-backend.sh (from repo root)
FROM python:3.12-slim

WORKDIR /app

# Build context must be project root: docker build -f rest_server/Dockerfile -t plalelab/patra-backend:latest .
COPY rest_server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY rest_server/ ./rest_server/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8000\")}/healthz', timeout=3)"

CMD ["sh", "-c", "uvicorn rest_server.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
