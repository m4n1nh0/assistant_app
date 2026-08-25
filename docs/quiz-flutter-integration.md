# Integração do Quiz no Flutter - Modo Educação

## Status de Implementação

**Aplicado em:** 2026-08-25
**Situação:** integração principal implementada com ajuste de fluxo.

- [x] `QuizGeneratorWidget` integrado ao Modo Educação.
- [x] Widget usado dentro da aba dedicada `6. QUIZ`, não na gravação ao vivo.
- [x] A aba lista apenas aulas encerradas.
- [x] A geração fica bloqueada quando a aula não tem resumo.
- [x] Ao gerar, o monitor de QR Code abre automaticamente.
- [x] Links copiados usam `api.baseUrl`, não domínio placeholder.
- [x] QR autenticado carrega com header `Authorization`.
- [ ] Preview/revisão das questões antes de salvar ainda não foi implementado.
- [ ] Relatórios de desempenho e exportação seguem como roadmap.

> Nota: exemplos antigos neste documento mostram o widget dentro de uma tela de detalhes da aula. No app atual, a decisão de produto é manter quiz em aba própria e somente após encerrar a gravação.

---

## 📱 Como Integrar na Interface

### 1. Adicionar Widget de Quiz na Tela de Aula

Na tela de detalhes da aula (depois do resumo), adicione um widget para gerar quiz:

```dart
// lib/screens/lesson_detail_screen.dart

import 'package:flutter/material.dart';
import '../widgets/quiz_generator_widget.dart';

class LessonDetailScreen extends StatefulWidget {
  final String lessonId;
  final String lessonTitle;
  
  // ...

  @override
  State<LessonDetailScreen> createState() => _LessonDetailScreenState();
}

class _LessonDetailScreenState extends State<LessonDetailScreen> {
  // ...

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.lessonTitle),
      ),
      body: SingleChildScrollView(
        child: Column(
          children: [
            // Resumo da aula
            _buildSummarySection(),
            
            const SizedBox(height: 20),
            
            // ⭐ Novo: Widget de Quiz
            QuizGeneratorWidget(
              lessonId: widget.lessonId,
              lessonTitle: widget.lessonTitle,
              disciplineName: widget.disciplineName,
              onQuizGenerated: () {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('Quiz gerado com sucesso!'),
                    backgroundColor: Colors.green,
                  ),
                );
              },
            ),
            
            const SizedBox(height: 20),
            
            // Presença/Chamada
            _buildAttendanceSection(),
          ],
        ),
      ),
    );
  }
}
```

---

## 🎯 Fluxo de Interação

### Passo 1: Professor Vê o Widget

```
┌────────────────────────────────────┐
│ Detalhes da Aula                   │
├────────────────────────────────────┤
│ 📝 Normalização de BD              │
│ Turma: BD-101 | 2024.1             │
├────────────────────────────────────┤
│ 📊 Resumo                          │
│ [Resumo completo da aula...]       │
├────────────────────────────────────┤
│ ✨ Gerar Quiz                      │ ← NEW
│                                    │
│ Tipo: [Prática ▼]  Dif: [Mista ▼] │
│ Questões: ████░ (10)              │
│                                    │
│  [Gerar Quiz com IA]              │
├────────────────────────────────────┤
│ 📍 Chamada por QR Code             │
│  [Iniciar Chamada]                 │
└────────────────────────────────────┘
```

### Passo 2: Professor Clica "Gerar Quiz"

```
⏳ Aguardando... (5-30s)

Backend:
  ├─ Generate: Prompta LLM
  ├─ Validate: Detecta hallucinations
  └─ Filter: Valida grounding score
```

### Passo 3: Quiz Gerado com Sucesso

```
┌────────────────────────────────────┐
│ ✅ Quiz Gerado com Sucesso!        │
├────────────────────────────────────┤
│ Quiz: Normalização de BD           │
│ Questões geradas: 10               │
│                                    │
│ Compartilhe com seus alunos:       │
│                                    │
│ https://seu-dominio.com/education/ │
│ quiz/quiz-abc123/play             │
│                                    │
│ [Copiar Link]  [Abrir Quiz]       │
└────────────────────────────────────┘
```

### Passo 4: Aluno Recebe Link e Responde

**No Celular/Tablet:**
```
Browser → https://seu-dominio.com/education/quiz/quiz-abc123/play

┌─────────────────────────┐
│ MODO EDUCAÇÃO           │
│ Questão 1 de 10         │
│ ▓▓░░░░░░░░              │
├─────────────────────────┤
│ Qual é a 1NF?          │
│                         │
│ ○ Elimina multivalorado│
│ ○ Remove dependência   │
│ ○ Elim. dependência tr │
│ ○ Otimiza performance  │
│                         │
│ [PULAR]  [CONFIRMAR]   │
└─────────────────────────┘
```

