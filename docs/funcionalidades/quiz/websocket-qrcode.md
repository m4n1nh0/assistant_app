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
- [x] Monitor exibe somente a pergunta atual durante a rodada.
- [x] Professor controla `Iniciar Quiz`, `Encerrar Pergunta` e `Próxima Pergunta`.
- [x] Ranking top 10 por rodada e ranking geral/final enviados pelo WebSocket.
- [x] Player público consulta `/education/quiz/{quiz_id}/state` para sair da pergunta quando a rodada encerra.
- [x] Ranking por **pontos acumulados** em todas as telas (professor, WebSocket e aluno); entre perguntas cada linha mostra também o `+N nesta pergunta`.
- [x] **Tempo por pergunta** escolhido pelo professor: ao acabar, a pergunta fecha sozinha e o ranking aparece; o professor chama a próxima.
- [x] Painel do professor legível (tema escuro de ponta a ponta), com enunciado **e alternativas**, e **maximizável** (tela cheia, letras maiores, QR Code ao lado).
- [x] **Idioma escolhido junto do nome**: a tela de entrada tem o seletor Português / Español / English, e o idioma vale para a interface **e para a pergunta e as alternativas** (traduzidas pelo modelo do professor e gravadas).
- [ ] WebSocket autenticado por JWT e autorização estrita do professor ainda seguem como roadmap.
- [ ] Gráficos avançados e exportação de resultados ainda seguem como roadmap.

---

## 🎯 Visão Geral

Sistema de quiz onde:
1. **Professor** prepara e publica quiz para compartilhar via **QR Code**
2. **Alunos** escaneiam o QR Code, entram pelo nome e aguardam a pergunta atual
3. **Professor** controla a rodada e monitora ranking em tempo real via **WebSocket**

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
│ 4. Confere perguntas preparadas     │
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
│ Controle ao Vivo:                   │
│ ├─ Iniciar Quiz                     │
│ ├─ Pergunta Atual                   │
│ ├─ Encerrar Pergunta                │
│ └─ Top 10 da Rodada                 │
│ (Atualiza a cada 2s via WebSocket)  │
└─────────────────────────────────────┘
                 ↓
┌─────────────────────────────────────┐
│ Alunos (Mobile/Tablet)              │
│                                     │
│ 1. Escaneia QR Code                 │
│ 2. Browser abre                     │
│    /education/quiz/quiz-id/play     │
│ 3. Informa o nome                   │
│ 4. Seleciona resposta               │
│ 5. Clica "CONFIRMAR"                │
│ 6. Aguarda encerramento da rodada   │
│ 7. Vê ranking e sua colocação       │
│ 8. Aguarda a próxima pergunta       │
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

#### Campos do quiz ao vivo (acrescentados ao `stats_update`)

```json
{
  "time_limit_seconds": 30,
  "seconds_remaining": 18,
  "current_question": {
    "question_id": "q1",
    "index": 0,
    "question_text": "Qual forma normal elimina dependência transitiva?",
    "options": [
      {"label": "A", "texto": "1FN"},
      {"label": "B", "texto": "3FN"}
    ],
    "total_answers": 7
  },
  "ranking_top10": [
    {"position": 1, "student_name": "Bia", "score": 1200, "round_score": 800, "round_correct": true}
  ]
}
```

- `time_limit_seconds` é o prazo por pergunta (`0` = o professor encerra na mão).
  `seconds_remaining` só existe com a pergunta aberta e prazo definido; o painel
  desconta o relógio localmente a partir dele, sem depender de os relógios das
  duas máquinas concordarem.
- `options` traz as alternativas para o painel do professor. O campo `correta`
  **só aparece depois que a pergunta fecha**: o painel costuma estar projetado.
- `ranking_top10` ordena pelo acumulado (`score`); `round_score` é o que o aluno
  somou na pergunta atual. O antigo `current_ranking_top10` continua no pacote
  por compatibilidade, mas o painel não o usa mais.

#### 3. Keepalive (ping/pong)

```json
// Enviado pelo cliente a cada 30s
{ "type": "ping" }

// Respondido pelo servidor
{ "type": "pong" }
```

---

