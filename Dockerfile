FROM node:24.15.0-bookworm-slim@sha256:4e6b70dd6cbfc88c8157ba19aa3d9f9cce6ba4703576d55459e45efcbc9c5f5d AS node
FROM python:3.13.13-slim-bookworm@sha256:355bfa66770995d7e9a0da4b3473b44d0cb451f6b56f5615ad9c39e3c4eca03f
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libgomp1 ca-certificates fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
WORKDIR /app
COPY requirements.txt requirements.lock package.json package-lock.json .npmrc ./
RUN pip install --no-cache-dir -r requirements.txt && npm install --global npm@11.12.1 && npm ci --omit=dev
COPY backend/__init__.py backend/local_ocr.py ./backend/
COPY scripts/download_local_models.py ./scripts/
RUN python scripts/download_local_models.py
COPY download-models.cjs ./
RUN node download-models.cjs
COPY . .
RUN useradd --create-home appuser && mkdir -p /data/photos && chown -R appuser:appuser /data /app/model-cache
USER appuser
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready')"
CMD ["uvicorn","backend.main:app","--host","0.0.0.0","--port","8000"]
