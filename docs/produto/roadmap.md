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

### Aplicativo mobile

Hoje existe uma interface só, Flutter para Windows (`interface/windows` é a
única pasta de plataforma). Tudo depende do notebook aberto — inclusive gravar,
que é a função mais usada e a que menos precisa de tela: hoje, para registrar
uma aula, uma palestra ou a apresentação de um grupo, o professor tem que
carregar e abrir o notebook antes de começar.

Chamada pelo SIA, QR Code do quiz e monitor ao vivo continuam melhores no
desktop: são feitos sentado, projetando, com a tela grande. Num tablet, parte
deles volta a fazer sentido.

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

### Onda 3 — Aplicativo mobile (3 a 5 semanas)

Objetivo: o celular vira o gravador e o consulente. **Não** vira um clone da
desktop.

**Mesmo projeto, não um segundo app.** O caminho é acrescentar os alvos Android
e iOS ao projeto Flutter que já existe e tornar o layout responsivo, e não
duplicar o código. Duas interfaces separadas significariam dois lugares para
corrigir cada regra, e a experiência das últimas entregas mostra que regra
duplicada diverge na primeira correção.

**O recorte por tamanho de tela**, que é o que decide o que vale portar:

| Função | Celular | Tablet | Desktop |
|---|---|---|---|
| Gravar — aula, palestra e apresentação de grupo | **Melhor aqui**: o professor está em pé, o microfone vai junto, e não precisa abrir o notebook para começar | sim | sim |
| Pontuar aluno citando o nome em voz alta | **vem junto com a gravação**: é o mesmo áudio, não é tela nova | sim | sim |
| Marcar presença na mão, andando pela sala | **melhor aqui**: lista de nomes com um toque cada | sim | sim |
| Enviar material fotografando o quadro ou o slide | **só faz sentido aqui**: o backend já lê foto por OCR (`extract_image_sync`), falta a câmera — no desktop é seletor de arquivo | sim | parcial |
| Consultar aulas, transcrições e resumos; chat | sim | sim | sim |
| Ouvir o resumo da aula pela narração que já existe | **bom aqui**: serve no deslocamento, sem tela | sim | sim |
| Consultar a agenda e o histórico de conversas | sim | sim | sim |
| Receber aviso de quiz pronto na fila | sim (com notificação do sistema, não só aviso no app) | sim | sim |
| Ver relatório de pontuação e de presença; gerar o PDF | leitura sim; gerar e enviar, avaliar | **sim** | sim |
| Consultar grupos de projeto e seus integrantes | leitura sim | **sim** | sim |
| Revisar e editar as questões geradas | ruim: texto longo em tela estreita | **sim** | sim |
| Central de quizzes | não | **sim** | sim |
| Cadastrar turmas, alunos e disciplinas | não: formulário longo | sim | **sim** |
| Importar tempo de estudo (planilha) | não: confirmação com dezenas de linhas | avaliar | **sim** |
| Configurar chaves de IA, atalhos e integrações | só o login | parcial | **sim** |
| Chamada pelo SIA | não: é WebView autenticado, feito sentado | avaliar | **sim** |
| QR Code da chamada e monitor ao vivo do quiz | não: a tela é projetada para a turma | avaliar | **sim** |
| Rodar script, abrir projeto, ler janela e apps (`local_*_service`) | não existe: o sistema não permite | não | **sim** |
| Atalho que abre o app da instituição, disca, compartilha ou põe na agenda | **só existe aqui**: é o equivalente móvel do atalho de app | sim | não: no desktop o alvo é executável ou URL |

Os três primeiros itens são o argumento da onda: **o que ganha no celular é o
que acontece de pé, em sala** — gravar, pontuar, marcar presença e fotografar o
quadro. O resto é consulta, e consulta cabe em qualquer tela.

**O assistente continua sendo assistente no celular** — o que muda é o
catálogo, não o mecanismo. O registro de capacidades já foi escrito assim: cada
entrada *declara e executa*, e a mesma lista vira o manifesto que a interface
publica para o backend (`local_capability_registry.dart`). No desktop ele
anuncia diagnóstico de rede, inspeção de workspace e execução de script; no
celular ele anunciaria outro conjunto, sem tocar no backend:

- **abrir o app da instituição** no ponto certo — Estácio, e depois o app de
  qualquer instituição que publique um esquema de URL;
- **compartilhar** o resumo, o PDF da aula ou o relatório pelo que já está
  instalado no aparelho;
- **pôr na agenda** do celular a aula, a entrega do trabalho ou a data do quiz;
- **discar ou mandar mensagem** para um contato da coordenação.

Os atalhos já cobrem isso no modelo de dados: `ShortcutModel` guarda `type` =
`app` | `url` | `command` com um `target` livre e apelidos de voz. No celular,
`app` passa a ser um deep link e `command` simplesmente não é anunciado — de
novo, o aparelho declara o que sabe fazer.