### Passo 5: Professor Acompanha

```
Na interface Flutter:

┌────────────────────────────────────┐
│ Quiz: Normalização de BD           │
│ Status: 🟢 Ativo                   │
├────────────────────────────────────┤
│ Respondidas: 5/30 alunos          │
│                                    │
│ ■■■■■░░░░░░░░░░░ (16%)           │
│                                    │
│ 📊 Resultados em Tempo Real        │
│ ├─ Q1: 28 acertos, 2 erros        │
│ ├─ Q2: 25 acertos, 5 erros        │
│ └─ Q3: 23 acertos, 7 erros        │
│                                    │
│ [Ver Detalhes] [Fechar Quiz]      │
└────────────────────────────────────┘
```

---

## 💻 Código de Exemplo - Integração Completa

### 1. Service para API de Quiz

```dart
// lib/services/quiz_service.dart

import 'api_service.dart';

class QuizService {
  final ApiService _apiService = ApiService();

  // Gera novo quiz
  Future<QuizResponse> generateQuiz({
    required String lessonId,
    required String quizType,
    required int questionCount,
    required String difficulty,
  }) async {
    final response = await _apiService.post(
      '/education/quiz/generate',
      {
        'lesson_id': lessonId,
        'tipo_quiz': quizType,
        'quantidade_questoes': questionCount,
        'dificuldade': difficulty,
        'tipos_questao': ['multipla_escolha', 'verdadeiro_falso', 'aberta'],
      },
    );

    if (!response.success) {
      throw Exception(response.error);
    }

    return QuizResponse.fromJson(response.data);
  }

  // Obtém resultados do quiz
  Future<QuizResultsResponse> getQuizResults(String quizId) async {
    final response = await _apiService.get('/education/quiz/$quizId');
    
    if (!response.success) {
      throw Exception(response.error);
    }

    return QuizResultsResponse.fromJson(response.data);
  }

  // URL pública para compartilhar
  String getPublicQuizUrl(String quizId, String baseUrl) {
    return '$baseUrl/education/quiz/$quizId/play';
  }
}

// Modelos
class QuizResponse {
  final String quizId;
  final String titulo;
  final int totalQuestoes;
  final List<QuizQuestion> questoes;

  QuizResponse({
    required this.quizId,
    required this.titulo,
    required this.totalQuestoes,
    required this.questoes,
  });

  factory QuizResponse.fromJson(Map<String, dynamic> json) {
    return QuizResponse(
      quizId: json['quiz_id'] ?? '',
      titulo: json['titulo'] ?? '',
      totalQuestoes: json['total_questoes'] ?? 0,
      questoes: (json['questoes'] as List?)
          ?.map((q) => QuizQuestion.fromJson(q))
          .toList() ?? [],
    );
  }
}

class QuizQuestion {
  final String id;
  final String enunciado;
  final String tipo;
  final String? resposta;
  final double groundingScore;

  QuizQuestion({
    required this.id,
    required this.enunciado,
    required this.tipo,
    this.resposta,
    required this.groundingScore,
  });

  factory QuizQuestion.fromJson(Map<String, dynamic> json) {
    return QuizQuestion(
      id: json['id'] ?? '',
      enunciado: json['enunciado'] ?? '',
      tipo: json['tipo'] ?? '',
      resposta: json['resposta_correta'],
      groundingScore: (json['grounding_score'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class QuizResultsResponse {
  final String quizId;
  final int totalRespostas;
  final Map<String, dynamic> statistics;

  QuizResultsResponse({
    required this.quizId,
    required this.totalRespostas,
    required this.statistics,
  });

  factory QuizResultsResponse.fromJson(Map<String, dynamic> json) {
    return QuizResultsResponse(
      quizId: json['id'] ?? '',
      totalRespostas: json['total_questoes'] ?? 0,
      statistics: json,
    );
  }
}
```

### 2. Widget de Monitoramento em Tempo Real

