# Quiz - Modo Educação

## Status de Implementação

**Aplicado em:** 2026-08-25
**Situação:** fluxo principal implementado.

- [x] Quiz em aba própria do Modo Educação (`6. QUIZ`).
- [x] Geração permitida somente para aula encerrada.
- [x] A aula encerrada pelo botão `ENCERRAR` abre a aba de quiz já selecionada.
- [x] Backend usa `QuizCreateRequest` e respeita tipo, quantidade, dificuldade, tipos de questão e LLM.
- [x] Geração baseada no resumo salvo da aula.
- [x] Link público `/education/quiz/{quiz_id}/play` para alunos.
- [x] Página HTML responsiva para o aluno responder.
- [x] Respostas salvas no banco e comparadas com gabarito quando aplicável.
- [x] Professor pode encerrar o quiz no monitor; o link público passa a bloquear novas respostas.
- [ ] Relatório completo por aluno, exportação em PDF e análise consolidada seguem como roadmap.

---

## 🎯 Visão Geral

Sistema de geração e aplicação automática de quizzes integrado ao Modo Educação, similar ao QR code de presença. Professor cria quiz de uma aula, compartilha link para alunos responderem via HTML responsivo.

---

## 📱 Arquitetura

```
Professor (Flutter Desktop)
    ├─ Abre Modo Educação
    ├─ Seleciona aula com resumo
    ├─ Clica "Gerar Quiz"
    │   └─ Backend: LangGraph (Generate → Validate → Filter)
    ├─ Recebe quiz_id
    └─ Compartilha link: /education/quiz/{quiz_id}/play

Aluno (Browser - Mobile/Desktop)
    ├─ Acessa link compartilhado
    ├─ Responde questões (HTML)
    ├─ Próxima questão após responder
    ├─ Feedback com justificativa
    └─ Conclusão + compartilha resultado
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
  "status": "success"
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

```
POST /education/quiz/generate
Content-Type: application/json
Authorization: Bearer {token}

{
  "lesson_id": "aula-123",
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
└─ created_at

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
- [ ] Notificações de quiz disponível

---

Documentação completa do Quiz no Modo Educação! 🚀
