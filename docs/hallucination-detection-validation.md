# Detecção de Hallucinations com Validação de Fonte

## Overview

Sistema robusto de detecção e prevenção de hallucinations em resumos de aula, garantindo que todas as afirmações derivem de transcriptions originais.

**Status:** Roadmap - Fase 3  
**Prioridade:** Crítica (Quality Assurance)  
**Complexidade:** Muito Alta

---

## Motivação

Hallucinations em resumos de aula são críticas:
- ❌ Professor diz "Banco de Dados", LLM escreve "Data Warehouse"
- ❌ Exemplo de código é inventado, não menciona na aula
- ❌ Datas/números errados inserem erros no histórico

**Risco:** Professores perdem confiança na ferramenta

**Solução:** Multi-layer validation pipeline que detecta e bloqueia hallucinations antes de salvar.

---

## Arquitetura

### Validation Pipeline

```
┌──────────────────────────────────┐
│  Resumo Gerado pelo LLM          │
└────────────────┬─────────────────┘
                 │
      ┌──────────┴──────────┐
      ▼                     ▼
┌──────────────┐      ┌──────────────┐
│ Extract Facts│      │Extract Claims│
│ & Entities   │      │              │
└──────┬───────┘      └──────┬───────┘
       │                     │
       └──────────┬──────────┘
                  │
    ┌─────────────┴─────────────┐
    ▼                           ▼
┌──────────────────┐  ┌─────────────────┐
│ Source Grounding │  │ Fact Verification│
│ (Transcript)     │  │ (Knowledge Base) │
└──────┬───────────┘  └────────┬────────┘
       │                       │
       └──────────┬────────────┘
                  │
    ┌─────────────┴──────────────┐
    ▼                            ▼
┌─────────────────┐  ┌───────────────────┐
│ Hallucination?  │  │ Confidence Score  │
│                 │  │ < threshold?      │
└────┬────────────┘  └─────┬─────────────┘
     │                     │
   Bloqueia           Marca para revisão
   ou sinaliza        manual
```

---

## Componentes

### 1. Fact Extraction

```python
from pydantic import BaseModel
from typing import List

class FactExtraction:
    """Extrai fatos e entidades de texto"""
    
    def __init__(self, llm_service):
        self.llm = llm_service
    
    async def extract_facts(self, text: str) -> List[dict]:
        """Extrai fatos estruturados de texto"""
        
        prompt = """Extraia TODOS os fatos do texto abaixo no formato JSON.
        
Formato:
{
  "facts": [
    {
      "subject": "O que/quem",
      "predicate": "propriedade/ação",
      "object": "valor",
      "sentence": "sentença original",
      "type": "definition|example|rule|number|date|name",
      "confidence": 0.95
    }
  ]
}

Texto:
{text}

JSON:"""
        
        response = await self.llm.generate(prompt)
        return json.loads(response)
    
    async def extract_entities(self, text: str) -> dict:
        """Extrai entidades nomeadas"""
        
        return {
            "concepts": await self._extract_concepts(text),
            "people": await self._extract_people(text),
            "places": await self._extract_places(text),
            "numbers": await self._extract_numbers(text),
            "dates": await self._extract_dates(text),
            "code_snippets": await self._extract_code(text)
        }
```

### 2. Source Grounding (Transcrição)

```python
class SourceGrounding:
    """Valida se fatos derivam da transcrição original"""
    
    def __init__(self, embedding_model, vector_db):
        self.embed = embedding_model
        self.vector_db = vector_db
    
    async def ground_facts(
        self,
        facts: List[dict],
        transcript: str,
        aula_id: str
    ) -> List[dict]:
        """Valida cada fato contra a transcrição"""
        
        # Indexa transcrição em chunks
        chunks = self._chunk_transcript(transcript, chunk_size=500, overlap=100)
        
        grounded_facts = []
        
        for fact in facts:
            # 1. Cria query a partir do fato
            query = f"{fact['subject']} {fact['predicate']} {fact['object']}"
            
            # 2. Busca chunks similares na transcrição
            similar_chunks = await self.vector_db.search(
                query_embedding=await self.embed.encode(query),
                collection=f"transcripts_{aula_id}",
                limit=3,
                min_similarity=0.60
            )
            
            # 3. Calcula "grounding score"
            grounding_score = self._calculate_grounding_score(
                fact=fact,
                similar_chunks=similar_chunks
            )
            
            # 4. Marca fato com score
            fact["grounding_score"] = grounding_score
            fact["source_chunks"] = similar_chunks
            fact["is_grounded"] = grounding_score > 0.7
            
            grounded_facts.append(fact)
        
        return grounded_facts
    
    def _calculate_grounding_score(self, fact: dict, chunks: List[dict]) -> float:
        """Score indica confiança que fato vem da transcrição"""
        
        if not chunks:
            return 0.0
        
        # Pontos positivos:
        # - Similarity score alto (0.9+)
        # - Palavras-chave exatas presentes
        # - Frase completa encontrada
        
        best_chunk = chunks[0]
        base_score = best_chunk.get("score", 0)
        
        # Bônus se palavras-chave estão no chunk
        keywords = fact["object"].split()
        keyword_match = sum(
            1 for kw in keywords 
            if kw.lower() in best_chunk.get("text", "").lower()
        ) / len(keywords) if keywords else 0
        
        combined_score = (base_score * 0.7) + (keyword_match * 0.3)
        return min(combined_score, 1.0)
    
    def _chunk_transcript(self, text: str, chunk_size: int = 500, overlap: int = 100) -> List[dict]:
        """Divide transcrição em chunks com overlap"""
        chunks = []
        for i in range(0, len(text), chunk_size - overlap):
            chunk = text[i:i + chunk_size]
            chunks.append({
                "text": chunk,
                "start": i,
                "end": i + len(chunk)
            })
        return chunks
```

