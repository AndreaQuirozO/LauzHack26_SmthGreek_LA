FROM python:3.13.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/update

COPY requirements-baseline.txt /opt/update/requirements-baseline.txt
COPY requirements-target.txt /opt/update/requirements-target.txt
RUN mkdir -p /opt/update/wheels
RUN python -m pip download --no-deps --only-binary=:all: --require-hashes \
    --dest /opt/update/wheels --requirement /opt/update/requirements-baseline.txt
RUN python -m pip download --no-deps --only-binary=:all: --require-hashes \
    --dest /opt/update/wheels --requirement /opt/update/requirements-target.txt

COPY run_update.py /opt/update/run_update.py
USER 10001:10001
ENTRYPOINT ["python", "-I", "/opt/update/run_update.py"]