"""Nucleo tecnico compartilhado pelos servicos.

O que mora aqui serve a qualquer processo e nao sabe nada do produto:
configuracao de processo, observabilidade, contratos (`ports`) e o cliente MCP.
A regra que define o pacote e uma so, e ha teste para ela
(`tests/test_import_boundaries.py`): **nada em `shared` importa `app`**.

E essa regra que deixa um servico depender so do nucleo. O mcp-service e o
exemplo: a imagem dele nao copia `app/`.
"""
