# Health Dashboard para Monitorar Provedores LLM

## Overview

Dashboard em tempo real que monitora saúde, performance e disponibilidade dos 10+ provedores LLM integrados no INTARQ, com alertas e fallback automático.

**Status:** Roadmap - Fase 1  
**Prioridade:** Alta (Operations)  
**Complexidade:** Média

---

## Motivação

Atualmente INTARQ integra 10+ provedores:
- Claude, GPT-4, GPT-3.5, Gemini, Gemini Pro
- Llama 2, DeepSeek, Ollama, LocalAI, CohereXL

**Problemas:**
- ❌ Não sabe qual provedor está down
- ❌ Fallback é cego (tenta um por um)
- ❌ Latência alta em produção sem visibilidade
- ❌ Custos de chamadas não monitorados
- ❌ Rate limits atingidos sem aviso prévio

**Solução:** Dashboard que mostra status em tempo real + histórico + alertas

---

## Arquitetura

### System Overview

```
┌────────────────────────────────────────┐
│   Health Check Engine (background)     │
│   - Pings provedores a cada 30s        │
│   - Mede latência, taxa erro           │
│   - Calcula uptime/downtime            │
└─────────────────┬──────────────────────┘
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
   ┌─────────┐        ┌──────────┐
   │ Metrics │        │ Alerts   │
   │ Storage │        │ Service  │
   │(InfluxDB)        │          │
   └─────────┘        └──────────┘
        │                   │
        └────────┬──────────┘
                 ▼
    ┌────────────────────────┐
    │ Dashboard (Frontend)   │
    │ - Real-time charts    │
    │ - Status indicators   │
    │ - Cost tracking       │
    │ - Rate limit monitor  │
    └────────────────────────┘
```

### Health Metrics por Provedor

```
Para cada provedor rastreamos:

├─ Availability
│  ├─ Uptime %
│  ├─ Last check time
│  └─ Response status (OK, DOWN, DEGRADED)
│
├─ Performance
│  ├─ Avg latency (ms)
│  ├─ P95 latency
│  ├─ P99 latency
│  └─ Throughput (req/s)
│
├─ Reliability
│  ├─ Error rate %
│  ├─ Timeout rate
│  ├─ Rate limit hits
│  └─ Authentication failures
│
├─ Costs
│  ├─ Total spend (dia/mês)
│  ├─ $/1k tokens
│  ├─ Budget remaining
│  └─ Projected spend
│
└─ Quota
   ├─ Requests used / limit
   ├─ Tokens used / limit
   ├─ Time until reset
   └─ Current throttle rate
```

---

## Componentes

### 1. Health Check Engine

