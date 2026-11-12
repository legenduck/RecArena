FROM python:3.11.17-slim-bookworm@sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf
WORKDIR /app
COPY docker/freeze-apt.sh docker/
RUN sh docker/freeze-apt.sh libgomp1 libstdc++6 && pip install --no-cache-dir uv==0.12.24
COPY contracts contracts
COPY examples/pyproject.toml examples/uv.lock examples/.python-version examples/
COPY examples/data examples/data
COPY examples/scenarios examples/scenarios
COPY examples/judging examples/judging
COPY examples/llm examples/llm
COPY examples/recommendation/training examples/recommendation/training
COPY docker/record-build.py docker/
ARG RECARENA_TRAINING_EXTRA=training
RUN uv sync --frozen --project examples --extra "$RECARENA_TRAINING_EXTRA" --no-dev
ARG RECARENA_CODE_COMMIT
ARG RECARENA_SOURCE_TREE_SHA256
ARG RECARENA_CODE_DIRTY
RUN python docker/record-build.py
ENV PATH="/app/examples/.venv/bin:$PATH" RECARENA_BUILD_PROVENANCE=/app/build-provenance.json PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
CMD ["python", "-m", "recarena_training.pipeline", "--help"]
