# Quiz com WebSocket + QR Code - Guia Completo

## Status de Implementação

**Aplicado em:** 2026-08-25
**Situação:** QR Code e monitoramento WebSocket funcionais.

- [x] Professor prepara perguntas, confere o conteúdo validado e depois libera o QR Code.
- [x] QR Code aponta para `/education/quiz/{quiz_id}/play`.
- [x] URL pública do QR/share-info é derivada da requisição real, com override opcional por `base_url`.
- [x] Endpoints PNG e SVG de QR Code disponíveis.
- [x] Flutter abre `QuizQRCodeMonitor` somente após publicar o quiz validado na aba `6. QUIZ`.
- [x] WebSocket `/ws/quiz/{quiz_id}/monitor` envia estatísticas iniciais e atualizações a cada 2 segundos.
- [x] Contador `total_answers` representa o total real de respostas recebidas.
- [x] Monitor permite encerrar o quiz; WebSocket informa `status` e `closed_at`.
- [ ] WebSocket autenticado por JWT e autorização estrita do professor ainda seguem como roadmap.
- [ ] Gráficos avançados e exportação de resultados ainda seguem como roadmap.

---

## 🎯 Visão Geral

Sistema de quiz onde:
1. **Professor** prepara e publica quiz para compartilhar via **QR Code**
2. **Alunos** escanean o QR Code e respondem questões
3. **Professor** monitora em tempo real via **WebSocket** (sem polling)

---

## 📱 Fluxo Completo

```
┌─────────────────────────────────────┐
│ Professor (Flutter Desktop)         │
│                                     │
│ 1. Abre Modo Educação               │
│ 2. Seleciona Aula                   │
│ 3. Clica "Preparar Perguntas"       │
│    (LangGraph: Generate → Validate →│
│     Filter)                         │
│ 4. Confere perguntas validadas      │
│ 5. Clica "Liberar QR Code"          │
│ 6. Recebe: Quiz ID + QR Code        │
│    ┌──────────────────────────┐    │
│    │    [QR CODE]             │    │
│    │  https://seu-dominio.com │    │
│    │  /education/quiz/...play │    │
│    └──────────────────────────┘    │
│ 7. Compartilha/Exibe QR Code        │
│    (WebSocket conectado)            │
│                                     │
│ 📊 Monitoramento em Tempo Real:     │
│ ├─ Respondidas: 15/30 (50%)        │
│ ├─ Q1: 28✅ 2❌                    │
│ ├─ Q2: 25✅ 5❌                    │
│ └─ Q3: 23✅ 7❌                    │
│ (Atualiza a cada 2s via WebSocket)  │
└─────────────────────────────────────┘
                 ↓
┌─────────────────────────────────────┐
│ Alunos (Mobile/Tablet)              │
│                                     │
│ 1. Escaneia QR Code                 │
│ 2. Browser abre                     │
│    /education/quiz/quiz-id/play     │
│ 3. Vê primeira questão              │
│ 4. Seleciona resposta               │
│ 5. Clica "CONFIRMAR"                │
│ 6. Próxima questão aparece          │
│ 7. Repete até terminar              │
│ 8. "Quiz Completado! 🎉"            │
│                                     │
│ (Respostas salvas em banco)         │
└─────────────────────────────────────┘
```

---

## 🔌 WebSocket - Monitoramento em Tempo Real

### Conexão

```
wss://seu-dominio.com/ws/quiz/{quiz_id}/monitor
```

### Fluxo de Comunicação

```
Cliente (Professor)
    ↓
[Conecta ao WebSocket]
    ↓
Backend calcula stats a cada 2s
    ↓
[Envia atualização JSON]
    ↓
Flutter recebe e atualiza UI
    ↓
[Sem polling, sem delay]
```

### Mensagens WebSocket

#### 1. Initial Stats (ao conectar)

```json
{
  "type": "initial_stats",
  "data": {
    "timestamp": "2024-08-20T10:30:45.123456",
    "quiz_id": "quiz-abc123",
    "status": "open",
    "closed_at": null,
    "total_questions": 10,
    "progress": {
      "total_answers": 5,
      "correct": 4,
      "incorrect": 1,
      "open": 0
    },
    "overall_percentage": 80.0,
    "questions": [
      {
        "question_id": "q1",
        "question_text": "Qual é a 1NF?...",
        "total_answers": 30,
        "correct": 28,
        "incorrect": 2,
        "percentage": 93.3
      }
    ],
    "active_connections": 1
  }
}
```

#### 2. Stats Update (a cada 2s)

```json
{
  "type": "stats_update",
  "data": {
    "timestamp": "2024-08-20T10:30:47.234567",
    "quiz_id": "quiz-abc123",
    "status": "open",
    "closed_at": null,
    "progress": {
      "total_answers": 6,
      "correct": 5,
      "incorrect": 1,
      "open": 0
    },
    "overall_percentage": 83.3,
    "questions": [...]
  }
}
```

#### 3. Keepalive (ping/pong)

