FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Keep the container alive so the harness can exec pytest into it.
CMD ["sleep", "infinity"]
