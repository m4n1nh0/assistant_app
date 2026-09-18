# Quiz - Modo Educação

## Status de Implementação

**Aplicado em:** 2026-08-25
**Situação:** fluxo principal implementado.

- [x] Quiz em aba própria do Modo Educação (`6. QUIZ`).
- [x] Geração permitida somente para aula encerrada.
- [x] A aula encerrada pelo botão `ENCERRAR` abre a aba de quiz já selecionada.
- [x] Backend usa `QuizCreateRequest` e respeita tipo, quantidade, dificuldade, tipos de questão e LLM.
- [x] Geração baseada no resumo salvo e, quando disponível, na transcrição da aula.
- [x] Quiz nasce como `draft`; QR Code/link só são liberados depois da publicação pelo professor.
- [x] Link público `/education/quiz/{quiz_id}/play` para alunos.
- [x] Página HTML responsiva para aluno entrar pelo nome e responder a pergunta atual.
- [x] Perguntas objetivas por escolha de opção, com pontuação por velocidade.
- [x] Professor controla pergunta atual, encerramento da rodada e próxima pergunta.
- [x] Ranking top 10 exibido ao professor após encerrar cada pergunta.
- [x] Aluno vê ranking da rodada e sua própria colocação.
- [x] Respostas salvas no banco com acerto, tempo e pontuação.
- [x] Professor pode encerrar o quiz no monitor; o link público passa a bloquear novas respostas.
- [ ] Relatório completo por aluno, exportação em PDF e análise consolidada seguem como roadmap.

---

## 🎯 Visão Geral

Sistema de geração e aplicação automática de quizzes integrado ao Modo Educação, similar ao QR code de presença. Professor cria quiz de uma aula, compartilha link e controla o avanço das perguntas em tempo real.

---

## 📱 Arquitetura

```
Professor (Flutter Desktop)
    ├─ Abre Modo Educação
    ├─ Seleciona aula com resumo
    ├─ Clica "Preparar Perguntas"
    │   └─ Backend: LangGraph (Generate → Validate → Filter)
    ├─ Confere as perguntas preparadas
    ├─ Clica "Liberar QR Code"
    └─ Compartilha link: /education/quiz/{quiz_id}/play

Aluno (Browser - Mobile/Desktop)
    ├─ Acessa link compartilhado
    ├─ Informa o nome
    ├─ Aguarda professor iniciar a pergunta
    ├─ Escolhe uma opção objetiva
    ├─ Recebe pontuação por velocidade
    └─ Vê ranking da rodada e sua colocação
```

---

## 🚀 Como Usar

### 1. Gerar Quiz (Backend)

```bash
curl -X POST http://localhost:8000/education/quiz/generate \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d {
    "lesson_id": "aula-123",
    "tipo_quiz": "pratica",
    "quantidade_questoes": 10,
    "dificuldade": "mista"
  }

# Resposta
{
  "quiz_id": "quiz-abc123",
  "titulo": "Quiz: Normalização de BD",
  "questoes": [...],
  "status": "draft"
}
```

### 2. Compartilhar com Alunos

Professor copia o link e compartilha:

```
http://localhost:8000/education/quiz/quiz-abc123/play
```

ou

```
http://seu-dominio.com/education/quiz/quiz-abc123/play?lang=pt
```

### 3. Aluno Responde

1. Abre link no browser (mobile-friendly)
2. Vê questão com progresso (1/10)
3. Seleciona resposta (múltipla, V/F ou aberta)
4. Clica "CONFIRMAR RESPOSTA"
5. Sistema valida e exibe próxima
6. Ao final, mostra "Quiz Completado! 🎉"

---

## 🎨 Interface Web

### Características

- **Responsivo**: Funciona em mobile, tablet, desktop
- **Gradiente**: Purple/violet (matching Modo Educação)
- **Seletor de idioma**: PT, ES, EN
- **Tipos de questão**:
  - Múltipla escolha (4 opções)
  - Verdadeiro/Falso
  - Aberta (textarea)
- **Feedback**: Imediato após responder
- **Progresso**: Barra visual + contador

### Fluxo Visual

