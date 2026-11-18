# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2

FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

COPY constraints.txt /tmp/motion-constraints.txt

RUN python -m pip install --constraint /tmp/motion-constraints.txt \
    "build==1.5.0" \
    "setuptools==80.9.0" \
    "wheel==0.45.1"

COPY pyproject.toml README.md LICENSE NOTICE.md ./
COPY src ./src

RUN python -m build --wheel --no-isolation --outdir /dist


FROM ${PYTHON_IMAGE} AS runtime-base

ARG MOTION_UID=1000
ARG MOTION_GID=1000

ENV HOME=/home/motion \
    MOTION_PROJECT_ROOT=/workspace \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid "${MOTION_GID}" motion \
    && useradd --create-home --uid "${MOTION_UID}" --gid "${MOTION_GID}" motion \
    && mkdir -p \
        /workspace/data/maps \
        /workspace/data/telemetry \
        /workspace/artifacts/here \
        /workspace/artifacts/models \
        /workspace/var/runtime \
        /workspace/outputs \
    && chown -R motion:motion /workspace

COPY --from=builder /dist /tmp/motion-dist
COPY constraints.txt /tmp/motion-constraints.txt

RUN set -eu; \
    motion_wheel="$(find /tmp/motion-dist -maxdepth 1 -type f -name 'motion-*.whl' -print -quit)"; \
    test -n "${motion_wheel}"; \
    python -m pip install --constraint /tmp/motion-constraints.txt "${motion_wheel}[ml]"; \
    rm -rf /tmp/motion-dist /tmp/motion-constraints.txt

COPY --chown=motion:motion data/reference /workspace/data/reference
COPY --chown=motion:motion artifacts/reference /workspace/artifacts/reference

WORKDIR /workspace
USER motion

ENTRYPOINT ["motion"]
CMD ["--help"]


FROM runtime-base AS runtime-carla

USER root

COPY --from=builder /dist /tmp/motion-dist
COPY constraints.txt /tmp/motion-constraints.txt

RUN set -eu; \
    motion_wheel="$(find /tmp/motion-dist -maxdepth 1 -type f -name 'motion-*.whl' -print -quit)"; \
    test -n "${motion_wheel}"; \
    python -m pip install --constraint /tmp/motion-constraints.txt "${motion_wheel}[carla]"; \
    rm -rf /tmp/motion-dist /tmp/motion-constraints.txt

USER motion


FROM runtime-base AS test

USER root

COPY --from=builder /dist /tmp/motion-dist
COPY constraints.txt /tmp/motion-constraints.txt

RUN set -eu; \
    motion_wheel="$(find /tmp/motion-dist -maxdepth 1 -type f -name 'motion-*.whl' -print -quit)"; \
    test -n "${motion_wheel}"; \
    python -m pip install --constraint /tmp/motion-constraints.txt "${motion_wheel}[dev]"; \
    rm -rf /tmp/motion-dist /tmp/motion-constraints.txt

COPY --chown=motion:motion pyproject.toml /opt/motion/pyproject.toml
COPY --chown=motion:motion tests /opt/motion/tests

WORKDIR /opt/motion
USER motion

ENTRYPOINT ["python", "-m", "pytest"]
CMD ["--cov=motion", "--cov-report=term-missing"]


FROM runtime-base AS runtime
