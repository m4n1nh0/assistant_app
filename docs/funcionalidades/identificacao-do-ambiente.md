# Identificação do ambiente

Mostra em qual servidor o app está conectado, para ninguém trabalhar em `localhost` achando que está na produção (ou o contrário).

## Onde aparece

O cabeçalho do app mostra uma etiqueta com o ambiente e o endereço do servidor conectado:
**PRODUÇÃO** (discreta, em verde), **LOCAL** ou **HOMOLOGAÇÃO** (em destaque âmbar) e
**SEM CONEXÃO** quando o servidor não responde. O tooltip traz o endereço completo, o commit
em execução e há quanto tempo o servidor está no ar.

O servidor informa o ambiente em `/health/live` (campo `environment`): `APP_ENV` manda quando
definido; sem ele, estar na Railway vale `production` (ou o nome do ambiente da Railway, se
for outro) e fora dela vale `local`. Nas páginas web (portal, quiz, inscrição, chamada), a
barra INTARQ ganha o selo **AMBIENTE LOCAL · TESTE** fora da produção; em produção o aluno
vê só a marca.
