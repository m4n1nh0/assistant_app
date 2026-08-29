"""Contratos que o dominio usa para falar com o mundo externo.

Aqui so existem `Protocol` e tipos de dados. Nenhum modulo deste pacote importa
SDK, cliente HTTP ou framework: e isso que permite trocar a implementacao
(in-process por remota, real por fake de teste) sem tocar em agente, no de
grafo ou regra de negocio.
"""
