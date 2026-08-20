# Multi-Turn Memory Context Optimization

## Overview

Otimização de contexto multi-turn usando cache em Qdrant com TTL (Time-To-Live), reduzindo latência e custos de embedding em conversas longas.

**Status:** Roadmap - Fase 1  
**Prioridade:** Alta (Core Infrastructure)  
**Complexidade:** Alta

---

## Motivação

Atualmente, cada turno em uma conversa multi-turn:
1. Busca contexto completo no Qdrant
2. Re-encoda embeddings de mensagens anteriores
3. Carrega histórico inteiro na memória

**Problema:** Conversas de 50+ turnos ficam lentas (latência > 2s)

**Solução:**
- Cache inteligente com TTL
- Janela deslizante de contexto
- Compressão de histórico antigo
- Priorização de relevância

---

## Arquitetura

### Current Flow (Problema)

```
Turno 50: Nova pergunta
    ↓
[Busca Qdrant] → [Embedding contexto completo] → [LLM]
    ↓                                              ↓
   1s              0.5s                        0.8s
   
Total: 2.3s ❌
```

### Optimized Flow (Solução)

```
Turno 50: Nova pergunta
    ↓
[Cache Hit?] → SIM → [LLM com contexto cached]
    ↓                 ↓
   10ms              0.8s = 0.81s ✅
    
    ↓ NÃO
[Qdrant Search] → [Compress Old] → [Cache + TTL] → [LLM]
```

### Cache Strategy

```
┌─────────────────────────────────┐
│  Multi-Layer Cache System       │
└────────────┬────────────────────┘
             │
    ┌────────┴────────┬──────────────┐
    ▼                 ▼              ▼
┌──────────┐  ┌──────────────┐  ┌──────────┐
│ L1: Hot  │  │ L2: Warm     │  │ L3: Cold │
│ Cache    │  │ Cache        │  │ Archive  │
│ (Redis)  │  │ (Qdrant)     │  │ (MySQL)  │
│ TTL: 5m  │  │ TTL: 1h      │  │ Permanet │
└──────────┘  └──────────────┘  └──────────┘
```

---

## Implementação Detalhada

### 1. Context Window Manager

```python
class ContextWindowManager:
    """Gerencia janela deslizante de contexto com priorização"""
    
    def __init__(self, max_tokens=2000, warm_cache_size=500):
        self.max_tokens = max_tokens
        self.warm_cache = {}  # TTL cache
        
    async def get_context(
        self, 
        conversation_id: str, 
        query: str,
        k_recent: int = 3,  # últimos 3 turnos sempre
        k_relevant: int = 5  # 5 turnos mais relevantes
    ):
        # 1. Busca últimos K turnos (always include)
        recent = await self.get_recent_turns(conversation_id, k_recent)
        
        # 2. Tenta cache L1 (Redis)
        cached = await self.redis.get(f"context:{conversation_id}")
        if cached and not self.is_stale(cached):
            return self.merge_contexts(recent, cached)
        
        # 3. Busca Qdrant (L2 - warm cache)
        relevant = await self.qdrant_search(
            query=query,
            conversation_id=conversation_id,
            limit=k_relevant,
            min_similarity=0.6
        )
        
        # 4. Compacta contexto antigo
        archived = await self.compress_old_context(conversation_id)
        
        # 5. Salva em cache com TTL
        full_context = self.merge_contexts(recent, relevant)
        await self.redis.setex(
            f"context:{conversation_id}",
            ttl=300,  # 5 minutos
            value=full_context
        )
        
        return full_context
```

### 2. Qdrant TTL Integration

