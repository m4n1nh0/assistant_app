# Agentes Especializados por Disciplina/Linguagem (Auto-Treináveis)

## Overview

Implementação de agentes LLM auto-treináveis especializados por disciplina acadêmica e linguagem de programação, com fine-tuning automático baseado em feedback e desempenho.

**Status:** Roadmap - Fase 3  
**Prioridade:** Alta (Intelligence)  
**Complexidade:** Muito Alta

---

## Motivação

Atualmente INTARQ usa um agente genérico que:
- Não conhece contexto de disciplinas específicas
- Não tem viés para padrões de código do professor
- Aprende lentamente com novos feedback

**Problema:**
- Resumo de BD usa termos genéricos (não menciona chaves estrangeiras)
- Sugestões de código Python usam padrões Java
- Agente não melhora com histórico de aulas

**Solução:**
- Agente **dedicated** por disciplina
- **Auto-treinável** com dados históricos
- **Adaptativo** ao estilo do professor
- **Contexto-aware** de pré-requisitos e progression

---

## Arquitetura

### Agent Taxonomy

```
┌─────────────────────────────────────┐
│    Agente Raiz (Base Agent)         │
│    (Orquestrador Multi-Especialista)│
└────────────────┬────────────────────┘
                 │
    ┌────────────┼────────────┬──────────────┐
    ▼            ▼            ▼              ▼
┌──────────┐ ┌────────┐ ┌─────────┐ ┌─────────────┐
│ BD Agent │ │PY Agent│ │Edu Agent│ │Math Agent   │
│          │ │        │ │         │ │             │
│ Fine-    │ │Fine-   │ │Fine-    │ │Fine-        │
│ tuned:   │ │tuned:  │ │tuned:   │ │tuned:       │
│ 200      │ │150     │ │250      │ │180          │
│ examples │ │examples│ │examples │ │examples     │
└──────────┘ └────────┘ └─────────┘ └─────────────┘
```

### Learning Loop

```
┌──────────────────────────────────────┐
│  Aula gravada + Feedback do Professor│
└────────────┬─────────────────────────┘
             │
             ▼
    ┌────────────────────┐
    │  Extrai Features   │
    │  - Disciplina      │
    │  - Conceitos       │
    │  - Padrões novos   │
    └────────┬───────────┘
             │
             ▼
    ┌────────────────────┐
    │ Agente especializado
    │ existente?         │
    └────┬───────────┬───┘
         │           │
        SIM          NÃO
         │           │
         ▼           ▼
    ┌─────────┐ ┌──────────────┐
    │ Update  │ │ Create novo  │
    │ weights │ │ agente       │
    └──┬──────┘ └──────┬───────┘
       │               │
       └───────┬───────┘
               │
               ▼
        ┌──────────────┐
        │ Validate BLEU│
        │ Evaluate     │
        │ Precision    │
        └──────┬───────┘
               │
               ▼
        ┌──────────────────┐
        │ Depoly se melhora│
        │ > 5% accuracy    │
        └──────────────────┘
```

---

## Componentes Principais

### 1. Agent Factory

```python
class SpecializedAgentFactory:
    """Factory para criar e gerenciar agentes especializados"""
    
    def __init__(self, llm_service, qdrant_client, db):
        self.llm = llm_service
        self.vector_db = qdrant_client
        self.db = db
        self.active_agents: Dict[str, SpecializedAgent] = {}
    
    async def get_or_create_agent(
        self,
        discipline: str,
        language: Optional[str] = None,
        tutor_id: str = None
    ) -> SpecializedAgent:
        """Obtém agente existente ou cria novo"""
        
        agent_key = f"{discipline}:{language or 'general'}:{tutor_id}"
        
        # Verifica cache em memória
        if agent_key in self.active_agents:
            return self.active_agents[agent_key]
        
        # Tenta carregar do banco
        agent_config = await self.db.get_agent_config(agent_key)
        
        if not agent_config:
            # Cria novo agente base
            agent_config = await self.create_base_agent(
                discipline=discipline,
                language=language
            )
        
        # Instancia agente com pesos salvos
        agent = SpecializedAgent(
            discipline=discipline,
            language=language,
            config=agent_config,
            vector_db=self.vector_db,
            llm=self.llm
        )
        
        self.active_agents[agent_key] = agent
        return agent
    
    async def create_base_agent(self, discipline: str, language: str = None):
        """Cria agente base com prompt specializado"""
        
        base_prompt = await self._load_base_prompt(discipline)
        
        # Busca exemplos históricos de sucesso (se houver)
        examples = await self.vector_db.search(
            query=f"Exemplos de sucesso em {discipline}",
            limit=10
        )
        
        return AgentConfig(
            discipline=discipline,
            language=language,
            system_prompt=base_prompt,
            base_examples=examples,
            training_examples=[],
            performance_metrics={},
            created_at=datetime.now()
        )
    
    async def _load_base_prompt(self, discipline: str) -> str:
        """Carrega prompt base specifico da disciplina"""
        prompts = {
            "bd": """Você é especialista em Banco de Dados.
                    Foque em: normalização, chaves estrangeiras, constraints, índices.
                    Cite formalmente: 1NF, 2NF, 3FN, BCNF.
                    Quando apropriado, mencione trade-offs e denormalização.""",
            
            "python": """Você é especialista em Python.
                        Siga PEP 8, use type hints, docstrings.
                        Prefira: list comprehension, generators, context managers.
                        Evite: mutable default arguments, globals.""",
            
            "web": """Você é especialista em desenvolvimento web.
                      Considere: segurança (XSS, SQL injection), performance, acessibilidade.
                      Siga standards: REST, HTTP status codes, semantic HTML.""",
        }
        
        return prompts.get(discipline, "Você é um especialista genérico.")
```

