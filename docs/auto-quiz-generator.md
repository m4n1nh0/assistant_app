# Geração Automática de Exercícios e Quiz

## Overview

Feature que gera automaticamente exercícios e questões baseado nos resumos de aula estruturados, permitindo que professores criem avaliações formativas sem esforço manual.

**Status:** Parcialmente aplicado - base do fluxo concluída em 2026-08-25
**Prioridade:** Alta (Modo Educação)  
**Complexidade:** Média

## Status de Implementação

**Aplicado em 2026-08-25:**

- [x] Geração automática de quiz a partir do resumo salvo da aula.
- [x] Geração usa resumo e transcrição disponível como base para o LangGraph.
- [x] Regra de produto: quiz só em aba própria e somente após encerrar a gravação.
- [x] Backend com grafo Generate → Validate → Filter.
- [x] Validação por grounding score e persistência de `grounding_score`.
- [x] Persistência em `quizzes`, `questions` e `student_answers`.
- [x] Perguntas aplicadas ao aluno são objetivas, por escolha de opção.
- [x] Configurações de tipo de quiz, quantidade, dificuldade e LLM respeitadas pela API.
- [x] Compartilhamento por link e QR Code.
- [x] Publicação em duas etapas: preparar perguntas revisáveis e só depois liberar QR Code.
- [x] Monitoramento em tempo real via WebSocket.
- [x] Fluxo ao vivo com pergunta atual controlada pelo professor.
- [x] Pontuação por velocidade e ranking top 10 por rodada.
- [x] Encerramento manual do quiz pelo professor, bloqueando novas respostas.

**Ainda roadmap:**

- [ ] Quiz consolidado de múltiplas aulas/período.
- [ ] Exportação de exercícios para PDF/material impresso.
- [ ] Preview e edição das questões antes de salvar.
- [ ] Relatório completo de desempenho por aluno.
- [ ] Banco de questões reutilizável e regeneração com feedback.

---

## Motivação

Após transcrever, resumir e organizar uma aula, o professor ainda precisa:
1. Criar exercícios manualmente
2. Revisar se cobrem os pontos-chave
3. Variar tipos de questão (múltipla escolha, aberta, verdadeiro/falso)

Com auto-geração de quiz:
- **Tempo:** Reduz de 30-60min para 5min por aula
- **Consistência:** Garante cobertura de todos os tópicos do resumo
- **Variação:** Gera múltiplos formatos de questão automaticamente

---

## Casos de Uso

### 1. Professor gera quiz ao final da aula
```
[Aula gravada] → [Transcrição] → [Resumo estruturado] → [Auto-Quiz]
                                                              ↓
                                                    QR code para alunos
                                                    responderem em tempo real
```

### 2. Quiz para revisão antes da prova
Professor seleciona aulas de um período e gera banco de questões consolidado.

### 3. Exercícios para apostila/material
Exporta questões em formato PDF ou HTML para incluir em materiais impressos.

### 4. Validação de compreensão
Quiz automático detecta lacunas e sugere tópicos para reforço.

---

## Arquitetura Técnica

### Entrada: Resumo Estruturado

```json
{
  "aula_id": "2024-08-20-BD101",
  "titulo": "Normalização de Banco de Dados",
  "duracao_minutos": 120,
  "topicos": [
    {
      "titulo": "Primeira Forma Normal (1NF)",
      "descricao": "Elimina atributos multivalorados...",
      "conceitos_chave": ["atomicidade", "grupos repetidos"],
      "exemplo": "Tabela de alunos com múltiplos telefones"
    },
    {
      "titulo": "Segunda Forma Normal (2NF)",
      "descricao": "Remove dependência parcial...",
      "conceitos_chave": ["chave candidata", "dependência funcional"],
      "exemplo": "Tabela de pedidos com informação de cliente"
    }
  ],
  "pontos_principais": [
    "Normalização reduz anomalias",
    "Trade-off: flexibilidade vs performance",
    "Denormalização é válida em casos específicos"
  ]
}
```

### Processamento: Quiz Generator (LangGraph Agent)

```
┌─────────────────────────────────────┐
│     Quiz Generator Agent            │
│     (LangGraph Multi-Turn)          │
└────────────┬────────────────────────┘
             │
      ┌──────┴──────┬──────────┬──────────┐
      ▼             ▼          ▼          ▼
  ┌────────┐  ┌──────────┐ ┌──────┐ ┌──────────┐
  │ Analisa│  │ Extrai   │ │Gera  │ │Valida   │
  │Resumo  │  │Conceitos │ │Quest.│ │Qualidade│
  │        │  │Chave     │ │      │ │         │
  └────────┘  └──────────┘ └──────┘ └──────────┘
```

### Saída: Quiz Estruturado