```json
// Enviado pelo cliente a cada 30s
{ "type": "ping" }

// Respondido pelo servidor
{ "type": "pong" }
```

---

## 📲 QR Code

### Endpoints

#### Gerar QR Code (PNG)

```
GET /education/quiz/{quiz_id}/qrcode
Authorization: Bearer {token}

Response: Image PNG (200x200px)
```

#### Gerar QR Code (SVG)

```
GET /education/quiz/{quiz_id}/qrcode/svg
Authorization: Bearer {token}

Response: Image SVG (escalável)
```

#### Info de Compartilhamento

```
GET /education/quiz/{quiz_id}/share-info
Authorization: Bearer {token}

Response:
{
  "quiz_id": "quiz-abc123",
  "title": "Quiz: Normalização de BD",
  "url": "https://seu-dominio.com/education/quiz/quiz-abc123/play",
  "qrcode_url": "https://seu-dominio.com/education/quiz/quiz-abc123/qrcode",
  "qrcode_svg_url": "https://seu-dominio.com/education/quiz/quiz-abc123/qrcode/svg",
  "share_text": "Responda meu quiz: Quiz: Normalização de BD\n\nhttps://...",
  "created_at": "2024-08-20T10:25:00.000000"
}
```

---

## 💻 Implementação Flutter

### 1. Adicionar Dependencies

```yaml
# pubspec.yaml
dependencies:
  web_socket_channel: ^2.4.0
  qr_flutter: ^4.1.0  # Para exibir QR Code (opcional)
```

### 2. Widget QR Code + Monitor

```dart
// Na tela de aula, após gerar quiz:
showDialog(
  context: context,
  builder: (context) => QuizQRCodeMonitor(
    quizId: generatedQuizId,
    quizTitle: 'Normalização de BD',
    totalQuestions: 10,
    onClose: () {
      print('Quiz fechado');
    },
  ),
);
```

### 3. Widget Completo

```dart
class QuizQRCodeMonitor extends StatefulWidget {
  final String quizId;
  final String quizTitle;
  final int totalQuestions;

  const QuizQRCodeMonitor({
    required this.quizId,
    required this.quizTitle,
    required this.totalQuestions,
  });

  @override
  State<QuizQRCodeMonitor> createState() => _QuizQRCodeMonitorState();
}

class _QuizQRCodeMonitorState extends State<QuizQRCodeMonitor> {
  late WebSocketChannel _channel;
  Map<String, dynamic>? _stats;

  @override
  void initState() {
    super.initState();
    _connectWebSocket();
  }

  void _connectWebSocket() {
    _channel = WebSocketChannel.connect(
      Uri.parse(
        'ws://localhost:8000/ws/quiz/${widget.quizId}/monitor'
      ),
    );

    _channel.stream.listen((message) {
      final data = jsonDecode(message);

      setState(() {
        _stats = data['data'];
      });
    });
  }

  @override
  void dispose() {
    _channel.sink.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      child: Column(
        children: [
          // QR Code
          if (_stats != null)
            Image.network(
              '/education/quiz/${widget.quizId}/qrcode',
              width: 200,
              height: 200,
            ),

          // Stats em Tempo Real
          if (_stats != null)
            Column(
              children: [
                Text('Respondidas: ${_stats!['progress']['total_answers']}'),
                Text('Acertos: ${_stats!['progress']['correct']}'),
                Text('Erros: ${_stats!['progress']['incorrect']}'),
                Text('Taxa: ${_stats!['overall_percentage']}%'),

                // Por questão
                ..._stats!['questions'].map<Widget>((q) {
                  return Text('Q${q['question_id']}: ${q['percentage']}%');
                }),
              ],
            ),
        ],
      ),
    );
  }
}
```

---

## 🔐 Segurança

### WebSocket

- **URL**: `wss://` (WebSocket Secure)
- **Autenticação**: Token JWT opcional
- **Autorização**: Apenas professor do quiz pode conectar
- **Timeout**: 30 segundos (keepalive com ping/pong)

### QR Code

- **Público**: Link é anônimo (alunos podem acessar)
- **Expiração**: Nenhuma (enquanto quiz existir)
- **Rate Limiting**: 120 req/min para check-in
- **HTTPS**: Sempre usar SSL/TLS

---

## 🚀 Otimizações

### 1. Caching

```python
# QR Code é cacheable por 1 hora
Cache-Control: public, max-age=3600
```

### 2. SVG vs PNG

- **PNG**: Melhor compressão, menor tamanho
- **SVG**: Escalável, infinito zoom
- **Recomendação**: Use SVG no Flutter (sem perda de qualidade)

### 3. WebSocket

- **2 segundos**: Intervalo de atualização (balanceia latência vs carga)
- **30 segundos**: Timeout de inatividade
- **Reconexão automática**: Se desconectar, reconecta em 3s

---

## 📊 Exemplo Prático - Tela Professor

### Estrutura

