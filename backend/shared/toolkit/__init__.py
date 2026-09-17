"""Governanca de ferramentas: catalogo e execucao, sem saber quais ferramentas existem.

`ToolRegistry` guarda contrato, escopo e origem; `ToolExecutor` valida, aplica
timeout, repete o que e transitorio e audita. Nenhum dos dois conhece as
ferramentas do produto - quem as registra e `app.toolkit.catalog`.

Estar em `shared` e o que permite o mesmo executor governar o catalogo da API, o
do tool-service, o da maquina do usuario e o do orquestrador.
"""