```python
class HealthCheckEngine:
    """Motor de health checks para provedores LLM"""
    
    def __init__(self, providers_config: Dict, metrics_db, alert_service):
        self.providers = providers_config
        self.metrics_db = metrics_db
        self.alerts = alert_service
        self.check_interval = 30  # segundos
    
    async def start(self):
        """Inicia background job de health checks"""
        while True:
            await self.run_health_checks()
            await asyncio.sleep(self.check_interval)
    
    async def run_health_checks(self):
        """Roda checks para todos os provedores em paralelo"""
        
        tasks = [
            self.check_provider_health(name, config)
            for name, config in self.providers.items()
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Salva métricas
        for provider_name, metrics in zip(self.providers.keys(), results):
            await self.metrics_db.save_metrics(provider_name, metrics)
            
            # Verifica alertas
            await self.check_for_alerts(provider_name, metrics)
    
    async def check_provider_health(self, name: str, config: dict) -> dict:
        """Executa health check de um provedor específico"""
        
        start_time = time.time()
        metrics = {
            "provider": name,
            "timestamp": start_time,
            "is_available": False,
            "latency_ms": 0,
            "error": None,
            "error_type": None,
        }
        
        try:
            # 1. Testa conectividade básica
            client = self._get_client(name, config)
            
            # 2. Faz teste simples (lightweight)
            response = await asyncio.wait_for(
                self._make_test_call(client, config),
                timeout=10  # timeout de 10s
            )
            
            # 3. Registra sucesso
            metrics["is_available"] = True
            metrics["latency_ms"] = (time.time() - start_time) * 1000
            metrics["status_code"] = 200
            
        except asyncio.TimeoutError:
            metrics["error"] = "Timeout"
            metrics["error_type"] = "TIMEOUT"
            metrics["latency_ms"] = 10000  # Timeout
            
        except Exception as e:
            metrics["error"] = str(e)
            metrics["error_type"] = self._classify_error(e)
            metrics["latency_ms"] = (time.time() - start_time) * 1000
        
        # 4. Busca quota/rate limit info
        quota_info = await self._get_quota_info(client, config)
        metrics.update(quota_info)
        
        return metrics
    
    async def _make_test_call(self, client, config: dict):
        """Faz chamada leve para testar saúde"""
        
        provider_type = config.get("type")
        
        if provider_type == "claude":
            return await client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=50,
                messages=[{"role": "user", "content": "Hi"}]
            )
        
        elif provider_type == "openai":
            return await client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=50
            )
        
        elif provider_type == "ollama":
            # Ollama: testa API diretamente
            return await client.generate(
                model="llama2",
                prompt="Hi",
                stream=False
            )
        
        # ... outros provedores
    
    async def _get_quota_info(self, client, config: dict) -> dict:
        """Busca informações de quota/rate limit"""
        
        try:
            # Diferentes provedores expõem isso de formas diferentes
            if hasattr(client, 'get_usage'):
                usage = await client.get_usage()
                return {
                    "quota_used": usage.get("total_tokens_used"),
                    "quota_limit": usage.get("quota_limit"),
                    "requests_this_period": usage.get("requests"),
                }
            else:
                return {
                    "quota_used": None,
                    "quota_limit": None,
                    "requests_this_period": None,
                }
        except:
            return {
                "quota_used": None,
                "quota_limit": None,
                "requests_this_period": None,
            }
    
    def _classify_error(self, error: Exception) -> str:
        """Classifica tipo de erro"""
        
        error_str = str(error).lower()
        
        if "401" in error_str or "unauthorized" in error_str:
            return "AUTH_ERROR"
        elif "429" in error_str or "rate limit" in error_str:
            return "RATE_LIMIT"
        elif "connection" in error_str:
            return "CONNECTION_ERROR"
        elif "timeout" in error_str:
            return "TIMEOUT"
        elif "500" in error_str or "internal server" in error_str:
            return "PROVIDER_ERROR"
        else:
            return "UNKNOWN"
```

### 2. Metrics Storage (InfluxDB)

```python
class MetricsStorage:
    """Armazena métricas time-series de health checks"""
    
    def __init__(self, influx_client):
        self.influx = influx_client
    
    async def save_metrics(self, provider_name: str, metrics: dict):
        """Salva métricas no InfluxDB"""
        
        point = Point("provider_health") \
            .tag("provider", provider_name) \
            .field("is_available", int(metrics["is_available"])) \
            .field("latency_ms", metrics["latency_ms"]) \
            .field("error_count", 1 if metrics["error"] else 0) \
            .field("quota_used", metrics.get("quota_used", 0)) \
            .field("quota_limit", metrics.get("quota_limit", 0)) \
            .time(metrics["timestamp"])
        
        await self.influx.write(point)
    
    async def get_provider_stats(
        self,
        provider_name: str,
        time_range: str = "-24h"  # últimas 24h
    ) -> dict:
        """Agrega stats de um provedor"""
        
        query = f"""
        from(bucket: "intarq")
          |> range(start: {time_range})
          |> filter(fn: (r) => r.provider == "{provider_name}")
        """
        
        result = await self.influx.query(query)
        
        # Processa resultado
        return {
            "uptime_percent": self._calc_uptime(result),
            "avg_latency": self._calc_avg_latency(result),
            "error_rate": self._calc_error_rate(result),
            "quota_trend": self._calc_quota_trend(result),
        }
```

### 3. Alert Service

