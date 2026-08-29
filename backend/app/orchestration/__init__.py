"""Orquestracao agentiva com LangGraph.

Concentra o controle de fluxo: estado, nos, arestas condicionais, roteamento,
handoff entre agentes, checkpoint e retomada. Consome as demais capacidades
pelos contratos de `app.ports`, nunca pelas implementacoes.
"""
