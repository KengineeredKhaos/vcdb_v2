#!/usr/bin/env bash
set -euo pipefail
python -m pip install --upgrade pip wheel setuptools
pip freeze --exclude-editable > requirements.txt
echo "Wrote requirements.txt"