```python
class AlertService:
    """Gera alertas baseado em thresholds"""
    
    def __init__(self, notification_service):
        self.notifier = notification_service
        
        self.thresholds = {
            "uptime_critical": 0.80,      # < 80% uptime
            "latency_warning": 2000,      # > 2s
            "latency_critical": 5000,     # > 5s
            "error_rate_warning": 0.05,   # > 5% error
            "error_rate_critical": 0.20,  # > 20% error
            "quota_warning": 0.80,        # > 80% usado
            "quota_critical": 0.95,       # > 95% usado
        }
    
    async def check_for_alerts(self, provider: str, metrics: dict):
        """Verifica se métricas violam thresholds"""
        
        alerts = []
        
        # Verifica uptime
        uptime = await self._get_uptime(provider, window="1h")
        if uptime < self.thresholds["uptime_critical"]:
            alerts.append({
                "type": "UPTIME_CRITICAL",
                "provider": provider,
                "value": uptime,
                "severity": "CRITICAL"
            })
        
        # Verifica latência
        if metrics["latency_ms"] > self.thresholds["latency_critical"]:
            alerts.append({
                "type": "LATENCY_CRITICAL",
                "provider": provider,
                "value": metrics["latency_ms"],
                "severity": "CRITICAL"
            })
        elif metrics["latency_ms"] > self.thresholds["latency_warning"]:
            alerts.append({
                "type": "LATENCY_WARNING",
                "provider": provider,
                "value": metrics["latency_ms"],
                "severity": "WARNING"
            })
        
        # Verifica quota
        if metrics.get("quota_limit"):
            quota_pct = metrics.get("quota_used", 0) / metrics["quota_limit"]
            if quota_pct > self.thresholds["quota_critical"]:
                alerts.append({
                    "type": "QUOTA_CRITICAL",
                    "provider": provider,
                    "value": quota_pct,
                    "severity": "CRITICAL"
                })
        
        # Envia alertas
        for alert in alerts:
            await self.notifier.send(alert)
```

### 4. Frontend Dashboard

```html
<!-- Componente Flutter/React para visualizar dashboard -->

<dashboard>
  <header>
    <title>LLM Provider Health</title>
    <refresh-button interval="30s" />
  </header>
  
  <section class="summary">
    <card class="overall-status">
      <stat>
        <label>Overall Status</label>
        <value status="healthy">All providers operational</value>
      </stat>
    </card>
    
    <card class="availability">
      <chart type="gauge">
        <title>Availability</title>
        <value>98.5%</value>
        <target>99%</target>
      </chart>
    </card>
    
    <card class="costs">
      <stat>
        <label>Monthly Spend</label>
        <value>$324.50</value>
        <trend>↑ 12% vs last month</trend>
      </stat>
    </card>
  </section>
  
  <section class="providers-list">
    <table>
      <thead>
        <tr>
          <th>Provider</th>
          <th>Status</th>
          <th>Latency (P95)</th>
          <th>Error Rate</th>
          <th>Uptime (24h)</th>
          <th>Quota Used</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr class="healthy">
          <td>Claude 3 Opus</td>
          <td><badge status="ok">✓ Healthy</badge></td>
          <td>320ms</td>
          <td>0.2%</td>
          <td>99.8%</td>
          <td>
            <progress value="45" max="100"></progress>
            45% / 1M req
          </td>
          <td>
            <button>Details</button>
            <button>Metrics</button>
          </td>
        </tr>
        
        <tr class="degraded">
          <td>GPT-4</td>
          <td><badge status="warning">⚠ Degraded</badge></td>
          <td>2100ms</td>
          <td>3.5%</td>
          <td>95.2%</td>
          <td>
            <progress value="92" max="100"></progress>
            92% / 500k req
          </td>
          <td>
            <button>Details</button>
            <button>Metrics</button>
          </td>
        </tr>
        
        <tr class="down">
          <td>Gemini Pro</td>
          <td><badge status="error">✗ Down</badge></td>
          <td>-</td>
          <td>100%</td>
          <td>0%</td>
          <td>-</td>
          <td>
            <button>Details</button>
            <button>Retry</button>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
  
  <section class="charts">
    <chart type="line">
      <title>Latency Trend (24h)</title>
      <series name="Claude">
        <data points="320, 315, 310, 322, ..." />
      </series>
      <series name="GPT-4">
        <data points="1200, 1500, 2100, 1800, ..." />
      </series>
    </chart>
    
    <chart type="line">
      <title>Uptime (7 days)</title>
      <series name="Providers">
        <data points="99.8%, 99.7%, 99.5%, 98.2%, ..." />
      </series>
    </chart>
    
    <chart type="bar">
      <title>Cost Breakdown</title>
      <series>
        <bar name="Claude" value="150" />
        <bar name="GPT-4" value="110" />
        <bar name="Gemini" value="45" />
      </series>
    </chart>
  </section>
  
  <section class="alerts">
    <title>Recent Alerts</title>
    <alert severity="critical" time="5 min ago">
      GPT-4 down for 15 minutes. Fallback to Claude activated.
    </alert>
    <alert severity="warning" time="1h ago">
      Gemini quota at 95%. Recommend upgrading plan.
    </alert>
  </section>
</dashboard>
```

