FROM docker.io/library/python:3.11-slim

# SERVICE_DIR: subdirectory under src/ (e.g. "user_management", "product_catalogue")
# PORT:        uvicorn listen port
ARG SERVICE_DIR
ARG PORT=8000

# libpq-dev + gcc required by psycopg2-binary on slim images
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the shared NFR module before the service code.
# Services do sys.path.insert(0, "..") inside /app/<SERVICE_DIR>, so ".." resolves
# to /app — where nfr/ lives — making `from nfr.*` imports work identically to local dev.
COPY src/nfr/ /app/nfr/

# Copy the service source code
COPY src/${SERVICE_DIR}/ /app/${SERVICE_DIR}/

WORKDIR /app/${SERVICE_DIR}

RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=${PORT}
EXPOSE ${PORT}

CMD uvicorn main:app --host 0.0.0.0 --port ${PORT}