```
┌─────────────────────────────────┐
│  MODO EDUCAÇÃO                  │
│  Questão 1 de 10                │
│  [▓▓░░░░░░] (10% completo)      │
├─────────────────────────────────┤
│                                 │
│  Qual é a primeira forma        │
│  normal em banco de dados?      │
│                                 │
│  ○ Eliminar multivalorados      │
│  ○ Remover dependência parcial  │
│  ○ Eliminar dependência trans.  │
│  ○ Otimizar performance         │
│                                 │
├─────────────────────────────────┤
│  [PULAR]  [CONFIRMAR RESPOSTA]  │
├─────────────────────────────────┤
│  Respostas serão registradas    │
│  e comparadas com o gabarito.   │
└─────────────────────────────────┘
```

---

## 📊 Endpoints

### Gerar Quiz (Autenticado)

As fontes se somam, em qualquer combinação: uma aula, três aulas, duas aulas
com a apostila. `lesson_id` e `material_id` (singulares) continuam valendo como
atalho de fonte única e entram junto com as listas.

A aula **não precisa estar encerrada** — o que decide se ela entra é ter texto,
seja o resumo validado ou a transcrição já gravada, o que permite o quiz
relâmpago no meio da aula. Fonte marcada que está sem texto é ignorada e
aparece nomeada no `message` da resposta; se nenhuma tem texto, a resposta é
400. O contexto de todas as fontes soma no máximo 60 mil caracteres, dividido
entre elas, porque a janela do modelo não cresce com o número de fontes.

Cada fonte que entrou vira uma linha em `quiz_sources`, então dá para rastrear
de onde cada pergunta saiu.

```
POST /education/quiz/generate
Content-Type: application/json
Authorization: Bearer {token}

{
  "lesson_ids": ["aula-123", "aula-124"],
  "material_ids": ["mat-1"],
  "tipo_quiz": "pratica|revisao|diagnostico",
  "quantidade_questoes": 10,
  "tipos_questao": ["multipla_escolha", "verdadeiro_falso", "aberta"],
  "dificuldade": "mista|facil|medio|dificil",
  "llm": "claude|auto"
}

Response:
{
  "quiz_id": "quiz-abc123",
  "titulo": "Quiz: Tema",
  "questoes": [
    {
      "id": "q1",
      "tipo": "multipla_escolha",
      "enunciado": "...",
      "opcoes": [...],
      "resposta_correta": "A",
      "justificativa": "...",
      "grounding_score": 0.92
    }
  ],
  "status": "success"
}
```

### Fila de Geração (Autenticado)

Gerar um quiz leva minutos, então a tela não espera: o pedido entra numa **fila
persistente** (`quiz_jobs`) e o professor segue usando o app. A central de
quizzes acompanha o andamento, e o aviso chega no fim — dentro do app, com botão
para revisar, e pelos canais externos configurados (Telegram/WhatsApp).

Regras da fila:

- **uma geração por professor por vez**; os pedidos seguintes esperam na ordem.
  Professores diferentes não esperam um pelo outro;
- **sobrevive a deploy e reinício**: o que estava gerando volta para a fila na
  subida e é gerado de novo;
- a fonte é validada na hora do pedido: aula inexistente ou sem texto responde
  `404`/`400` imediato, e não um pedido que falha minutos depois;
- as questões já geradas **das mesmas fontes** vão para a IA como "já geradas",
  para o segundo quiz da mesma aula não repetir o primeiro.

Estados de um pedido:

```
queued (na fila) → running (gerando) → done (pronto) | error (com erro)
queued | running → canceled (cancelado)
error | canceled → [tentar de novo] → novo pedido queued
```

```
POST /education/quiz/generate/async      (mesmo corpo de /education/quiz/generate)

Response 202:
{
  "job_id": "…",
  "status": "queued",
  "titulo": "Quiz: Tema",
  "total": 10,
  "prontas": 0,
  "position": 2,
  "message": "Na fila: 1 pedido(s) antes deste.",
  "quiz_id": null,
  "can_cancel": true, "can_retry": false, "can_review": false
}
```

| Rota | O que faz |
|---|---|
| `GET /education/quiz/jobs` | Pedidos do professor (ativos primeiro), com `active` e `unseen` |
| `GET /education/quiz/jobs/{job_id}` | Um pedido; pronto, traz o quiz em `quiz` para revisão |
| `POST /education/quiz/jobs/{job_id}/cancel` | Cancela na fila ou em andamento |
| `POST /education/quiz/jobs/{job_id}/retry` | Enfileira de novo o mesmo pedido (só `error` ou `canceled`) |
| `POST /education/quiz/jobs/seen` | `{"job_ids": [...]}` — marca avisos de fim como vistos |