> **Limite honesto:** abrir o app da instituição não é integrar com ele. O
> assistente leva o professor até a porta; ele não lê nem lança nada lá dentro.
> A chamada pelo SIA continua vindo do WebView autenticado que já existe, e um
> app de instituição não substitui isso. Além disso, deep link depende de a
> instituição publicar um esquema (no iOS, ainda declarado no
> `LSApplicationQueriesSchemes`): **antes de prometer, é preciso testar aparelho
> a aparelho** — isso não dá para verificar pelo código daqui.

As duas telas maiores (chat e Modo Aula, ~10 mil linhas juntas) foram escritas
para três painéis lado a lado. No celular só o chat, a gravação e as três ações
de sala precisam de versão estreita; o Modo Aula inteiro fica para o tablet,
onde o layout de painéis ainda cabe.

Etapas:

1. **Fatiar o que é local.** Isolar as capacidades de desktop atrás do registro
   de capacidades que já existe, para o app anunciar ao backend só o que aquele
   aparelho sabe fazer — o mecanismo já é esse, falta o app não depender delas.
   Sem isso o chat no celular quebra ao tentar rodar script ou abrir projeto.
2. **Catálogo de capacidades do celular**: abrir app da instituição,
   compartilhar, agenda e contato. Mesma estrutura do registro atual, entradas
   diferentes — e um teste de fumaça por aparelho, porque deep link que não
   existe falha só em produção.
3. **Alvos Android e iOS**, com permissão de microfone, câmera e notificação.
   Áudio sai do `media_kit` com libs do Windows para o caminho nativo do Flutter
   mobile; PDF sai da impressora do sistema para compartilhar arquivo.
4. **Layout estreito** das quatro ações de sala — gravar, pontuar, marcar
   presença e fotografar material — mais chat e lista de conteúdos. A gravação
   precisa dos três tipos (aula, palestra, apresentação), o que inclui escolher
   disciplina e turma da aula: é formulário curto, cabe na tela.
5. **Câmera como entrada de material**: fotografar o quadro e mandar para a
   mesma rota de material. O OCR do backend já trata imagem; falta o caminho da
   câmera e o recorte da foto.
6. **Notificação do sistema** em lugar do aviso só dentro do app — o professor
   não fica com o app aberto esperando a fila de quiz terminar.
7. **Layout de tablet** (breakpoint largo) reaproveitando os painéis do
   desktop: revisão de questões, central de quizzes, relatórios e grupos.
8. **Publicação**: assinatura, conta de desenvolvedor Apple e Google, política
   de privacidade e o texto de consentimento de gravação — as lojas exigem.

*Pronto quando:* o professor dá a aula inteira com o celular no bolso — grava,
pontua quem participou, marca quem faltou e fotografa o quadro — e depois
revisa as questões no tablet antes de aplicar o quiz pelo notebook.

> **Primeiro a Onda 1.** Mais um aparelho com a conta do professor amplia o
> alcance do que hoje está sem autenticação no monitor do quiz.

### Onda 4 — Sair do SIA (4 a 8 semanas)

1. Contrato de adaptador acadêmico, com o SIA como primeira implementação.
2. Credenciais por sistema, cifradas como já são as chaves de IA.
3. Mapeamento de alunos com aprovação manual e auditoria.
4. Um segundo sistema de verdade (Moodle é o mais provável) antes de prometer "multi-sistema".

*Pronto quando:* trocar de instituição é configuração, não desenvolvimento.

### Onda 5 — Escala e inteligência (depois do piloto)

1. **Escalar horizontalmente**: sessão do WebSocket e fila de quiz compartilhadas (Redis), o que hoje limita a uma réplica.
2. **Memória multi-turno com cache**, se a latência do chat virar queixa real.
3. **Validação de alucinação medida**, com conjunto de avaliação e número publicado.
4. **Adaptação por disciplina**, começando por prompt com histórico da disciplina, antes de qualquer treino.

---

## 4. Decisões que dependem de você

1. **Identidade do aluno**: código por turma (simples, anônimo) ou vínculo com o cadastro (permite nota, exige mais cuidado com dado pessoal)?
2. **Os três documentos de "Fase 3"**: viram roadmap de verdade, ou são arquivados como estudo?
3. **Multi-instituição**: vale investir nos adaptadores antes de ter um segundo cliente pedindo?
4. **Escala**: o piloto vai ter quantas turmas simultâneas? Abaixo de uma centena de alunos ao mesmo tempo, a réplica única aguenta e a Onda 5 pode esperar.
5. **Mobile**: Android primeiro (custo baixo, publicação simples) ou Android e iOS juntos (iOS exige conta paga e revisão da Apple)?
6. **Tablet**: entra junto com o celular ou é uma etapa depois? A chamada pelo SIA e o monitor do quiz cabem no tablet em sala, ou o notebook continua sendo o aparelho de sala de aula?

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
| `interface/` (código, sem doc própria) | Só o alvo Windows existe; celular e tablet são a Onda 3 |
