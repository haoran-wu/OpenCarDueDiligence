FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OCDD_DATABASE_PATH=/data/ocdd.sqlite3 \
    OCDD_DATA_ROOT=/app/data

WORKDIR /app
COPY services/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/api/app ./app
COPY data ./data

RUN useradd --create-home --uid 10001 ocdd && mkdir -p /data && chown -R ocdd:ocdd /data /app
USER ocdd

EXPOSE 8000
# Never let an untrusted Forwarded/X-Forwarded-For header rewrite the ASGI peer
# used by the reference limiter. A deployment-owned ingress may opt in only
# together with an explicit trusted --forwarded-allow-ips value.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
