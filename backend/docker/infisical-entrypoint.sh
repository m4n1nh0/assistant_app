#!/bin/sh
# Entrada dos servicos: busca os segredos no Infisical e sobe o processo com eles no ambiente.
#
#   infisical-entrypoint <comando...>
#
# Sem nenhuma variavel INFISICAL_*, executa o comando direto: e o comportamento de sempre
# (docker compose, desenvolvimento local, instalacao sem cofre).
#
# Com o cofre ligado, ele FALHA FECHADO: faltou variavel, o login foi recusado ou o cofre nao
# respondeu, o servico nao sobe. Subir sem os segredos cairia nos valores padrao do codigo
# (`change-me-jwt`), que e pior que ficar fora do ar.
#
# Variaveis (as do cofre ficam no Railway; todo o resto vem do proprio cofre):
#   INFISICAL_PROJECT_ID                       id do projeto no Infisical            (obrigatoria)
#   INFISICAL_UNIVERSAL_AUTH_CLIENT_ID         identidade de maquina deste servico   (obrigatoria*)
#   INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET     segredo da identidade                 (obrigatoria*)
#   INFISICAL_TOKEN                            alternativa: token ja emitido         (*ou este)
#   INFISICAL_ENV                              ambiente do cofre, padrao "prod"
#   INFISICAL_SECRET_PATH                      pasta do servico, padrao "/"
#   INFISICAL_DOMAIN                           so fora da nuvem US (ex.: https://eu.infisical.com)
#
# Depois de subir, o processo recebe INFISICAL_INJECTED=1. Com INFISICAL_REQUIRED=true o
# servico recusa-se a iniciar sem esse marcador (shared/settings.py): pega o caso do "Start
# command" do Railway, que SUBSTITUI o ENTRYPOINT e pularia este script em silencio.

set -eu

die() {
    echo "infisical-entrypoint: $1" >&2
    exit 78
}

vault_on=false
for name in INFISICAL_PROJECT_ID INFISICAL_TOKEN INFISICAL_UNIVERSAL_AUTH_CLIENT_ID \
            INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET; do
    eval "value=\${$name:-}"
    [ -n "$value" ] && vault_on=true
done

if [ "$vault_on" = false ]; then
    exec "$@"
fi

[ "$#" -gt 0 ] || die "nenhum comando para executar"
[ -n "${INFISICAL_PROJECT_ID:-}" ] || die "INFISICAL_PROJECT_ID nao definido"
command -v infisical >/dev/null 2>&1 || die "o CLI do Infisical nao esta na imagem"

if [ -z "${INFISICAL_TOKEN:-}" ]; then
    [ -n "${INFISICAL_UNIVERSAL_AUTH_CLIENT_ID:-}" ] || die "INFISICAL_UNIVERSAL_AUTH_CLIENT_ID nao definido"
    [ -n "${INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET:-}" ] || die "INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET nao definido"
    # O CLI le o client id e o secret do ambiente, entao nenhum dos dois aparece na lista de
    # processos. Tres tentativas cobrem uma oscilacao de rede no boot, sem esconder erro real.
    attempt=1
    token=""
    while [ "$attempt" -le 3 ]; do
        if token=$(infisical login --method=universal-auth --plain --silent) && [ -n "$token" ]; then
            break
        fi
        token=""
        [ "$attempt" -lt 3 ] && sleep "${INFISICAL_LOGIN_RETRY_DELAY:-2}"
        attempt=$((attempt + 1))
    done
    [ -n "$token" ] || die "login no Infisical recusado ou fora do ar (conferir client id/secret e INFISICAL_DOMAIN)"
    export INFISICAL_TOKEN="$token"
fi

# O secret de login ja cumpriu o papel; o processo do servico nao precisa dele.
unset INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET

export INFISICAL_INJECTED=1
export INFISICAL_DISABLE_UPDATE_CHECK=true

exec infisical run --silent \
    --projectId "$INFISICAL_PROJECT_ID" \
    --env "${INFISICAL_ENV:-prod}" \
    --path "${INFISICAL_SECRET_PATH:-/}" \
    -- "$@"