```json
{
  "quiz_id": "quiz-2024-08-20-BD101",
  "aula_id": "2024-08-20-BD101",
  "titulo": "Quiz: Normalização de Banco de Dados",
  "questoes": [
    {
      "id": "q1",
      "tipo": "multipla_escolha",
      "dificuldade": "facil",
      "enunciado": "Qual é o objetivo principal da Primeira Forma Normal?",
      "opcoes": [
        {"label": "A", "texto": "Eliminar atributos multivalorados", "correta": true},
        {"label": "B", "texto": "Remover dependência parcial"},
        {"label": "C", "texto": "Eliminar dependência transitiva"},
        {"label": "D", "texto": "Otimizar performance de queries"}
      ],
      "justificativa": "1NF garante que cada atributo contenha apenas valores atômicos.",
      "conceitos": ["atomicidade", "formas normais"],
      "topico_origem": "Primeira Forma Normal (1NF)"
    },
    {
      "id": "q2",
      "tipo": "verdadeiro_falso",
      "dificuldade": "medio",
      "enunciado": "Denormalização é sempre prejudicial para a qualidade de um banco de dados.",
      "resposta_correta": false,
      "justificativa": "Em certos cenários (analytics, cache), denormalização pode ser vantajosa.",
      "conceitos": ["normalização", "denormalização", "trade-offs"],
      "topico_origem": "Pontos Principais"
    },
    {
      "id": "q3",
      "tipo": "aberta",
      "dificuldade": "dificil",
      "enunciado": "Explique a diferença entre dependência funcional e dependência parcial.",
      "resposta_esperada": "Dependência funcional: atributo A determina B. Dependência parcial: parte da chave composta determina um atributo não-chave.",
      "conceitos": ["dependência funcional", "chave candidata", "2NF"],
      "topico_origem": "Segunda Forma Normal (2NF)",
      "rubrica": ["menciona chave", "diferencia parcial de completa", "exemplifica"]
    }
  ],
  "estatisticas": {
    "total_questoes": 3,
    "por_tipo": {"multipla_escolha": 1, "verdadeiro_falso": 1, "aberta": 1},
    "cobertura_topicos": {"1NF": 2, "2NF": 1},
    "distribuicao_dificuldade": {"facil": 1, "medio": 1, "dificil": 1}
  }
}
```

---

## Fluxo de Implementação

### Backend (FastAPI)

**Novo Endpoint:**
```python
POST /api/quiz/generate
{
  "aula_id": "string",
  "tipo_quiz": "revisao | diagnostico | pratica",
  "quantidade_questoes": 10,
  "tipos_questao": ["multipla_escolha", "verdadeiro_falso", "aberta"],
  "dificuldade": "mista | facil | medio | dificil"
}

Response:
{
  "quiz_id": "string",
  "questoes": [...],
  "tempo_estimado_resposta": 15,
  "criado_em": "2024-08-20T10:30:00Z"
}
```

**Service Layer (LangGraph Agent):**
```python
class QuizGeneratorService:
    def __init__(self, llm_service, resumo_repo, qdrant_client):
        self.llm = llm_service
        self.resumo_repo = resumo_repo
        self.vector_db = qdrant_client
    
    async def generate_quiz(self, aula_id, config):
        # 1. Busca resumo estruturado
        resumo = await self.resumo_repo.get_by_aula(aula_id)
        
        # 2. Extrai conceitos-chave via embedding
        conceitos = await self.vector_db.search(
            query=resumo.topicos,
            limit=20
        )
        
        # 3. Usa LangGraph para multi-turn generation
        questoes = await self.langgraph_agent.generate(
            resumo=resumo,
            conceitos=conceitos,
            config=config
        )
        
        # 4. Valida qualidade (sem hallucinations)
        questoes = await self.validate_questoes(questoes)
        
        # 5. Persiste no banco
        return await self.quiz_repo.create(questoes)
```

**Database Schema:**
```sql
CREATE TABLE quizzes (
    id VARCHAR(36) PRIMARY KEY,
    aula_id VARCHAR(36) NOT NULL,
    tutor_id VARCHAR(36) NOT NULL,
    titulo VARCHAR(255),
    tipo_quiz ENUM('revisao', 'diagnostico', 'pratica'),
    total_questoes INT,
    tempo_estimado INT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (aula_id) REFERENCES aulas(id),
    FOREIGN KEY (tutor_id) REFERENCES tutors(id)
);

CREATE TABLE questoes (
    id VARCHAR(36) PRIMARY KEY,
    quiz_id VARCHAR(36) NOT NULL,
    tipo ENUM('multipla_escolha', 'verdadeiro_falso', 'aberta', 'preenchimento'),
    dificuldade ENUM('facil', 'medio', 'dificil'),
    enunciado TEXT,
    opcoes JSON,
    resposta_correta TEXT,
    justificativa TEXT,
    conceitos_relacionados JSON,
    topico_origem VARCHAR(255),
    criado_em TIMESTAMP,
    FOREIGN KEY (quiz_id) REFERENCES quizzes(id)
);

CREATE TABLE respostas_alunos (
    id VARCHAR(36) PRIMARY KEY,
    questao_id VARCHAR(36) NOT NULL,
    aluno_id VARCHAR(36),
    resposta TEXT,
    correta BOOLEAN,
    tempo_resposta INT,
    respondido_em TIMESTAMP,
    FOREIGN KEY (questao_id) REFERENCES questoes(id)
);
```