### 2. Specialized Agent

```python
class SpecializedAgent:
    """Agente com contexto de disciplina + aprendizado"""
    
    def __init__(self, discipline: str, config: AgentConfig, vector_db, llm):
        self.discipline = discipline
        self.config = config
        self.vector_db = vector_db
        self.llm = llm
        self.performance = PerformanceTracker()
    
    async def generate_resumo(self, aula_content: str) -> str:
        """Gera resumo com especialização de disciplina"""
        
        # 1. Injeta contexto especializado
        system_prompt = self.config.system_prompt
        
        # 2. Busca exemplos similares no histórico
        similar_aulas = await self.vector_db.search(
            query=aula_content,
            collection=f"exemplos_{self.discipline}",
            limit=3
        )
        
        # Constrói few-shot com exemplos de sucesso
        few_shot = self._build_few_shot_examples(similar_aulas)
        
        # 3. Chama LLM com contexto enriquecido
        prompt = f"""{system_prompt}

Exemplos de resumos bem-sucedidos:
{few_shot}

Agora gere um resumo para:
{aula_content}"""
        
        resumo = await self.llm.generate(prompt)
        
        # 4. Registra para análise futura
        await self.performance.log_generation(
            input=aula_content,
            output=resumo,
            discipline=self.discipline
        )
        
        return resumo
    
    async def suggest_code(self, problem: str) -> str:
        """Sugere código com padrões de linguagem específica"""
        
        system_prompt = self.config.system_prompt
        
        # Busca patterns similares no código do professor
        similar_patterns = await self.vector_db.search(
            query=problem,
            collection=f"code_patterns_{self.config.language}",
            limit=5
        )
        
        few_shot = self._build_code_examples(similar_patterns)
        
        prompt = f"""{system_prompt}

Padrões de código do professor:
{few_shot}

Problema:
{problem}

Gere código seguindo os padrões do professor."""
        
        suggestion = await self.llm.generate(prompt)
        return suggestion
    
    def _build_few_shot_examples(self, examples: List) -> str:
        """Formata exemplos para contexto"""
        formatted = []
        for ex in examples:
            formatted.append(f"Input: {ex['input']}\nOutput: {ex['output']}")
        return "\n---\n".join(formatted)
```

### 3. Auto-Training Pipeline

```python
class AgentAutoTrainer:
    """Treina agentes automaticamente com feedback"""
    
    def __init__(self, agent_factory: SpecializedAgentFactory, db, llm):
        self.factory = agent_factory
        self.db = db
        self.llm = llm
    
    async def process_feedback(
        self,
        agent_key: str,
        feedback: {
            "output": str,
            "rating": 1..5,  # ou "bom" / "ruim"
            "correction": Optional[str],
            "timestamp": datetime
        }
    ):
        """Processa feedback e atualiza agente se necessário"""
        
        agent = await self.factory.get_or_create_agent_by_key(agent_key)
        
        # 1. Salva feedback para análise
        await self.db.save_feedback(agent_key, feedback)
        
        # 2. Se muitos feedbacks negativos recentes
        recent_quality = await self._calculate_recent_quality(agent_key, window=20)
        
        if recent_quality.rating < 3.5:  # Baixo desempenho
            print(f"⚠️  Agente {agent_key} abaixo do esperado. Iniciando re-training...")
            await self.retrain_agent(agent_key)
    
    async def retrain_agent(self, agent_key: str):
        """Re-treina agente com novos dados históricos"""
        
        agent = await self.factory.get_or_create_agent_by_key(agent_key)
        
        # 1. Coleta novos exemplos de sucesso
        successful_outputs = await self.db.get_successful_outputs(
            agent_key=agent_key,
            min_rating=4,
            limit=50
        )
        
        # 2. Extrai features comuns
        features = await self._extract_features(successful_outputs)
        
        # 3. Atualiza sistema prompt
        new_prompt = await self._generate_improved_prompt(
            current_prompt=agent.config.system_prompt,
            features=features,
            successful_examples=successful_outputs
        )
        
        # 4. Testa com validação set
        validation_set = await self.db.get_validation_set(agent_key, size=10)
        
        # Compara: novo prompt vs prompt antigo
        old_quality = await self._evaluate_prompt(agent, agent.config.system_prompt, validation_set)
        new_quality = await self._evaluate_prompt(agent, new_prompt, validation_set)
        
        improvement = (new_quality - old_quality) / old_quality
        
        print(f"Improvement: {improvement:.2%}")
        
        # 5. Deploy se melhora > threshold
        if improvement > 0.05:  # 5% melhoria
            print(f"✅ Deploying improved prompt")
            agent.config.system_prompt = new_prompt
            agent.config.training_examples = successful_outputs
            await self.db.save_agent_config(agent_key, agent.config)
        else:
            print(f"❌ Improvement too small. Keeping current version")
    
    async def _generate_improved_prompt(
        self,
        current_prompt: str,
        features: Dict,
        successful_examples: List
    ) -> str:
        """USA LLM para gerar prompt melhorado"""
        
        analysis_prompt = f"""Analise os outputs bem-sucedidos e gere um system prompt aprimorado.

Prompt atual:
{current_prompt}

Features comuns nos outputs bem-sucedidos:
{json.dumps(features, indent=2)}

Exemplos de sucesso (top 3):
{json.dumps([ex[:200] for ex in successful_examples[:3]], indent=2)}

Gere um novo system prompt que capture essas características e melhore a qualidade."""
        
        improved = await self.llm.generate(analysis_prompt)
        return improved
    
    async def _evaluate_prompt(self, agent, prompt: str, validation_set: List) -> float:
        """Avalia qualidade de um prompt usando BLEU/ROUGE"""
        
        scores = []
        for item in validation_set:
            # Gera saída com novo prompt
            output = await agent.llm.generate(
                system_prompt=prompt,
                user_input=item["input"]
            )
            
            # Compara com output esperado (feedback do professor)
            score = self._calculate_similarity(output, item["expected_output"])
            scores.append(score)
        
        return sum(scores) / len(scores)
```

