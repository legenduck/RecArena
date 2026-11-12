FROM python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.24
COPY contracts contracts
COPY backend backend
COPY docker/entrypoint.py docker/record-build.py docker/
RUN uv sync --frozen --project backend --no-dev
ARG RECARENA_CODE_COMMIT
ARG RECARENA_SOURCE_TREE_SHA256
ARG RECARENA_CODE_DIRTY
RUN python docker/record-build.py
ENV PATH="/app/backend/.venv/bin:$PATH" RECARENA_BUILD_PROVENANCE=/app/build-provenance.json PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "/app/docker/entrypoint.py"]
CMD ["uvicorn", "recarena_platform.app:app", "--host", "0.0.0.0", "--port", "8010", "--no-access-log"]
