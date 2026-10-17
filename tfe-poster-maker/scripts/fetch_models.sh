#!/usr/bin/env bash
# Download AI models (checksum-verified) into vendor/models so they are bundled in the .app.
#   scripts/fetch_models.sh            -> recommended set (~1.2 GB)
#   scripts/fetch_models.sh all        -> every catalogue model (~2.5 GB)
#   scripts/fetch_models.sh hat-l-real drct-l-hq ...
set -euo pipefail
cd "$(dirname "$0")/.."
WHICH="${*:-default}"
PY="${PYTHON:-python3}"
[[ -x .venv/bin/python ]] && PY=.venv/bin/python
mkdir -p vendor/models
"$PY" -m tfe_poster models --download $WHICH --dest vendor/models
ls -lh vendor/models