### 3. Fact Verification (Knowledge Base)

```python
class FactVerification:
    """Valida fatos contra base de conhecimento"""
    
    def __init__(self, llm_service, knowledge_base_url=None):
        self.llm = llm_service
        self.kb_url = knowledge_base_url
    
    async def verify_facts(
        self,
        facts: List[dict],
        discipline: str
    ) -> List[dict]:
        """Verifica fatos contra conhecimento estabelecido"""
        
        verified = []
        
        for fact in facts:
            # Tipos que precisam verificação:
            if fact["type"] in ["definition", "rule", "number", "date"]:
                verification = await self._verify_single_fact(
                    fact=fact,
                    discipline=discipline
                )
                fact.update(verification)
            
            verified.append(fact)
        
        return verified
    
    async def _verify_single_fact(self, fact: dict, discipline: str) -> dict:
        """Verifica um fato individual"""
        
        # Exemplos de verificações:
        
        if fact["type"] == "definition":
            # Definição: busca em Wikipedia/Wiktionary
            result = await self._verify_definition(fact, discipline)
        
        elif fact["type"] == "date":
            # Data: verifica se plausível
            result = await self._verify_date(fact)
        
        elif fact["type"] == "number":
            # Número: valida range plausível
            result = await self._verify_number(fact)
        
        elif fact["type"] == "rule":
            # Regra: verifica contra conhecimento de domínio
            result = await self._verify_rule(fact, discipline)
        
        return {
            "verified": result.get("is_correct", False),
            "verification_confidence": result.get("confidence", 0),
            "verification_notes": result.get("notes", "")
        }
    
    async def _verify_definition(self, fact: dict, discipline: str) -> dict:
        """Verifica definição usando LLM"""
        
        prompt = f"""Na disciplina de {discipline}, defina '{fact['subject']}':
        
Definição do resumo: {fact['object']}

Essa definição está correta? Se não, qual seria correta?
Responda em JSON: {{"is_correct": bool, "confidence": 0-1, "correct_definition": "..."}}"""
        
        response = await self.llm.generate(prompt)
        return json.loads(response)
    
    async def _verify_date(self, fact: dict) -> dict:
        """Verifica validade de data"""
        try:
            date_obj = datetime.fromisoformat(fact["object"])
            return {
                "is_correct": date_obj <= datetime.now(),
                "confidence": 1.0,
                "notes": "Data válida"
            }
        except:
            return {
                "is_correct": False,
                "confidence": 1.0,
                "notes": "Formato de data inválido"
            }
    
    async def _verify_number(self, fact: dict) -> dict:
        """Verifica plausibilidade de número"""
        try:
            num = float(fact["object"])
            # Verificações básicas
            if num < 0 and "quantidade" in fact.get("predicate", ""):
                return {"is_correct": False, "confidence": 1.0}
            return {"is_correct": True, "confidence": 0.8}
        except:
            return {"is_correct": False, "confidence": 1.0}
```

### 4. Hallucination Detection

