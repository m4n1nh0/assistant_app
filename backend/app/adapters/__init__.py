"""Implementacoes concretas dos contratos declarados em `app.ports`.

Cada capacidade tem, no minimo, uma implementacao local (in-process), uma
remota (HTTP para o servico extraido) e uma fake (memoria, para teste). Quem
depende do contrato nao sabe qual esta ativa - a escolha e de
`app.adapters.container`, a partir da configuracao.
"""
