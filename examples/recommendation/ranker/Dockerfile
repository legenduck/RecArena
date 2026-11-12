FROM eclipse-temurin:21.0.10_7-jre-jammy@sha256:fa4854e6057665066cb79953616671c20f32b96a85d6dd8b78db0762203924c4 AS java
FROM python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
WORKDIR /app
COPY --from=java /opt/java/openjdk /opt/java/openjdk
COPY docker/freeze-apt.sh docker/
RUN sh docker/freeze-apt.sh libgomp1 libstdc++6 && pip install --no-cache-dir uv==0.12.24
COPY contracts contracts
COPY examples/recommendation/ranker examples/recommendation/ranker
COPY examples/data examples/data
COPY docker/entrypoint.py docker/record-build.py docker/
RUN uv sync --frozen --project examples/recommendation/ranker
ARG RECARENA_CODE_COMMIT
ARG RECARENA_SOURCE_TREE_SHA256
ARG RECARENA_CODE_DIRTY
RUN python docker/record-build.py
ENV PATH="/app/examples/recommendation/ranker/.venv/bin:/opt/java/openjdk/bin:$PATH" JAVA_HOME=/opt/java/openjdk RECARENA_BUILD_PROVENANCE=/app/build-provenance.json PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
ENTRYPOINT ["python", "/app/docker/entrypoint.py"]
CMD ["python", "-m", "recarena_ranker.serve", "--host", "0.0.0.0", "--port", "8011", "--no-access-log"]
