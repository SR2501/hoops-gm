# Backend image.
#
# Development-oriented, matching ADR-001: this runs on the owner's laptop, not
# on a cluster. Small and obvious beats a multi-stage build that is hard to
# debug at speed.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY alembic ./alembic

# The published port is bound to the host loopback in docker-compose.yml. The
# process must bind 0.0.0.0 inside the container or that mapping cannot reach
# it. See the comment on the port mapping, and ADR-001.
ENV HOST=0.0.0.0 \
    PORT=8000 \
    LOG_FORMAT=json \
    DATABASE_URL=sqlite:////data/hoops_gm.db

EXPOSE 8000

# Migrate then serve. On a single-user local tool, an app that starts against a
# schema it does not match is a worse failure than a slightly slower start.
CMD ["sh", "-c", "alembic upgrade head && python -m hoops_gm"]
