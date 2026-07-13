FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY ocdd_worker ./ocdd_worker
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 ocdd \
    && mkdir -p /data/artifacts \
    && chown -R ocdd:ocdd /app /data
USER ocdd

CMD ["celery", "-A", "ocdd_worker.celery_app:app", "worker", "--loglevel=INFO"]