### 4. Database Schema

```sql
CREATE TABLE specialized_agents (
    id VARCHAR(36) PRIMARY KEY,
    tutor_id VARCHAR(36) NOT NULL,
    discipline VARCHAR(100),
    programming_language VARCHAR(50),
    system_prompt TEXT,
    base_examples JSON,
    training_examples JSON,
    created_at TIMESTAMP,
    last_trained_at TIMESTAMP,
    accuracy_score FLOAT,
    version INT DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE KEY uq_agent (tutor_id, discipline, programming_language)
);

CREATE TABLE agent_feedback (
    id VARCHAR(36) PRIMARY KEY,
    agent_id VARCHAR(36) NOT NULL,
    input_content TEXT,
    output_content TEXT,
    rating INT (1-5),
    correction TEXT,
    created_at TIMESTAMP,
    quality_metrics JSON,
    FOREIGN KEY (agent_id) REFERENCES specialized_agents(id)
);

CREATE TABLE agent_performance_metrics (
    id VARCHAR(36) PRIMARY KEY,
    agent_id VARCHAR(36) NOT NULL,
    metric_name VARCHAR(100),
    metric_value FLOAT,
    measured_at TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES specialized_agents(id)
);
```

---

## Métricas de Desempenho

```python
class PerformanceTracker:
    """Rastreia performance de agentes"""
    
    def __init__(self):
        self.bleu_score = 0.0      # Similaridade com referência
        self.rouge_score = 0.0     # Recall-oriented
        self.user_rating = 0.0     # Feedback direto (1-5)
        self.accuracy = 0.0        # Acurácia em tarefas
        self.coherence = 0.0       # Coesão do texto
    
    async def evaluate_generation(self, generated: str, reference: str):
        """Avalia qualidade de geração"""
        self.bleu_score = calculate_bleu(generated, reference)
        self.rouge_score = calculate_rouge(generated, reference)
        # ... outros scores
```

---

## Exemplos Práticos

### Cenário 1: Agente BD

```
Professor ensina normalização por 4 semestres.
Agente acumula 200 exemplos de resumos bem-sucedidos.

Treino automático detecta padrões:
✅ Sempre menciona "First/Second/Third Normal Form"
✅ Cita exemplos com chaves estrangeiras
✅ Avisa sobre denormalização e quando fazer

Sistema prompt evolui automaticamente.
Accuracy: 68% → 82% em 4 semestres
```

### Cenário 2: Agente Python

```
Professor usa:
- Type hints (100% dos exemplos)
- List comprehensions (80% dos exemplos)
- Context managers (70%)

Agente aprende padrões.
Quando sugere código, já começa com:
def função(param: type) -> ReturnType:
```

---

## Testing & Validation

- [ ] Unit tests: Prompt generation, feature extraction
- [ ] Integration: Agent training pipeline end-to-end
- [ ] A/B testing: Nova vs antiga versão de agente
- [ ] Correctness: Feedback sempre melhora ou mantém qualidade

---

## Timeline

**Week 1:** Agent factory + base prompts  
**Week 2:** Auto-training pipeline + feedback loop  
**Week 3:** Evaluation metrics + A/B testing framework  
**Week 4:** Deployment + monitoring  
**Week 5:** Fine-tuning por disciplina (BD, Python, Web)