```python
class HallucinationDetector:
    """Detecta resumos com alta probabilidade de hallucination"""
    
    def __init__(
        self,
        fact_extractor: FactExtraction,
        source_grounding: SourceGrounding,
        fact_verifier: FactVerification
    ):
        self.extractor = fact_extractor
        self.grounding = source_grounding
        self.verifier = fact_verifier
    
    async def detect_hallucinations(
        self,
        resumo: str,
        transcript: str,
        aula_id: str,
        discipline: str
    ) -> dict:
        """Pipeline completo de detecção"""
        
        # 1. Extrai fatos do resumo
        facts = await self.extractor.extract_facts(resumo)
        
        # 2. Valida source (transcrição)
        grounded = await self.grounding.ground_facts(
            facts=facts,
            transcript=transcript,
            aula_id=aula_id
        )
        
        # 3. Verifica contra conhecimento
        verified = await self.verifier.verify_facts(
            facts=grounded,
            discipline=discipline
        )
        
        # 4. Calcula índices
        hallucination_report = self._analyze_hallucinations(verified)
        
        return {
            "facts": verified,
            "hallucination_report": hallucination_report,
            "should_block": hallucination_report["hallucination_index"] > 0.3,
            "confidence": hallucination_report["confidence"]
        }
    
    def _analyze_hallucinations(self, facts: List[dict]) -> dict:
        """Analisa probabilidade de hallucination"""
        
        total = len(facts)
        
        # Conta fatos não grounded e não verificados
        ungrounded = sum(1 for f in facts if not f.get("is_grounded", True))
        unverified = sum(1 for f in facts if f.get("verified") == False)
        
        # Índice de hallucination
        # 0.0 = confiável, 1.0 = totalmente alucinado
        hallucination_index = (ungrounded + unverified) / total if total > 0 else 0
        
        return {
            "total_facts": total,
            "ungrounded_facts": ungrounded,
            "unverified_facts": unverified,
            "hallucination_index": hallucination_index,
            "confidence": 1.0 if total > 10 else 0.5,  # Mais fatos = mais confiança
            "summary": self._summarize_issues(facts)
        }
    
    def _summarize_issues(self, facts: List[dict]) -> List[str]:
        """Sumariza problemas encontrados"""
        issues = []
        
        for fact in facts:
            if not fact.get("is_grounded"):
                issues.append(f"⚠️  Fato não encontrado na transcrição: '{fact.get('subject')}'")
            
            if fact.get("verified") == False:
                issues.append(f"❌ Fato não verificável: '{fact.get('object')}'")
        
        return issues[:5]  # Top 5 issues
```

### 5. API & Integration

```python
@router.post("/api/resumo/generate-and-validate")
async def generate_resumo_with_validation(
    aula_id: str,
    llm_provider: str = "claude"
):
    """Gera resumo com validação de hallucinations integrada"""
    
    # 1. Busca transcrição
    transcript = await db.get_transcript(aula_id)
    
    # 2. Gera resumo
    resumo = await llm_service.generate_resumo(transcript)
    
    # 3. Valida hallucinations
    validation = await hallucination_detector.detect_hallucinations(
        resumo=resumo,
        transcript=transcript,
        aula_id=aula_id,
        discipline=await db.get_aula_discipline(aula_id)
    )
    
    # 4. Decide ação
    if validation["should_block"]:
        # Hallucination detectada
        return {
            "status": "REJECTED",
            "reason": "Alta probabilidade de hallucination detectada",
            "issues": validation["hallucination_report"]["summary"],
            "hallucination_index": validation["hallucination_report"]["hallucination_index"],
            "suggested_action": "Regenerar com LLM diferente ou revisar manualmente"
        }
    
    elif validation["hallucination_report"]["hallucination_index"] > 0.15:
        # Moderado: salva mas marca para revisão
        return {
            "status": "ACCEPTED_WITH_WARNING",
            "resumo": resumo,
            "confidence": validation["confidence"],
            "warnings": validation["hallucination_report"]["summary"],
            "should_review": True
        }
    
    else:
        # Limpo: salva normalmente
        return {
            "status": "ACCEPTED",
            "resumo": resumo,
            "confidence": validation["confidence"],
            "validation_passed": True
        }
```

---

## Thresholds & Configuração

```python
VALIDATION_CONFIG = {
    "grounding_threshold": 0.70,      # Min score para considerar grounded
    "verification_confidence": 0.80,   # Min confidence na verificação
    "hallucination_block_threshold": 0.30,  # Bloqueia se > este índice
    "hallucination_warn_threshold": 0.15,   # Avisa se > este índice
    "min_facts_for_confidence": 10,    # Precisa de 10+ fatos para confiar no score
}
```

---

## Examples

### Exemplo 1: Hallucination Detectado

```
Resumo gerado: "O professor explicou sobre Data Warehouses"
Transcrição: "Falamos sobre Banco de Dados relacional..."

Detecção:
- "Data Warehouses" não encontrado na transcrição
- Grounding score: 0.15 (< 0.70 threshold)
- Status: REJEITADO

Ação: Regenerar ou revisar manualmente
```

### Exemplo 2: Fato Verificado

```
Resumo: "1NF elimina atributos multivalorados"
Status: VERIFICADO contra conhecimento de BD
Confidence: 0.95

Ação: Salvar com confiança alta
```

---

## Testing Strategy

- [ ] Unit: Fact extraction, grounding score, verification logic
- [ ] Integration: Pipeline end-to-end com resumos reais
- [ ] Benchmark: Dataset de 50+ resumos com anotações humanas
- [ ] False positives: Garantir que afirmações corretas não são bloqueadas

---

## Timeline

**Week 1:** Fact extraction + entity recognition  
**Week 2:** Source grounding com embeddings  
**Week 3:** Fact verification pipeline  
**Week 4:** Hallucination detection + API integration  
**Week 5:** Testing, tuning thresholds, deployment