## ⏱️ Tempo por pergunta e fluxo da rodada

```
Iniciar Quiz ──► pergunta aberta ──┬─ acabou o tempo ────┐
                                   └─ "Encerrar Agora" ──┤
                                                         ▼
                    Próxima Pergunta ◄── ranking (acumulado + "+N nesta pergunta")
```

- O professor escolhe o prazo no painel (`Manual`, 15s … 2 min, ou `Outro...` de
  5 a 600s) em qualquer fase. `POST /education/quiz/{quiz_id}/settings` com
  `{"time_limit_seconds": 30}`; `0` volta ao modo manual.
- O prazo vale **a partir da próxima pergunta**: ao abrir a pergunta o servidor
  grava `question_ends_at`, então mudar o tempo no meio da rodada não encurta nem
  estica a que a turma já está respondendo.
- **Não há tarefa em segundo plano.** Quem lê o quiz (a tela do aluno a cada 2s, o
  monitor do professor a cada 2s, `GET /quiz/{id}`) confere o prazo e fecha a
  pergunta com um `UPDATE` condicional na pergunta e na fase lidas — sobrevive a
  reinício do servidor e a vários workers, e um leitor com o quiz velho nunca fecha
  a pergunta nova que o professor acabou de abrir.
- **Folga de 2s** depois do zero: a resposta enviada no último segundo ainda cruza
  a rede. Depois da folga a resposta é descartada.
- A pontuação por velocidade usa o prazo da pergunta como janela (responder no
  último segundo vale o mínimo, 100 pontos, com 15s ou com 60s). Sem prazo, a
  janela segue sendo de 30s.
- `close-question` é idempotente: encerrar uma pergunta que o relógio acabou de
  encerrar (ou clicar duas vezes) devolve o resultado, não um erro.
- A tela do aluno só mostra o relógio quando há prazo; no modo manual a barra que
  encolhia sozinha foi removida, porque era um prazo que não existia.

---

## 🌐 Idioma do aluno

- **Escolha na entrada.** A tela do nome mostra `Português | Español | English`.
  Trocar o idioma ali recarrega a tela (os textos mudam na hora) sem perder o nome
  já digitado. O idioma escolhido vence o do navegador e o da URL, e fica num
  cookie: links sem `?lang=` seguem no idioma do aluno. O seletor da tela da
  pergunta continua funcionando.
- **Pergunta e alternativas traduzidas.** A tradução é feita pelo modelo do
  professor (as chaves dele são carregadas do banco, porque o aluno é anônimo) e
  gravada em `question_translations`, uma vez por pergunta e idioma: a turma
  inteira lê a mesma tradução.
- **Pronta antes de a pergunta abrir.** Quando o primeiro aluno entra num idioma,
  o quiz inteiro começa a ser traduzido em segundo plano, na ordem em que as
  perguntas avançam, em lotes de 5. Se a pergunta abrir antes de a tradução ficar
  pronta, a tela espera até 12s por ela. A turma toda pedindo o mesmo idioma gera
  uma chamada ao modelo, não uma por aluno.
- **O gabarito não muda.** O aluno envia a **letra** da alternativa, e é a letra
  que corrige a resposta; só o texto exibido é traduzido.
- **Tradução que não fecha é descartada** (outra quantidade de alternativas, letra
  trocada, texto vazio): o aluno lê o original em português, nunca uma pergunta
  traduzida errada.
- **Falha não derruba a tela.** Sem provedor de IA ou com o modelo fora do ar, o
  aluno lê a pergunta original com a interface no idioma escolhido, e o servidor
  espera 60s antes de tentar de novo (a tela recarrega a cada 2s, e cada recarga
  repetiria a chamada que falha).
