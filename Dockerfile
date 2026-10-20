# Pinned by digest for reproducible builds. To pick up security updates, run
# docker pull python:3.12-slim and replace the digest with the new one.
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

WORKDIR /app

RUN useradd --create-home --uid 1000 yotolib \
    && mkdir -p /data \
    && chown yotolib:yotolib /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py extractor.py gdrive.py server.py yotolib.py ./
COPY static ./static

USER yotolib

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    YOTOLIB_HOST=0.0.0.0 \
    YOTOLIB_PORT=8765 \
    YOTOLIB_OPEN_BROWSER=0 \
    YOTOLIB_DATA_DIR=/data

EXPOSE 8765

CMD ["python", "yotolib.py"]
