#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if ! command -v uv >/dev/null 2>&1; then
  echo 'Installa uv e poi esegui uv sync mentre sei online.' >&2
  exit 1
fi
package_path="${1:-}"
if [[ -z "$package_path" ]]; then
  read -r -p 'Percorso del pacchetto SQLite (vuoto per il database principale): ' package_path
fi
if [[ -n "$package_path" ]]; then
  if [[ ! -f "$package_path" ]]; then
    echo 'Pacchetto inesistente: controlla il percorso.' >&2
    exit 1
  fi
  package_path="$(cd -- "$(dirname -- "$package_path")" && pwd)/$(basename -- "$package_path")"
  exec uv run --offline --frozen streamlit run app.py -- --storage "$package_path"
fi
exec uv run --offline --frozen streamlit run app.py
