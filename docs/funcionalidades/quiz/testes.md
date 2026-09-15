# Guia de Teste - Geração e Reprodução de Quiz

## 🚀 Início Rápido

### 1. Acessar o Dashboard de Quiz

```bash
# Em desenvolvimento local
http://localhost:8000/quiz/dashboard
```

### 2. Fluxo de Teste

#### Opção A: Via Interface Web (Recomendado)

1. Abra o dashboard em `http://localhost:8000/quiz/dashboard`
2. Selecione uma aula (com resumo)
3. Configure:
   - **Tipo de Quiz**: Prática / Revisão / Diagnóstico
   - **Número de Questões**: 5-50
   - **Dificuldade**: Fácil / Médio / Difícil / Mista
4. Clique "Gerar Quiz com IA"
5. Aguarde a geração (~10-30s dependendo do LLM)
6. Serão redirecionado para o Player
7. Responda as questões

#### Opção B: Via API REST (Para testes programáticos)

```bash
# Gerar quiz
curl -X POST http://localhost:8000/education/quiz/generate \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d {
    "lesson_id": "aula-123",
    "tipo_quiz": "pratica",
    "quantidade_questoes": 10,
    "tipos_questao": ["multipla_escolha", "verdadeiro_falso", "aberta"],
    "dificuldade": "mista",
    "llm": "claude"
  }

# Resposta:
{
  "quiz_id": "quiz-abc123",
  "titulo": "Quiz: Normalização de Banco de Dados",
  "questoes": [
    {
      "id": "q1",
      "tipo": "multipla_escolha",
      "dificuldade": "medio",
      "enunciado": "Qual é o objetivo principal da 1NF?",
      "opcoes": [
        {"label": "A", "texto": "Eliminar atributos multivalorados", "correta": true},
        {"label": "B", "texto": "Remover dependência parcial", "correta": false},
        {"label": "C", "texto": "Eliminar dependência transitiva", "correta": false},
        {"label": "D", "texto": "Otimizar performance", "correta": false}
      ],
      "resposta_correta": "A",
      "justificativa": "1NF garante que cada atributo contenha apenas valores atômicos...",
      "grounding_score": 0.92,
      "verificado": true
    }
  ],
  "tempo_estimado_resposta": 15,
  "status": "success"
}

# Recuperar quiz existente
curl -X GET http://localhost:8000/education/quiz/quiz-abc123 \
  -H "Authorization: Bearer YOUR_TOKEN"

# Registrar resposta
curl -X POST http://localhost:8000/education/quiz/quiz-abc123/answer \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d {
    "question_id": "q1",
    "resposta": "A",
    "tempo_resposta": 45
  }
```

---

## 🎮 Testando o Player (Kahoot-like)

### Interface

O player web oferece:

- **✨ Tema Moderno**: Interface gradiente purple/violet
- **⏱️ Timer**: Contador regressivo (30s por padrão)
- **📊 Progresso**: Barra de progresso visual
- **❓ Tipos de Questão**:
  - Múltipla escolha (4 opções)
  - Verdadeiro/Falso
  - Aberta (texto livre)
- **📈 Resultados**: Placar final com estatísticas
  - Total de acertos
  - Total de erros
  - Questões puladas

### Fluxo de Teste Completo

```
[Dashboard]
    ↓
[Selecionar Aula]
    ↓
[Configurar Quiz]
    ↓
[Gerar com IA] ← Valida hallucinations, grounding score
    ↓
[Player - Questão 1]
    ├─ Exibe questão
    ├─ Mostra opções
    ├─ Timer começaa
    ├─ Usuário responde
    └─ Feedback com justificativa
    ↓
[Próximas Questões]
    ↓
[Resultados Finais]
    ├─ Placar: X/Y acertos
    ├─ Tempo total
    ├─ Dificuldade média
    └─ Opção de refazer
```

---

## 🧪 Casos de Teste

### Teste 1: Geração com Validação

**Objetivo**: Garantir que questões são derivadas do resumo

**Passos**:
1. Crie um quiz de uma aula com resumo pequeno
2. Verifique que todas as questões mencionam conceitos do resumo
3. Verifique `grounding_score > 0.70` em todas

**Esperado**:
- ✅ Todas as questões bem formuladas
- ✅ Sem hallucinations detectáveis
- ✅ Justificativas citam o resumo

---

### Teste 2: Tipos de Questão Variados

**Objetivo**: Verificar suporte a diferentes tipos

