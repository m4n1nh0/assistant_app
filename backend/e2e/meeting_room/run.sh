#!/usr/bin/env bash
# Teste de ponta a ponta da reuniao online propria: navegadores de verdade, LiveKit de
# verdade e o nosso backend, tudo em Docker. Nao faz parte do pytest (precisa de Docker e
# baixa o Chromium); rode quando mexer na sala, na pagina ou no token do LiveKit.
#
# Uso:  bash backend/e2e/meeting_room/run.sh
#
# Precisa de um volume Docker com as dependencias do backend instaladas para o Python 3.14
# (padrao: `assistant_pydeps`, o mesmo usado para rodar o pytest em contêiner):
#   docker run --rm -v assistant_pydeps:/deps -v "$PWD/backend:/app" python:3.14-slim \
#       pip install --target /deps -r /app/requirements.txt
#
# O que confere: dois navegadores entram na sala, o video de um chega ao outro, o nome do
# aluno vem do cadastro, a fala de cada um vira trecho "Nome: texto", a presenca fecha, o
# aluno sai, e o professor encerra para todos.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$(cd "$HERE/../.." && pwd)"
DEPS_VOLUME="${DEPS_VOLUME:-assistant_pydeps}"
NET=meetnet

# No Git Bash do Windows os caminhos precisam ser convertidos para o Docker.
if command -v cygpath >/dev/null 2>&1; then
  BACKEND_PATH="$(cygpath -w "$BACKEND")"
  HERE_PATH="$(cygpath -w "$HERE")"
  export MSYS_NO_PATHCONV=1
else
  BACKEND_PATH="$BACKEND"
  HERE_PATH="$HERE"
fi

cleanup() { docker rm -f meet-lk meet-api >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
docker network create "$NET" >/dev/null

# O backend de teste conversa com o LiveKit pelo nome "lk".
docker run -d --name meet-lk --network-alias lk --network "$NET" \
  livekit/livekit-server --dev --bind 0.0.0.0 >/dev/null

docker run -d --name meet-api --network "$NET" \
  -v "$BACKEND_PATH:/app" -v "$DEPS_VOLUME:/deps" -v "$HERE_PATH:/e2e:ro" \
  -e PYTHONPATH=/deps:/app:/e2e -w /app python:3.14-slim \
  python -m uvicorn e2e_server:app --host 0.0.0.0 --port 8000 >/dev/null

echo "Esperando o backend e o LiveKit subirem..."
for _ in $(seq 1 40); do
  if docker run --rm --network container:meet-api python:3.12-slim \
      python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/__stats')" \
      >/dev/null 2>&1; then break; fi
  sleep 2
done

# O navegador roda na rede do backend para acessar por localhost: camera e microfone so
# funcionam em HTTPS ou localhost.
docker run --rm --network container:meet-api --shm-size=1g \
  -v "$HERE_PATH/e2e_client.py:/e2e_client.py:ro" python:3.12-slim sh -c \
  "pip install -q playwright >/dev/null 2>&1; playwright install --with-deps chromium >/tmp/pw.log 2>&1 || { tail -5 /tmp/pw.log; exit 1; }; python -u /e2e_client.py"