- **Reserva pelo app do professor (Codex / Claude).** O aluno é anônimo e não tem
  provedor, mas o painel do professor tem os agentes conectados. Quando falta
  tradução e o servidor não consegue fazê-la, o painel traduz:

  ```
  WebSocket: translations_pending = [{language, students, missing, backend_failed}]
  painel ──GET /quiz/{id}/translation/prompt?language=en──► só as perguntas sem tradução
  painel ──executa Codex ou Claude no CLI local──►
  painel ──POST /quiz/{id}/translation/external──► servidor valida e grava
  ```

  - O servidor tem a primeira chance: o painel só age quando `backend_failed` ou
    depois de 20s sem o servidor resolver. Falhou, o painel avisa o professor
    ("N aluno(s) leem em English com a pergunta em português") e só tenta de novo
    depois de 90s.
  - Usa o primeiro agente que o servidor aceitar, sem gastar os dois.
  - A tradução do agente passa pela **mesma validação** da do servidor: o que não
    fecha com a pergunta original é descartado.
  - Sem agente conectado, o painel diz isso ao professor em vez de falhar calado.
  - O aluno que já está na pergunta aberta continua lendo o original dela; as
    perguntas seguintes já saem traduzidas.
- O ranking mostra o enunciado traduzido quando já há tradução, sem esperar o
  modelo. A tela do professor continua em português.

---

## ♿ Acessibilidade da tela do aluno

Primeira rodada (teclado e leitor de tela):

- **`lang` no texto que de fato está naquele idioma.** O `<html lang>` segue a
  interface, mas a pergunta e as alternativas declaram o idioma **real** do texto.
  Quando a tradução falha e o aluno lê o original, o bloco sai como `lang="pt-BR"`
  mesmo com a interface em inglês: o leitor de tela usa a voz certa e o botão
  "traduzir" do navegador atua sobre o trecho certo. Vale também para o
  enunciado do ranking.
- **Pergunta e alternativas agrupadas** em `fieldset` + `legend`: o leitor de tela
  diz a qual pergunta cada opção pertence.
- **Foco visível** nas alternativas, nos botões e no seletor de idioma da entrada.
  Os botões de idioma ficam escondidos só da vista, não do teclado.
- **Idioma como grupo com legenda**, cada opção lida no próprio idioma
  ("Español" em espanhol), e o idioma atual marcado com `aria-current` no seletor
  da pergunta.
- **Campo do nome com nome acessível** (`aria-label` e `autocomplete="name"`).
- **`prefers-reduced-motion`** desliga a animação da barra de tempo.

Segunda rodada (sem recarregar a página):

- **A tela não se recarrega mais a cada 2s.** A página consulta `/state` e só
  troca o conteúdo quando o estado do quiz muda (nova pergunta, resultado, fim):
  busca a página nova, troca o corpo, move o foco para o novo título e segue o
  idioma que a página nova declara. O leitor de tela não volta mais ao início da
  página a cada 2s. Sem JavaScript, o `<noscript>` mantém o recarregamento antigo.
- **O relógio é anunciado só em 10s e 5s**, numa região `aria-live` à parte. O
  número que muda por segundo e a barra (`aria-hidden`) ficam fora dela.
- **O resultado do aluno vem antes da lista** do ranking.
- **A consulta de estado marca a presença do aluno.** Era o recarregamento que
  mantinha o aluno "online" no lobby do professor; agora é `/state` (só para quem
  já entrou, com cookie de tentativa e nome, e só com o quiz aberto). Consulta
  anônima não cria participante.
- O ranking final não consulta nem recarrega.

O script foi executado num DOM simulado (jsdom) com as páginas reais do servidor:
sem mudança de estado nada é refeito; cada mudança gera uma busca de página; o
foco vai para o título novo; o relógio anuncia só nos marcos; o ranking final
para a consulta. Isso achou um defeito (o script mantinha a unidade do relógio da
página antiga) já corrigido e coberto por teste. Esse cenário não está no
repositório: não há infraestrutura de teste de JavaScript.

Ainda falta uma verificação com leitor de tela real (NVDA, VoiceOver) e a revisão
de contraste.

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
4. Questões recebem score de confiança e sinalização de revisão
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
- [x] Aviso ao professor quando o quiz fica pronto (no app, Telegram e WhatsApp)
- [ ] Análise de desempenho por aluno
- [ ] Exportar resultados em PDF
- [ ] Gráficos de desempenho em tempo real
- [ ] Chat entre professor e alunos durante quiz
- [x] Banco de questões (reusar em vários quizzes)

---

Tudo pronto! 🚀 WebSocket + QR Code implementados e integrados ao Modo Educação!
