#!/usr/bin/env bash
# Gera a documentacao completa do codigo-fonte em site/:
#   - backend: mkdocs + mkdocstrings, a partir das docstrings de backend/app
#   - interface: dart doc, a partir dos comentarios /// de interface/lib
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> mkdocs build (backend + paginas manuais)"
python -m mkdocs build --clean

echo "==> dart doc (interface Flutter)"
if command -v flutter >/dev/null 2>&1; then
  (
    cd interface
    flutter pub get
    # A saida vai para dentro do site do mkdocs, entao o link relativo
    # referencia/interface/api/ funciona no site final.
    dart doc --output "$ROOT/site/referencia/interface/api"
  )
else
  echo "!! flutter nao encontrado no PATH; pulando a referencia Dart." >&2
fi

echo "==> pronto: $ROOT/site/index.html"
