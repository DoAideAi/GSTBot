# GSTBot backend.
#
# Two stages so the runtime image does not carry a compiler. The build stage
# resolves wheels into a virtualenv, the runtime stage copies that venv and
# nothing else — which is also why dependencies are installed before the source
# is copied: editing a router should not reinstall psycopg.

# ---------- build ----------
FROM python:3.14-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# build-essential is needed by any dependency without a manylinux wheel for
# this platform (notably on arm64); it stays in this stage.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt


# ---------- runtime ----------
FROM python:3.14-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# tesseract is the OCR fallback for image invoices when no vision model is
# reachable. libpq5 is psycopg's runtime library. curl is here for the
# container healthcheck and nothing else.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/venv /opt/venv

# Invoices are customer tax documents; the process that writes them does not
# need to be able to rewrite its own code.
RUN useradd --create-home --uid 10001 gstbot
WORKDIR /app

COPY --chown=gstbot:gstbot alembic.ini ./
COPY --chown=gstbot:gstbot alembic ./alembic
COPY --chown=gstbot:gstbot app ./app
COPY --chown=gstbot:gstbot docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Declared so the directory exists and is owned correctly even when no volume
# is mounted over it.
RUN mkdir -p /app/data/invoices && chown -R gstbot:gstbot /app/data
VOLUME ["/app/data"]

USER gstbot
EXPOSE 8000

# --start-period covers the migration run on the first boot: the API is not
# listening yet and that is not a failure.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health/live || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["api"]
