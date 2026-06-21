# Shared application image: API, Celery worker, and the Logs-DB MCP server.
# Build context = repo root.
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1

# git + patch are the fallback path for the PR node's diff-apply (the common
# path uses the full file the Dev agent emits and needs neither).
RUN apt-get update && apt-get install -y --no-install-recommends curl git patch \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/ services/
COPY scripts/ scripts/

EXPOSE 8000
CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
