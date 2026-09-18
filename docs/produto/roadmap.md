# Roadmap do produto

Levantado em **18/09/2026**, a partir de todos os documentos de
`docs/funcionalidades/` e `docs/arquitetura/`, com cada pendência **conferida
contra o código** — a documentação tinha itens já entregues e itens listados
como prontos que não existem.

Para o plano comercial de 30 dias (marca, instalador, LGPD, piloto), veja
[Roadmap comercial](roadmap-comercial.md). Este documento é sobre o produto.

---

## 1. O que a documentação dizia e não é mais verdade

Entregue desde que aqueles textos foram escritos:

| Item listado como pendente | Onde estava | Situação real |
|---|---|---|
| Quiz consolidado de várias aulas/período | `quiz/gerador-automatico.md` | **Feito**: aulas e materiais se somam como fontes |
| Preview/revisão das questões antes de liberar | `quiz/flutter.md` | **Feito**: revisão antes de liberar o QR Code |
| Edição das questões | `quiz/gerador-automatico.md` | **Feito** em rascunho; quiz já aplicado é protegido |
| Banco de questões reutilizável | `quiz/websocket-qrcode.md` | **Feito**: busca, filtros, arquivar e montar quiz com questões existentes |
| WebSocket sem polling no monitor | `quiz/flutter.md` | **Feito** |
| Notificação quando o quiz fica pronto | `quiz/modo-educacao.md` | **Feito para o professor** (aviso no app, Telegram e WhatsApp). Para alunos, não existe |

Fora das listas, entregue depois delas: fila persistente de geração, central de
quizzes, gravação de apresentação de grupo e de palestra, separação dos serviços
(orquestrador, tool-service, mcp-service) e deploy na Railway.

---

## 2. Pendências reais, por tema

### Segurança (é o que está mais atrasado)

| Pendência | Risco hoje |
|---|---|
| **`/ws/quiz/{id}/monitor` não tem autenticação** | Quem souber o id do quiz vê respostas, nomes e ranking da turma em tempo real. O id circula no QR Code |
| **Aluno sem identidade** | Nome digitado e cookie; dá para responder duas vezes em outro navegador, e um nome pode se passar por outro |
| **Réplica única obrigatória** | O WebSocket da sessão e a fila de quiz vivem num processo; escalar a API horizontalmente quebra os dois |

### Quiz

- relatório de desempenho por aluno e por questão, além do ranking;
- exportação dos resultados (PDF/planilha) — hoje só existe PDF de aula e relatório acadêmico;
- embaralhar alternativas entre alunos;
- regenerar quiz com base no que a turma errou;
- avisar a turma quando o quiz abre (depende de identidade do aluno);
- integração com calendário e com as notas da turma.

### Integrações acadêmicas

Hoje existe só o SIA/Estácio, por WebView autenticado. Pendente:

- adaptador genérico para SIGAA, Moodle, Blackboard e Canvas;
- credenciais por sistema, guardadas e cifradas;
- sincronização em lote de um período inteiro;
- mapeamento `INTARQ → sistema acadêmico` com aprovação manual;
- sincronização de notas e calendários;
- auditoria dessas sincronizações.

### Especificações que nunca saíram do papel

Três documentos grandes descrevem sistemas inteiros marcados como "Fase 3" e
sem implementação correspondente. Eles descrevem o alvo, não o que existe:

| Documento | O que existe hoje |
|---|---|
| `agentes-por-disciplina.md` (agentes auto-treináveis) | Especialistas fixos por tarefa, sem treino nem adaptação por disciplina |
| `deteccao-alucinacao.md` (validação multicamada) | `grounding_score` vindo do próprio modelo e a ancoragem no cadastro de aulas |
| `memoria-multi-turno.md` (cache com TTL) | Busca no Qdrant a cada turno, sem cache nem expiração |

Antes de implementar, vale decidir se ainda é o alvo: os três foram escritos
antes da arquitetura atual.

### Plataforma