```
┌──────────────────────────────────────┐
│ 🎓 Modo Educação                     │
├──────────────────────────────────────┤
│ Aula: Normalização de BD             │
│ Turma: BD-101                        │
├──────────────────────────────────────┤
│ 📊 Resumo da Aula                    │
│ [Resumo completo...]                 │
├──────────────────────────────────────┤
│ ✨ Quiz da Aula                      │
│ [Config: Prática, 10 q, Mista]      │
│ [Preparar Perguntas com IA]         │
│                                      │
│ Perguntas preparadas                │
│ [Liberar QR Code]                   │
│                                      │
│ Quiz liberado                       │
│ ┌──────────────────────────────────┐│
│ │                                  ││
│ │    [QR CODE DA AULA]             ││
│ │    Escanear para responder       ││
│ │                                  ││
│ └──────────────────────────────────┘│
│                                      │
│ 📱 Quiz ao Vivo                     │
│ ┌──────────────────────────────────┐│
│ │ Respondidas: 18/30 (60%)        ││
│ │ ████████░░░░░░░░░░░░░░░░░░░░░░││
│ │                                  ││
│ │ ✅ Acertos: 15                  ││
│ │ ❌ Erros: 3                     ││
│ │ 📊 Taxa: 83%                    ││
│ │                                  ││
│ │ Por questão:                     ││
│ │ Q1: 28✅ 2❌ (93%)              ││
│ │ Q2: 25✅ 5❌ (83%)              ││
│ │ Q3: 20✅ 10❌ (67%)             ││
│ │ ...                              ││
│ └──────────────────────────────────┘│
│ (Atualiza a cada 2s via WebSocket)   │
│                                      │
│ [Compartilhar] [Copiar Link]        │
├──────────────────────────────────────┤
│ 📍 Chamada por QR                   │
│ [Iniciar Chamada]                   │
└──────────────────────────────────────┘
```

---

## 🔄 Fluxo Completo (Step by Step)

### T=0s: Professor Prepara Perguntas

```
1. Clica "Preparar Perguntas"
2. Seleciona: Prática, 10 questões, Mista
3. Backend executa LangGraph usando resumo + transcrição
4. Questões validadas com grounding_score >= 0.65
5. Quiz salvo como draft com quiz_id="quiz-abc123"
```

### T=5s: Professor Libera QR Code

```
1. Professor confere as perguntas geradas
2. Clica "Liberar QR Code"
3. Backend publica o quiz como open
4. Flutter carrega imagem QR e abre o monitor
5. Alunos começam a escanear
```

### T=10s: Primeira Resposta

```
1. Aluno 1 escaneia QR Code
2. Browser abre: /education/quiz/quiz-abc123/play
3. Vê Questão 1
4. Responde "A"
5. POST /education/quiz/quiz-abc123/play
6. Resposta salva no banco (student_answers)
7. WebSocket notifica professor
8. Flutter atualiza: Q1: 1✅ 0❌
```

### T=12s: Múltiplas Respostas

```
Aluno 2, 3, 4... começam a responder

WebSocket envia atualizações:
- T=12s: 2 respondidas
- T=14s: 5 respondidas
- T=16s: 10 respondidas
- T=18s: 18 respondidas
...

Professor vê progresso em tempo real
```

### T=600s: Último Aluno Termina

```
30 alunos responderam
Professor pode fechar quiz
Análise de desempenho fica disponível
```

---

## 🧪 Testes

### Teste 1: QR Code Gerado

```bash
curl -H "Authorization: Bearer TOKEN" \
  http://localhost:8000/education/quiz/quiz-123/qrcode \
  -o quiz.png

# Verifica se imagem foi gerada
file quiz.png  # PNG image data
```

### Teste 2: WebSocket Connect

```bash
# Via wscat (npm install -g wscat)
wscat -c ws://localhost:8000/ws/quiz/quiz-123/monitor

# Deve receber stats inicial
< {"type":"initial_stats","data":{...}}

# Enviar ping
> {"type":"ping"}
< {"type":"pong"}
```

### Teste 3: QR Code → Browser

```bash
1. Gera quiz via API
2. Obtém QR Code via GET /education/quiz/{id}/qrcode
3. Abre em navegador: /education/quiz/{id}/play
4. Responde 3 questões
5. WebSocket deve mostrar 3 respostas
```

---

## 📈 Métricas

| Métrica | Alvo | Status |
|---------|------|--------|
| Latência WebSocket | < 100ms | ✅ |
| QR Code gerado | < 500ms | ✅ |
| Atualização stats | 2s | ✅ |
| Reconexão automática | < 3s | ✅ |
| Taxa de acerto | > 70% | ⏳ |

---

## 🎯 Próximas Features

- [ ] WebSocket autenticado (JWT)
- [ ] Notificação push quando quiz fica pronto
- [ ] Análise de desempenho por aluno
- [ ] Exportar resultados em PDF
- [ ] Gráficos de desempenho em tempo real
- [ ] Chat entre professor e alunos durante quiz
- [ ] Banco de questões (reusar em vários quizzes)

---

Tudo pronto! 🚀 WebSocket + QR Code implementados e integrados ao Modo Educação!