### Quizzes e Banco de Questões (Autenticado)

Estados de um quiz: `draft` (rascunho, em revisão) → `open` (liberado pelo QR
Code) → `closed` (encerrado). Só rascunho é editado ou descartado: quiz liberado
já tem resposta de aluno apontando para as questões.

| Rota | O que faz |
|---|---|
| `GET /education/quiz?status=&discipline=&lesson_id=&q=` | Quizzes com disciplinas (vindas das fontes) e contagem de questões |
| `DELETE /education/quiz/{quiz_id}` | Descarta rascunho (`409` se já liberado) |
| `GET /education/quiz/questions?discipline=&lesson_id=&q=&dificuldade=&include_archived=&limit=&offset=` | Banco de questões com filtro e paginação |
| `PATCH /education/quiz/questions/{id}` | Corrige questão de rascunho; com `opcoes`, exatamente uma correta |
| `DELETE /education/quiz/questions/{id}` | Apaga (rascunho) ou **arquiva** (quiz liberado): some do banco e das próximas gerações, mas continua ligada às respostas |
| `POST /education/quiz/questions/{id}/restore` | Devolve ao banco uma questão arquivada |
| `POST /education/quiz/from-questions` | `{"titulo", "question_ids", "tipo_quiz"}` — novo rascunho com cópias das questões, na ordem escolhida, sem chamar a IA |

Na interface, tudo isso fica na aba **Quiz** do Modo Aula, em quatro sub-abas:
**Gerar** (pedido), **Fila** (andamento, cancelar, tentar de novo, revisar),
**Quizzes** (revisar, liberar QR Code, descartar rascunho) e **Banco de
questões** (buscar, editar, arquivar, montar quiz).

### Responder Quiz (Público)

```
GET /education/quiz/{quiz_id}/play?lang=pt
→ Retorna HTML da primeira questão

POST /education/quiz/{quiz_id}/play?lang=pt
Content-Type: application/x-www-form-urlencoded

answer=A

→ Valida resposta, salva no DB, exibe próxima questão
```

### Recuperar Quiz (Autenticado)

```
GET /education/quiz/{quiz_id}
Authorization: Bearer {token}

Response:
{
  "id": "quiz-abc123",
  "lesson_id": "aula-123",
  "titulo": "Quiz: Normalização",
  "tipo_quiz": "pratica",
  "total_questoes": 10,
  "questoes": [...]
}
```

---

## 🔐 Segurança

### Autenticação

- **Geração**: Requer token (professor autenticado)
- **Resposta**: Pública (pode ser compartilhado)
- **Recuperação**: Requer token (apenas professor)

### Proteção

- Rate limiting no check-in (120 req/min)
- Respostas anônimas (student_id = None)
- Validação de entrada
- Sanitização de HTML

---

## 💾 Banco de Dados

### Tabelas

```sql
quizzes
├─ id (PK)
├─ tutor_id (FK)
├─ lesson_id (FK)
├─ titulo
├─ tipo_quiz
├─ total_questoes
├─ tempo_estimado
└─ created_at

questions
├─ id (PK)
├─ quiz_id (FK)
├─ tipo
├─ dificuldade
├─ enunciado
├─ opcoes (JSON)
├─ resposta_correta
├─ justificativa
├─ grounding_score
├─ verificado
├─ arquivada (fora do banco de questões, mantida para as respostas)
└─ created_at

quiz_jobs (fila de geração)
├─ id (PK)
├─ tutor_id / user_id
├─ titulo
├─ status (queued | running | done | error | canceled)
├─ total / prontas
├─ request_json (pedido completo, para gerar e tentar de novo)
├─ quiz_id (quando pronto)
├─ message / error / attempts_json
├─ created_at / started_at / finished_at
└─ seen_at (aviso de fim visto)

student_answers
├─ id (PK)
├─ question_id (FK)
├─ student_id (NULL = anônimo)
├─ resposta
├─ correta
├─ tempo_resposta
└─ respondido_em
```

---

## 🧪 Testes

### Teste 1: Gerar Quiz