- fila de quiz e WebSocket presos a uma réplica (ver Segurança);
- o orquestrador é obrigatório para o chat quando remoto: sem réplica reserva, ele é ponto único de falha;
- sem alerta automático quando um provedor de IA fica sem crédito — hoje o professor descobre na hora de gerar.

### Qualidade

Metas declaradas e nunca medidas: acurácia da validação de alucinação, média de
grounding, tempo de resposta do player, taxa de conclusão de quiz. Não há
conjunto de avaliação nem medição registrada.

---

## 3. Roadmap proposto

### Onda 1 — Fechar o que já está no ar (1 a 2 semanas)

Objetivo: o que hoje está exposto passa a ser defensável.

1. **Autenticar o monitor do quiz**: token do professor no WebSocket e checagem de dono do quiz.
2. **Identidade mínima do aluno**: código de entrada por turma ou vínculo com o aluno cadastrado, para a resposta valer como registro.
3. **Aviso de provedor sem crédito** no painel e ao enfileirar quiz.

*Pronto quando:* um quiz aplicado em turma real tem autoria confiável e ninguém de fora acompanha o monitor.

### Onda 2 — Fechar o ciclo pedagógico (2 a 4 semanas)

Objetivo: o professor usa o resultado, não só aplica o quiz.

1. **Relatório de desempenho**: por aluno, por questão e por turma, reaproveitando o gerador de PDF que já existe.
2. **Exportação** dos resultados junto com o relatório de pontuação.
3. **Regenerar com foco no erro**: novo quiz a partir das questões que a turma mais errou — o banco de questões já dá a base.
4. **Embaralhar alternativas** por aluno.

*Pronto quando:* depois da aula, o professor sai com um relatório pronto para lançar nota e um quiz de reforço.

### Onda 3 — Sair do SIA (4 a 8 semanas)

1. Contrato de adaptador acadêmico, com o SIA como primeira implementação.
2. Credenciais por sistema, cifradas como já são as chaves de IA.
3. Mapeamento de alunos com aprovação manual e auditoria.
4. Um segundo sistema de verdade (Moodle é o mais provável) antes de prometer "multi-sistema".

*Pronto quando:* trocar de instituição é configuração, não desenvolvimento.

### Onda 4 — Escala e inteligência (depois do piloto)

1. **Escalar horizontalmente**: sessão do WebSocket e fila de quiz compartilhadas (Redis), o que hoje limita a uma réplica.
2. **Memória multi-turno com cache**, se a latência do chat virar queixa real.
3. **Validação de alucinação medida**, com conjunto de avaliação e número publicado.
4. **Adaptação por disciplina**, começando por prompt com histórico da disciplina, antes de qualquer treino.

---

## 4. Decisões que dependem de você

1. **Identidade do aluno**: código por turma (simples, anônimo) ou vínculo com o cadastro (permite nota, exige mais cuidado com dado pessoal)?
2. **Os três documentos de "Fase 3"**: viram roadmap de verdade, ou são arquivados como estudo?
3. **Multi-instituição**: vale investir nos adaptadores antes de ter um segundo cliente pedindo?
4. **Escala**: o piloto vai ter quantas turmas simultâneas? Abaixo de uma centena de alunos ao mesmo tempo, a réplica única aguenta e a Onda 4 pode esperar.

---

## 5. Rastreio por documento

| Documento | Pendências reais |
|---|---|
| `quiz/websocket-qrcode.md` | WebSocket autenticado; gráficos; exportação |
| `quiz/flutter.md` | Relatórios e exportação |
| `quiz/gerador-automatico.md` | Relatório por aluno; regeneração com feedback; exportação para material impresso |
| `quiz/modo-educacao.md` | Análise por aluno; embaralhar alternativas; calendário; aviso à turma |
| `quiz/testes.md` | Metas de qualidade nunca medidas |
| `sistema-academico.md` | Tudo além do SIA |
| `agentes-por-disciplina.md`, `deteccao-alucinacao.md`, `memoria-multi-turno.md` | Especificações inteiras, sem implementação |
| `arquitetura/agentes.md` | Réplica única; orquestrador como ponto único |