```dart
// lib/widgets/quiz_monitoring_widget.dart

import 'package:flutter/material.dart';
import 'package:stream/stream.dart' as stream;
import '../services/quiz_service.dart';

class QuizMonitoringWidget extends StatefulWidget {
  final String quizId;

  const QuizMonitoringWidget({
    required this.quizId,
    Key? key,
  }) : super(key: key);

  @override
  State<QuizMonitoringWidget> createState() => _QuizMonitoringWidgetState();
}

class _QuizMonitoringWidgetState extends State<QuizMonitoringWidget> {
  final QuizService _quizService = QuizService();
  late Stream<QuizResultsResponse> _quizStream;

  @override
  void initState() {
    super.initState();
    // Atualiza a cada 2 segundos
    _quizStream = Stream.periodic(
      const Duration(seconds: 2),
      (_) => _quizService.getQuizResults(widget.quizId),
    ).asyncExpand((future) => Stream.fromFuture(future));
  }

  @override
  Widget build(BuildContext context) {
    return StreamBuilder<QuizResultsResponse>(
      stream: _quizStream,
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return Center(child: Text('Erro: ${snapshot.error}'));
        }

        if (!snapshot.hasData) {
          return const Center(child: CircularProgressIndicator());
        }

        final results = snapshot.data!;

        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Título
                Row(
                  children: [
                    const Icon(Icons.analytics, color: Colors.purple),
                    const SizedBox(width: 12),
                    Text(
                      'Monitoramento do Quiz',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const Spacer(),
                    Chip(
                      label: const Text('🟢 Ativo'),
                      backgroundColor: Colors.green[100],
                    ),
                  ],
                ),
                const SizedBox(height: 20),

                // Progresso
                _buildProgressSection(results),
                const SizedBox(height: 20),

                // Estatísticas por questão
                _buildQuestionStats(results),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildProgressSection(QuizResultsResponse results) {
    final totalRespostas = results.statistics['total_questoes'] ?? 0;
    final respostasRecebidas = results.statistics['respondidas'] ?? 0;
    final percentage = totalRespostas > 0
        ? (respostasRecebidas / totalRespostas * 100).toInt()
        : 0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              'Alunos que responderam',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            Text(
              '$respostasRecebidas/$totalRespostas ($percentage%)',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.bold,
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: LinearProgressIndicator(
            value: percentage / 100,
            minHeight: 12,
          ),
        ),
      ],
    );
  }

  Widget _buildQuestionStats(QuizResultsResponse results) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Desempenho por Questão',
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 12),
        // Aqui você mostraria cada questão com seu desempenho
        // Por enquanto é um placeholder
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: Colors.grey[100],
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(
            '📊 Dados em tempo real\n'
            'Q1: 28 acertos, 2 erros\n'
            'Q2: 25 acertos, 5 erros\n'
            'Q3: 23 acertos, 7 erros',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
      ],
    );
  }

  @override
  void dispose() {
    super.dispose();
  }
}
```

---

## 🔗 Integração Passo a Passo

### 1. Adicione na Tela de Aula

```dart
// Dentro de LessonDetailScreen > build() > body

// Depois do widget de resumo:
QuizGeneratorWidget(
  lessonId: lesson.id,
  lessonTitle: lesson.title,
  disciplineName: lesson.discipline,
  onQuizGenerated: _onQuizGenerated,
),
```

### 2. Adicione Monitoramento (Opcional)

```dart
// Se o professor quiser acompanhar em tempo real
if (_generatedQuizId != null)
  QuizMonitoringWidget(quizId: _generatedQuizId!),
```

### 3. Customizações

```dart
// Cores (tema purple)
final quizColor = Colors.purple[400];

// Animações
transition: SlideTransition()

// Compartilhamento
Share.share('Responda meu quiz: $quizUrl')
```

---

## 📊 Visualização no Flutter

### Layout da Tela de Aula

```
┌─────────────────────────────────────┐
│ ◀ Aula Detalhes                     │
├─────────────────────────────────────┤
│                                     │
│ 📝 Normalização de BD               │
│ Turma: BD-101 | 2024.1              │
│ Docente: Prof. Dr. X                │
│                                     │
├─ Resumo ─────────────────────────┤
│ A normalização de banco de dados... │
│ ...conceitos de chave estrangeira..│
│                                     │
├─ ✨ Gerar Quiz ──────────────────┤
│ [Tipo: Prática] [Dif: Mista]       │
│ Questões: ████░░░░░ (10)           │
│                                     │
│     [Gerar Quiz com IA]            │
│                                     │
│ ✅ Quiz Gerado!                    │
│ https://seu-dominio.com/quiz/...   │
│ [Copiar] [Abrir]                   │
│                                     │
│ 📊 Monitoramento                    │
│ Respondidas: 🟢 15/30 alunos       │
│ ■■■■■■░░░░░░░░░░░░ (50%)          │
│ Q1: 28 ✅, 2 ❌                    │
│ Q2: 25 ✅, 5 ❌                    │
│                                     │
├─ 📍 Chamada por QR ──────────────┤
│ [Iniciar Chamada]                  │
│                                     │
└─────────────────────────────────────┘
```

---

## 🚀 Próximas Features

- [ ] WebSocket para atualizar monitoramento em tempo real (sem polling)
- [ ] Gráfico de desempenho por questão
- [ ] Exportar resultados em PDF
- [ ] Notificação de alunos quando quiz fica pronto
- [ ] Análise de quais alunos erraram mais
- [ ] Regenerar quiz com feedback
- [ ] Integrar com notas da turma

---

Pronto para testar na interface! 🎉
