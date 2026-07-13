FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY obd_bridge ./obd_bridge
RUN pip install --no-cache-dir .
EXPOSE 8765
CMD ["uvicorn", "obd_bridge.service:app", "--host", "127.0.0.1", "--port", "8765"]
