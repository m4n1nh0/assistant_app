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
- [x] Revisão do rascunho por **agentes especialistas** (Codex e Claude), com veredito por pergunta.

**Ainda roadmap:**

- [x] Quiz consolidado de múltiplas aulas e materiais (as fontes se somam).
- [x] Exportação de exercícios para PDF/material impresso (prova, com gabarito opcional em página separada).
- [x] Revisão antes de liberar o QR Code e edição das questões do rascunho.
- [x] Relatório de desempenho por aluno e por pergunta, com PDF (folha individual por aluno) e planilha.
- [x] Banco de questões reutilizável (buscar, editar, arquivar, montar quiz).
- [ ] Regeneração com feedback do que a turma errou.

---

## Exportar exercícios e relatório de desempenho

**Exercícios em PDF** (ícone de PDF na lista de quizzes e na revisão). O professor
escolhe o que sai no papel:

- **Prova do aluno**: perguntas numeradas, alternativas com círculo para marcar,
  espaço para escrever nas abertas, e campos de nome, turma, data e nota (opcional).
  Cada pergunta cabe inteira numa página, sem partir o enunciado de um lado e as
  alternativas do outro.
- **Gabarito em página separada**, no fim do arquivo (opcional), com aviso de que é
  para o professor. Imprima só as primeiras páginas para a turma. Com
  "justificativas", vira gabarito comentado, com a alternativa correta por extenso.
- Salvar o PDF ou **imprimir** direto pelo diálogo do sistema.

**Relatório de desempenho** (ícone de gráfico na lista e na revisão de quiz liberado
ou encerrado, e "Ver Relatório" no painel ao vivo). `GET /education/quiz/{id}/report`.
Mostra, e exporta em **PDF** e **planilha CSV**, os mesmos números:

- **Por aluno**: posição, pontos, acertos, erros, em branco, % de acerto, tempo médio
  e o que respondeu em cada pergunta. O PDF pode ter **uma folha por aluno**, com o
  que ele marcou, o que era certo e os pontos.
- **Por pergunta**: % de acerto, quantos erraram, quantos ficaram em branco e a
  distribuição das alternativas, com a **mais marcada errada** — que costuma apontar
  o que a aula não passou.
- **Pontos de atenção**: perguntas em que a turma acertou menos da metade (só com 3
  ou mais respostas, para não tirar conclusão de dois alunos), alunos que acertaram
  menos da metade e quem entrou e não respondeu nada.

**Resumo executivo** (aba "Resumo executivo" do relatório e opção no PDF). É a versão
para quem decide sem ter estado na sala — coordenação, direção: **uma página**, só
números agregados, **sem nome de aluno**. Traz o veredito (Bom desempenho a partir de
70% de acerto, Atenção de 50% a 69%, Abaixo do esperado abaixo de 50%), os indicadores
(participação, taxa de acerto, pontos médios, tempo), dois gráficos (alunos por faixa
de acerto e acerto por pergunta), o que os números mostram e o que fazer.

- **O texto sai de regras, não de um modelo de IA.** Texto gerado poderia inventar uma
  conclusão que os números não sustentam, e quem lê o resumo não tem como conferir.
  Exemplos das regras: pergunta com menos da metade de acerto vira "retomar em aula";
  alunos abaixo de 50% viram "oferecer reforço a N alunos"; participação abaixo de
  80% vira "verificar o acesso" (QR Code, rede, tempo curto), porque quem não responde
  é problema de acesso antes de ser de aprendizado.
- **Diz o que não sabe.** Todo resumo termina avisando que é um único quiz, uma
  amostra da aula, e que cada participante é um navegador identificado pelo nome
  digitado, não uma matrícula. Quiz encerrado antes do fim avisa que o resultado cobre
  só as perguntas aplicadas.
- Quem entrou e não respondeu tem faixa própria: não conta como "0% de acerto".

Como as contas são feitas:

- **Só conta pergunta que a turma viu.** Quiz encerrado antes do fim tem perguntas
  que ninguém chegou a ver; contá-las como "sem resposta" derrubaria o percentual de
  todos. Aplicada é a que recebeu ao menos uma resposta ou está no ar.
- **Quem entrou e não respondeu aparece**, com zero. O ranking ao vivo só conhece
  quem respondeu.
- **O aluno é o navegador dele.** Ele digita o nome ao entrar, então dois navegadores
  com o mesmo nome são duas linhas; juntar nomes iguais misturaria pessoas
  diferentes. Por isso o relatório é **por quiz**: cruzar quizzes ou ligar o aluno à
  lista da turma depende de um vínculo que ainda não existe.
- A planilha usa `;`, vírgula decimal e BOM (abre no Excel em português sem
  assistente), traz a linha do gabarito no fim e **protege nomes que começam com
  `=`, `+`, `-` ou `@`**, que a planilha executaria como fórmula — o nome vem de um
  campo livre, digitado por quem escaneou o QR Code.

---

## Variedade e completude das perguntas