### Frontend (Flutter)

**UI Components:**
- `QuizGeneratorDialog` - formulário de configuração
- `QuizPreview` - visualização antes de salvar
- `QuizPlayer` - interface de resposta
- `QuizResults` - relatório de desempenho

**Flow:**
```
[Aula Detalhe] → [Botão "Preparar Perguntas"]
                      ↓
              [Formulário de Config]
                      ↓
              [LangGraph + Validação]
                      ↓
              [Salvar Quiz como draft]
                      ↓
              [Liberar QR Code]
                      ↓
              [Compartilhar Link / QR]
```

---

## Estratégia de Validação (Sem Hallucinations)

### 1. Source Validation
```python
async def validate_fonte(questao, resumo):
    # Garante que a questão derivou do resumo
    
    # Técnica 1: Similarity Check
    embedding_questao = embed(questao.enunciado)
    embedding_resumo = embed(resumo.texto)
    
    similaridade = cosine_similarity(embedding_questao, embedding_resumo)
    assert similaridade > 0.6, "Questão sem fonte no resumo"
    
    # Técnica 2: Concept Grounding
    conceitos_questao = extract_concepts(questao)
    conceitos_resumo = extract_concepts(resumo)
    
    assert len(conceitos_questao & conceitos_resumo) > 0, \
        "Questão introduz conceitos novos"
    
    return True
```

### 2. Quality Checks
- ✅ Enunciado tem 10-100 caracteres
- ✅ Múltipla escolha: 3-5 opções, apenas 1 correta
- ✅ Verdadeiro/Falso: resposta inequívoca
- ✅ Aberta: rubrica bem definida
- ✅ Justificativa cite fonte do resumo

### 3. Diversidade
- Não gera 2+ questões idênticas
- Cobertura de todos os tópicos principais
- Distribuição de dificuldade equilibrada

---

## Configurações & Parâmetros

### Tipos de Quiz

| Tipo | Uso | Características |
|------|-----|---|
| **Revisão** | Antes de prova | Cobre 100% tópicos, dificuldade mista |
| **Diagnóstico** | Início de aula | Detecta lacunas, foco em pré-requisitos |
| **Prática** | Durante semana | Reforço, poucos tópicos, variado |

### Dificuldade (Bloom's Taxonomy)

- **Fácil** (Lembrar/Entender): reconhecimento, definição, exemplo
- **Médio** (Aplicar/Analisar): caso prático, compare, diferencie
- **Difícil** (Avaliar/Criar): justifique, proponha, critique

---

## Exemplos de Geração

### Input: Resumo de "Normalização de BD"

### Output: 3 Questões Geradas

**Q1 (Fácil - Múltipla Escolha):**
```
Qual atributo caracterixa dados em Primeira Forma Normal?

A) Valores atômicos (resposta correta)
B) Sem redundância
C) Sem dependência funcional
D) Sem dependência transitiva

Fonte: "Primeira Forma Normal (1NF) elimina atributos multivalorados"
```

**Q2 (Médio - Verdadeiro/Falso):**
```
Uma tabela em 2FN pode ainda conter dependências transitivas.

Resposta: VERDADEIRO
Justificativa: 2FN elimina dependência parcial, mas 3FN elimina 
transitivas. A progressão é: 1FN → 2FN → 3FN.
```

**Q3 (Difícil - Aberta):**
```
Você tem uma tabela de pedidos (id_pedido, id_cliente, nome_cliente, 
data_pedido, id_produto, nome_produto, preco, quantidade).

Cite qual forma normal viola, justifique e proponha decomposição.

Rubrica:
- Identifica 2NF (via dependência parcial de id_cliente)
- Justifica com exemplo (nome_cliente depende só de id_cliente)
- Propõe tabelas: Pedidos, Clientes, Produtos
```

---

## Timeline de Implementação

**Week 1-2:** Backend setup (service, endpoints, DB)  
**Week 3:** LangGraph agent + validação  
**Week 4:** Frontend UI components  
**Week 5:** Testes integrados + refinamento  
**Week 6:** Deploy + feedback

---

## Próximos Passos

1. [ ] Detalhar prompt para LangGraph Agent
2. [ ] Definir métricas de qualidade (aprovação/rejeição)
3. [ ] Criar testes com resumos reais
4. [ ] Documentar API de consumo
5. [ ] Integrar com dashboard de analytics