```bash
# 1. Gera quiz
curl -X POST http://localhost:8000/education/quiz/generate \
  -H "Authorization: Bearer eyJ..." \
  -d {"lesson_id": "aula-123"}

# 2. Copia quiz_id
quiz_id="quiz-abc123"

# 3. Acessa no browser
open "http://localhost:8000/education/quiz/$quiz_id/play"
```

### Teste 2: Responder Questão

```bash
# 1. Acessa página do quiz
curl "http://localhost:8000/education/quiz/quiz-abc123/play"

# 2. Extrai HTML, preenche form
# 3. Submete resposta
curl -X POST "http://localhost:8000/education/quiz/quiz-abc123/play" \
  -d "answer=A"

# 4. Próxima questão aparece
```

### Teste 3: Validação

```bash
# Verifica se grounding_score > 0.70
curl "http://localhost:8000/education/quiz/quiz-abc123" \
  -H "Authorization: Bearer eyJ..." \
  | jq '.questoes[].grounding_score'
```

---

## ⚙️ Configuração

### Variáveis de Ambiente

```bash
# Backend
QUIZ_TIMEOUT=30              # Segundos por questão
QUIZ_MAX_QUESTIONS=50        # Máximo permitido
GROUNDING_THRESHOLD=0.70     # Score mínimo para aceitar questão
```

### Tipos de Questão Suportados

| Tipo | Descrição | Validação | Exemplo |
|------|-----------|-----------|---------|
| multipla_escolha | 4 opções | Comparação exata | A, B, C, D |
| verdadeiro_falso | V ou F | Normalizado | verdadeiro/v/sim → true |
| aberta | Texto livre | Sem validação | Qualquer texto |

---

## 🐛 Troubleshooting

### "Quiz não encontrado"

**Causa**: quiz_id inválido ou expirado

**Solução**: 
- Verifique quiz_id está correto
- Verifique que quiz foi criado com sucesso
- Tente gerar novo quiz

### Validação bloqueia questões

**Causa**: grounding_score < 0.70

**Solução**:
- Resumo muito diferente do gerado
- Use Claude em vez de Llama (mais preciso)
- Reduza quantidade de questões (mais qualidade)
- Em dev: abaixe GROUNDING_THRESHOLD

### Interface não carrega

**Causa**: Recurso bloqueado, charset errado

**Solução**:
- Limpe cache do navegador
- Tente em navegador privado
- Verifique headers de cache-control

---

## 📚 Fluxo Completo - Step by Step

```
1. Professor acessa Modo Educação
   ├─ Seleciona disciplina
   └─ Seleciona aula

2. Vê resumo gerado anteriormente
   ├─ Se resumo OK...
   └─ Clica botão "Gerar Quiz"

3. Backend executa:
   ├─ Prompta LLM: generate_summary_prompt
   ├─ LLM retorna questões
   ├─ Valida hallucinations
   ├─ Calcula grounding_score
   ├─ Filtra score < 0.70
   └─ Salva no DB

4. Professor recebe:
   ├─ Quiz ID
   ├─ Botão "Copiar Link"
   └─ Preview das questões

5. Professor compartilha link:
   http://seu-dominio/education/quiz/{quiz_id}/play

6. Aluno clica link:
   ├─ Abre no navegador (mobile OK)
   ├─ Vê primeira questão
   └─ Seleciona resposta

7. Aluno clica "CONFIRMAR":
   ├─ POST /education/quiz/{quiz_id}/play
   ├─ Backend valida resposta
   ├─ Salva em student_answers
   ├─ Exibe próxima questão
   └─ Progresso atualiza

8. Ao final (última questão):
   ├─ Aluno submete última resposta
   ├─ Backend salva
   ├─ Exibe tela de conclusão
   └─ 🎉 Quiz Completado!

9. Professor acessa quiz:
   GET /education/quiz/{quiz_id}
   ├─ Vê todas as respostas
   ├─ Calcula estatísticas
   └─ Pode revisar questões
```

---

## 🎯 Próximas Features

- [ ] Análise de respostas por aluno
- [ ] Exportar resultados em PDF
- [ ] Comparação com gabarito
- [ ] Relatório de desempenho
- [ ] Remixagem de questões (embaralhar opções)
- [ ] Integração com calendário
- [x] Aviso ao professor quando a geração termina

---

Documentação completa do Quiz no Modo Educação! 🚀
