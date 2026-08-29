"""Entrypoints dos servicos que podem rodar em processo proprio.

Cada subpacote aqui e um processo com ciclo de vida, porta e health proprios.
Nao confundir com `app.services`, que sao os servicos de dominio dentro do
backend: aqui estao **fronteiras de processo**, la estao modulos de negocio.

O que roda separado por padrao e decisao de configuracao, nao de codigo. O
`assistant-api` fala com `mcp-service` e `tool-service` pelos gateways de
`app.ports`, entao subir um deles em outro processo e mudar `MCP_TRANSPORT` ou
`TOOL_TRANSPORT` para `remote` - nenhum agente ou no de grafo percebe.
"""
