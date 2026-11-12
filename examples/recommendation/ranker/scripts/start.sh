#!/usr/bin/env bash
set -euo pipefail
RECARENA_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$RECARENA_ROOT"
if [[ -n "${RECARENA_INSTANCE_ENV:-}" ]]; then source "$RECARENA_INSTANCE_ENV"; fi
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
# This optional provider receives no platform administration/database credentials.
unset RECARENA_ADMIN_TOKEN RECARENA_SESSION_API_KEY RECARENA_DATABASE_URL
exec uv run --frozen --project examples/recommendation/ranker python -m recarena_ranker.serve "$@"
