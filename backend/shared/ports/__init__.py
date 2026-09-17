"""Contratos tecnicos que servem a mais de um processo.

Aqui so existem `Protocol` e tipos de dados. Nenhum modulo deste pacote importa
SDK, cliente HTTP ou framework: e isso que permite trocar a implementacao
(in-process por remota, real por fake de teste) sem tocar em agente, no de
grafo ou regra de negocio.

Contratos que dependem do dominio do produto - o turno do chat, a busca nas
aulas - ficam em `app.ports`.
"""