Defeito de aula real: pedidas 20 perguntas, vieram 15, parecidas entre si e com a
alternativa correta sempre na A. O que mudou, na ordem do pipeline:

1. **Plano antes das perguntas.** Uma chamada à parte planeja os objetivos —
   conceito, tópico e ângulo (definição, aplicação, comparação, causa e
   consequência, erro, ordem, exemplo) — sem repetir um objetivo no outro. Cada
   lote recebe os objetivos que precisa cobrir e devolve o número do objetivo em
   cada pergunta; o que não rendeu pergunta volta no lote seguinte, e um objetivo
   oferecido duas vezes sem render é abandonado (o conteúdo pode não sustentá-lo).
   Se o plano falha, a geração segue como antes, só com a lista do que já saiu.
2. **Folga para as perdas.** Gera-se `pedido + 25%` (mínimo 2, máximo 8 a mais) e
   corta-se no fim, ficando com as melhores: verificadas primeiro, depois maior
   `grounding_score`. Repetição e reprovação na validação são perdas esperadas;
   sem folga, 20 viravam 15.
3. **Repetição pega a pergunta reescrita.** Além da similaridade de palavras do
   enunciado (agora com plural tratado: "dependências" = "dependência"), duas
   perguntas com **a mesma resposta** e enunciado minimamente parecido contam como
   o mesmo fato. A resposta igual sozinha não basta — "qual forma normal exige a
   2FN?" e "qual elimina dependência transitiva?" têm a mesma resposta e são
   perguntas diferentes.
4. **A correta não fica mais na A.** O exemplo do prompt marcava a A e os modelos o
   copiavam. Agora o exemplo varia e, no código, a posição da correta é
   **equilibrada no quiz inteiro** (20 perguntas, 4 posições, 5 em cada), e as
   letras e o gabarito acompanham. Pergunta que depende da ordem ("todas as
   anteriores", "A e B") não é reordenada.
5. **Alternativas que servem.** Alternativas com o mesmo texto são unificadas, as
   letras ficam sequenciais, e pergunta com menos de 3 alternativas distintas é
   descartada.
6. **O professor sabe por que vieram menos.** Quando vem menos que o pedido, a
   mensagem diz quantas foram repetidas, inválidas ou reprovadas na validação. Se o
   plano achou menos assuntos do que o pedido, diz que o **conteúdo só sustentou N
   assuntos distintos** e sugere marcar mais aulas ou materiais; senão, sugere
   gerar de novo.

Custo: uma chamada a mais (o plano) e cerca de 25% mais geração e validação por
quiz, em troca de entregar o que foi pedido.

---

## Revisão por agentes especialistas (Codex e Claude)

Depois da geração, o professor pode pedir que **Codex e Claude** revisem o
rascunho (`REVISAR COM CODEX + CLAUDE`, na revisão de um quiz em rascunho). Eles
rodam no computador do professor, com a conta que ele já conectou em
Configurações > Agentes — não são provedores do backend, e é por isso que o app
faz a ponte (mesmo desenho do resumo de aula pelos agentes conectados).

```
app ──GET /quiz/{id}/review/prompt──► servidor monta o prompt (aula + perguntas, SEM gabarito)
app ──executa Codex e Claude em paralelo no CLI local──►
app ──POST /quiz/{id}/review/external (um agente por vez)──► servidor lê, compara e decide
```

**O agente não recebe o gabarito.** Ele resolve cada pergunta só com o texto da
aula e responde qual alternativa é a correta; quem compara com a chave gravada é
o servidor. Revisão em que o modelo "aprova" depois de ver a resposta tende a
concordar com o que já está escrito — aqui, dois modelos independentes precisam
chegar à mesma letra que o gerador.

| Veredito | Quando | Efeito em `verificado` |
|---|---|---|
| `aprovada` | todo agente que revisou resolveu com a letra do gabarito, achou a resposta ancorada na aula e não apontou defeito | liga |
| `divergente` | algum agente chegou a **outra** alternativa (ou a nenhuma única) | desliga |
| `revisar` | o gabarito bate, mas o agente apontou defeito ou disse que a aula não sustenta a resposta | desliga |
| `sem_gabarito` | o gerador não deixou uma alternativa correta única | desliga |

- Rodar o Claude depois do Codex **soma** as leituras: o veredito sai de todos os
  agentes que já leram a pergunta. Rodar o mesmo agente de novo substitui a leitura
  dele.
- **O servidor nunca troca o gabarito sozinho.** A divergência fica registrada
  (`questions.revisao_agentes`) e aparece marcada na pergunta, com o que cada
  agente respondeu. Quando o agente propõe uma correção mínima, a sugestão vem com
  o botão `APLICAR SUGESTÃO`, que usa a edição de rascunho que já existia.
- Editar a pergunta descarta a revisão dela (ficou velha) e a marca como revisada
  pelo professor.
- Só vale para **rascunho**: depois de liberado o gabarito não muda (`409`).
- Se nenhum agente estiver instalado e conectado, o app avisa e não chama o
  servidor. Um agente que falha (tempo esgotado, sem login) não derruba o outro.

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
