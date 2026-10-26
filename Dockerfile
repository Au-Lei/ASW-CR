FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium \
    && groupadd -g 10001 etd \
    && useradd -m -u 10001 -g etd etd \
    && mkdir -p /app/data /app/logs \
    && chown -R etd:etd /app/data /app/logs \
    && chmod -R a+rX /ms-playwright
COPY etd_sync ./etd_sync
USER etd
EXPOSE 8000
CMD ["python", "-m", "etd_sync.web", "--host", "0.0.0.0"]