```python
class QdrantCacheManager:
    """Gerencia cache com TTL no Qdrant"""
    
    async def index_turn(
        self,
        conversation_id: str,
        turn_id: str,
        content: str,
        metadata: dict,
        ttl_seconds: int = 3600  # 1 hora
    ):
        # Embeds o conteúdo
        embedding = await self.embed_model.encode(content)
        
        # Indexa no Qdrant com payload incluindo TTL
        await self.qdrant.upsert(
            collection_name=f"conversations",
            points=[
                PointStruct(
                    id=hash(turn_id),
                    vector=embedding,
                    payload={
                        "conversation_id": conversation_id,
                        "turn_id": turn_id,
                        "content": content,
                        "created_at": time.time(),
                        "ttl_seconds": ttl_seconds,
                        "relevance_score": 1.0,  # Decai com tempo
                        **metadata
                    }
                )
            ]
        )
    
    async def search_with_ttl(
        self, 
        query: str,
        conversation_id: str,
        limit: int = 10
    ):
        now = time.time()
        
        results = await self.qdrant.search(
            collection_name="conversations",
            query_vector=await self.embed_model.encode(query),
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="conversation_id",
                        match=MatchValue(value=conversation_id)
                    ),
                    # Filtra por TTL: criado + ttl > agora
                    FieldCondition(
                        key="created_at",
                        range=Range(
                            gte=now - 3600  # Máximo 1h atrás
                        )
                    )
                ]
            ),
            limit=limit
        )
        
        # Ajusta relevância pelo decay de tempo
        scored_results = [
            {
                **r,
                "score": r.score * self.decay_score(r.payload["created_at"], now)
            }
            for r in results
        ]
        
        return sorted(scored_results, key=lambda x: x["score"], reverse=True)
    
    def decay_score(self, created_at: float, now: float) -> float:
        """Score decai exponencialmente com tempo"""
        age_seconds = now - created_at
        # e^(-0.0001 * age) → 1.0 em t=0, ~0.9 em t=15min
        return math.exp(-0.0001 * age_seconds)
```

### 3. Context Compression

```python
class ContextCompressor:
    """Compacta histórico antigo mantendo essência"""
    
    async def compress_context(
        self,
        turns: List[ConversationTurn],
        target_tokens: int = 500
    ):
        """Usa LLM para resumir turnos antigos"""
        
        old_turns = turns[:-10]  # Tudo exceto últimos 10
        
        if self.count_tokens(old_turns) <= target_tokens:
            return turns
        
        # Agrupa por tema
        themes = await self.cluster_turns(old_turns)
        
        compressed = []
        for theme_group in themes:
            summary = await self.llm.summarize(
                f"Resuma brevemente o seguinte contexto de conversa:\n"
                f"{theme_group}\n"
                f"Mantenha apenas pontos-chave.",
                max_tokens=200
            )
            compressed.append({
                "type": "compressed_summary",
                "original_turns": len(theme_group),
                "summary": summary,
                "theme": theme_group[0].get("theme")
            })
        
        return compressed + turns[-10:]  # Últimos 10 sempre completos
```

### 4. Database Schema Update

```sql
-- Nova tabela para cache metadata
CREATE TABLE context_cache_metadata (
    id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL,
    cache_key VARCHAR(255),
    ttl_seconds INT DEFAULT 3600,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    hit_count INT DEFAULT 0,
    compressed_size INT,
    INDEX idx_conversation_expires (conversation_id, expires_at),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

-- Altera conversation_turns para suportar compressão
ALTER TABLE conversation_turns 
ADD COLUMN is_compressed BOOLEAN DEFAULT FALSE,
ADD COLUMN original_turns_count INT,
ADD COLUMN compression_ratio FLOAT,
ADD COLUMN compressed_at TIMESTAMP;
```

### 5. API Changes

```python
# Novo endpoint para stats de cache
@router.get("/conversations/{conversation_id}/cache-stats")
async def get_cache_stats(conversation_id: str):
    """Retorna stats de cache e sugestões de otimização"""
    return {
        "cache_hits": int,
        "cache_misses": int,
        "hit_rate": float,
        "avg_response_time": float,
        "hot_cache_size": int,
        "compression_ratio": float,
        "memory_saved": int,
        "recommendations": List[str]
    }
```

---

## Métricas & Monitoring

```python
class CacheMetrics:
    def __init__(self):
        self.hits = 0
        self.misses = 0
        self.response_times = []
    
    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0
    
    @property
    def avg_response_time(self) -> float:
        return sum(self.response_times) / len(self.response_times) \
            if self.response_times else 0
```

**Targets:**
- Cache hit rate: > 70% em conversas ativas
- Response time: < 500ms (vs 2.3s atual)
- Memory savings: 60% redução em embeddings duplicados

---

## Fallback & Degradation

Se cache falha:
1. **L1 (Redis) down?** → Cai para L2 (Qdrant)
2. **L2 (Qdrant) down?** → Usa histórico em MySQL
3. **Tudo down?** → Usa apenas últimos 3 turnos (graceful degradation)

---

## Testing Strategy

- [ ] Unit tests: compression, decay score, TTL logic
- [ ] Integration: Redis + Qdrant + MySQL consistency
- [ ] Load: 100+ conversas simultâneas, 50+ turnos cada
- [ ] Correctness: Cache misses nunca retornam contexto errado

---

## Timeline

**Week 1:** Cache manager + Redis integration  
**Week 2:** Qdrant TTL, compression, decay score  
**Week 3:** Testing, monitoring, alerting  
**Week 4:** Deployment + optimization tuning
