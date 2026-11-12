FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY anvaya ./anvaya
# SQLite + uploads live in /data: mount a persistent disk/volume here.
ENV ANVAYA_DATA_DIR=/data
RUN useradd -m app && mkdir -p /data && chown app /data
USER app
EXPOSE 8000
# One worker on purpose: background jobs, SSE subscribers and rate limits are in-process.
CMD ["sh", "-c", "uvicorn anvaya.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
