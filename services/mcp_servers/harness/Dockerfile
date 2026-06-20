# Harness MCP image: needs the Docker CLI + compose plugin + git so it can
# spin up sub-stacks (via the mounted docker.sock) and git-apply patches.
# Build context = repo root.
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg git patch \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# Lean dependency set — the harness doesn't need the LLM / embedding stack.
RUN pip install --no-cache-dir \
        "mcp==1.27.2" "pyyaml==6.0.2" "docker==7.1.0" \
        "pydantic==2.13.4" "pydantic-settings==2.7.1"

COPY services/ services/

EXPOSE 8001
CMD ["python", "-m", "services.mcp_servers.harness.server"]