---

## Database Schema

```sql
CREATE TABLE provider_health_checks (
    id VARCHAR(36) PRIMARY KEY,
    provider_name VARCHAR(100),
    check_timestamp TIMESTAMP,
    is_available BOOLEAN,
    latency_ms INT,
    error_type VARCHAR(50),
    error_message TEXT,
    quota_used BIGINT,
    quota_limit BIGINT,
    status_code INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_provider_timestamp (provider_name, check_timestamp)
);

CREATE TABLE provider_metrics_daily (
    id VARCHAR(36) PRIMARY KEY,
    provider_name VARCHAR(100),
    date DATE,
    uptime_percent FLOAT,
    avg_latency_ms INT,
    p95_latency_ms INT,
    p99_latency_ms INT,
    error_rate FLOAT,
    total_requests INT,
    failed_requests INT,
    cost_usd FLOAT,
    UNIQUE KEY uq_provider_date (provider_name, date)
);

CREATE TABLE provider_alerts (
    id VARCHAR(36) PRIMARY KEY,
    provider_name VARCHAR(100),
    alert_type VARCHAR(50),
    severity ENUM('INFO', 'WARNING', 'CRITICAL'),
    message TEXT,
    metric_value FLOAT,
    threshold FLOAT,
    created_at TIMESTAMP,
    acknowledged_at TIMESTAMP,
    acknowledged_by VARCHAR(100)
);
```

---

## API Endpoints

```python
@router.get("/api/health/providers")
async def get_all_providers_status():
    """Status snapshot de todos os provedores"""
    return {
        "timestamp": datetime.now(),
        "providers": [
            {
                "name": "claude",
                "status": "healthy",
                "latency_ms": 320,
                "uptime_24h": 99.8,
                "quota_used": 0.45
            },
            # ... mais provedores
        ]
    }

@router.get("/api/health/providers/{provider_name}")
async def get_provider_details(provider_name: str):
    """Detalhes de um provedor específico"""
    return {
        "provider": provider_name,
        "status": "healthy",
        "current": {
            "latency_ms": 320,
            "is_available": True,
        },
        "last_24h": {
            "uptime_percent": 99.8,
            "avg_latency": 315,
            "error_rate": 0.002,
            "requests": 45000
        },
        "quota": {
            "used": 450000,
            "limit": 1000000,
            "percent": 45,
            "reset_at": "2024-09-01T00:00:00Z"
        }
    }

@router.get("/api/health/alerts")
async def get_recent_alerts(limit: int = 20):
    """Alertas recentes"""
    return {
        "alerts": [...],
        "total": 5,
        "critical": 1,
        "warnings": 2
    }
```

---

## Thresholds & Configuration

```yaml
health_check_config:
  interval_seconds: 30
  timeout_seconds: 10
  
  thresholds:
    uptime_critical: 0.80
    latency_warning_ms: 2000
    latency_critical_ms: 5000
    error_rate_warning: 0.05
    error_rate_critical: 0.20
    quota_warning_percent: 0.80
    quota_critical_percent: 0.95
  
  alert_channels:
    - email
    - slack
    - in_app_notification
```

---

## Timeline

**Week 1:** Health check engine + InfluxDB setup  
**Week 2:** Alert service + thresholds  
**Week 3:** Frontend dashboard development  
**Week 4:** API integration + testing  
**Week 5:** Deployment + monitoring setup