**Passos**:
1. Gere quiz com `tipos_questao: ["multipla_escolha", "verdadeiro_falso", "aberta"]`
2. Responda uma de cada tipo

**Esperado**:
- ✅ Múltipla escolha: valida resposta correta
- ✅ V/F: normaliza entrada (verdadeiro/v/sim → true)
- ✅ Aberta: registra resposta sem validar automaticamente

---

### Teste 3: Fallback de LLM

**Objetivo**: Garantir fallback automático se Claude falhar

**Passos**:
1. Desabilite Claude (ou remova API key)
2. Gere quiz com `llm: "auto"`
3. Verifique logs: deve cair para próximo LLM disponível

**Esperado**:
- ✅ Quiz gerado com sucesso com LLM alternativo
- ✅ `attempts` array mostra fallback realizado

---

### Teste 4: Performance com Muitas Questões

**Objetivo**: Testar escalabilidade

**Passos**:
1. Gere quiz com `quantidade_questoes: 50`
2. Meça tempo de geração
3. Responda 20+ questões

**Esperado**:
- ✅ Geração < 2 minutos
- ✅ Interface responsiva
- ✅ Sem erros de memória

---

## 📊 Exemplos de Dados para Teste

### Dataset Pequeno (Teste Rápido)

```json
{
  "lesson_id": "test-bd-101",
  "titulo_aula": "Introdução a Banco de Dados",
  "resumo": "Discutimos o conceito de banco de dados relacional. Uma relação é uma tabela com linhas e colunas. Chaves primárias identificam registros únicos. Chaves estrangeiras conectam tabelas. A normalização reduz redundância.",
  "disciplina": "Banco de Dados"
}
```

**Questões Esperadas**:
- O que é uma relação em banco de dados?
- Qual é a função de uma chave primária?
- Verdadeiro/Falso: Chaves estrangeiras conectam tabelas

---

## 🔍 Checklist de Validação

### Antes do Deploy

- [ ] Quiz gerado com sucesso via API
- [ ] Questões validadas contra hallucinations
- [ ] Player responde e calcula resultado correto
- [ ] Timer funciona corretamente
- [ ] Feedback mostra justificativas
- [ ] Placar final exibe estatísticas
- [ ] Fallback de LLM funciona
- [ ] Diferentes tipos de questão funcionam
- [ ] Interface responsiva (mobile/desktop)
- [ ] Sem erros no console do navegador

### Performance

- [ ] Geração < 30s (Claude), < 60s (outros LLM)
- [ ] Player carrega em < 2s
- [ ] Banco de dados persiste quiz corretamente
- [ ] Respostas salvas no DB

---

## 🐛 Troubleshooting

### "Quiz ID não fornecido"

**Problema**: Player abre mas mostra erro

**Solução**: Verifique URL tem `?quiz_id=ABC123`

---

### "Falha ao carregar quiz"

**Problema**: API retorna 404

**Solução**: 
- Verifique quiz_id existe no banco
- Verifique token de autenticação

---

### LLM lento ou timeout

**Problema**: Geração demora > 1 minuto

**Solução**:
- Reduza `quantidade_questoes`
- Use Claude (mais rápido) em vez de Llama
- Verifique conexão de rede

---

### Validação bloqueia todas as questões

**Problema**: `grounding_score < 0.70` para todas

**Solução**:
- Resumo pode ser muito diferente do gerado
- Reduza threshold de validação (dev only)
- Regenere quiz

---

## 📚 Recursos Adicionais

- Documento de arquitetura: [docs/auto-quiz-generator.md](./auto-quiz-generator.md)
- Esquema de banco de dados: [models de Quiz](../backend/app/core/database.py)
- Serviço de geração: [quiz_generator_service.py](../backend/app/services/quiz_generator_service.py)

---

## 🎯 Métricas de Sucesso

| Métrica | Alvo | Status |
|---------|------|--------|
| Geração de quiz | < 30s | ✅ |
| Validação de hallucination | > 90% acurácia | ⏳ |
| Grounding score médio | > 0.75 | ⏳ |
| Tempo por questão no player | < 1s resposta | ⏳ |
| Taxa de conclusão de quiz | > 95% | ⏳ |

---

## 🔄 Fluxo de Integração Contínua

```bash
# 1. Rodar testes unitários
pytest backend/tests/test_quiz_generator.py

# 2. Testar API
python -m pytest backend/tests/test_quiz_endpoints.py

# 3. Testar interface web (Selenium)
pytest backend/tests/test_quiz_ui.py
```

---

Pronto para testar! 🚀
