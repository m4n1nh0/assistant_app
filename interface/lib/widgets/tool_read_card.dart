/// Mostra, junto da resposta, o que o assistente leu do banco para responder.
///
/// Sem este card o dado só existia dentro do parágrafo do modelo, e o usuário
/// tinha duas opções ruins: acreditar no número ou ir conferir na mão. O card
/// traz as linhas como vieram do banco e um botão que abre a tela onde elas
/// moram, para a decisão continuar com quem manda.
library;

import 'package:flutter/material.dart';

import '../models/app_config.dart';
import '../utils/theme.dart';
import 'education_dialog.dart';

/// Quantas linhas aparecem antes de "ver na tela": o card acompanha a
/// resposta, não substitui a tela de gestão.
const _linhasVisiveis = 5;

class ToolReadCard extends StatelessWidget {
  final ToolReadResult result;

  const ToolReadCard({super.key, required this.result});

  @override
  Widget build(BuildContext context) {
    final visao = _VisaoDaLeitura.of(result.kind);
    final linhas = result.items.take(_linhasVisiveis).toList();
    final restantes = result.total - linhas.length;

    return Container(
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
      decoration: BoxDecoration(
        border: Border.all(color: AssistantTheme.c1.withOpacity(0.28)),
        borderRadius: BorderRadius.circular(3),
        color: AssistantTheme.c1.withOpacity(0.05),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(visao.icone, size: 13, color: AssistantTheme.c1),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  result.title.isEmpty ? visao.rotulo : result.title,
                  style: const TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 10,
                    color: AssistantTheme.c1,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (visao.destino != null)
                TextButton.icon(
                  onPressed: () => showDialog<void>(
                    context: context,
                    barrierDismissible: false,
                    useSafeArea: false,
                    builder: (_) => EducationDialog(startAt: visao.destino!),
                  ),
                  icon: const Icon(Icons.open_in_new, size: 13),
                  label: Text(
                    visao.acao,
                    style: const TextStyle(fontSize: 10),
                  ),
                  style: TextButton.styleFrom(
                    foregroundColor: AssistantTheme.c1,
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    minimumSize: const Size(0, 28),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                ),
            ],
          ),
          const SizedBox(height: 4),
          for (final linha in linhas)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: _Linha(
                titulo: visao.titulo(linha),
                detalhe: visao.detalhe(linha),
              ),
            ),
          if (restantes > 0)
            Text(
              '+$restantes no seu cadastro',
              style: TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 9,
                color: AssistantTheme.textPrimary.withOpacity(0.5),
              ),
            ),
          const SizedBox(height: 2),
          Text(
            'lido do seu cadastro',
            style: TextStyle(
              fontFamily: 'JetBrains Mono',
              fontSize: 9,
              color: AssistantTheme.textPrimary.withOpacity(0.4),
            ),
          ),
        ],
      ),
    );
  }
}

class _Linha extends StatelessWidget {
  final String titulo;
  final String detalhe;

  const _Linha({required this.titulo, required this.detalhe});

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '· ',
          style: TextStyle(
            fontSize: 11,
            color: AssistantTheme.textPrimary.withOpacity(0.5),
          ),
        ),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                titulo,
                style: const TextStyle(
                  fontSize: 11,
                  color: AssistantTheme.textPrimary,
                  height: 1.35,
                ),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              if (detalhe.isNotEmpty)
                Text(
                  detalhe,
                  style: TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 9,
                    color: AssistantTheme.textPrimary.withOpacity(0.55),
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
            ],
          ),
        ),
      ],
    );
  }
}

/// Como cada tipo de leitura vira linha na tela.
///
/// O envelope que vem do backend é um só para todos os tipos; o que muda é
/// qual campo é o assunto da linha e qual é o detalhe. Concentrar isso aqui
/// evita um card por domínio -- e um lugar novo para esquecer de atualizar.
class _VisaoDaLeitura {
  final IconData icone;
  final String rotulo;

  /// Aba do Modo Educação que mostra esses dados por inteiro.
  final String? destino;
  final String acao;
  final String Function(Map<String, dynamic>) titulo;
  final String Function(Map<String, dynamic>) detalhe;

  const _VisaoDaLeitura({
    required this.icone,
    required this.rotulo,
    required this.destino,
    required this.acao,
    required this.titulo,
    required this.detalhe,
  });

  static String _texto(Map<String, dynamic> item, List<String> campos) {
    for (final campo in campos) {
      final valor = item[campo]?.toString() ?? '';
      if (valor.isNotEmpty) return valor;
    }
    return '';
  }

  static String _juntar(List<String> partes) =>
      partes.where((parte) => parte.isNotEmpty).join(' · ');

  static _VisaoDaLeitura of(String kind) {
    switch (kind) {
      case 'question_bank':
        return _VisaoDaLeitura(
          icone: Icons.quiz_outlined,
          rotulo: 'Banco de questões',
          destino: 'quiz',
          acao: 'Abrir banco',
          titulo: (item) => _texto(item, ['enunciado']),
          detalhe: (item) => _juntar([
            _texto(item, ['dificuldade']),
            _texto(item, ['disciplina']),
            _texto(item, ['quiz']),
          ]),
        );
      case 'quiz':
        return _VisaoDaLeitura(
          icone: Icons.fact_check_outlined,
          rotulo: 'Quiz',
          destino: 'quiz',
          acao: 'Abrir quiz',
          titulo: (item) =>
              '${item['numero'] ?? ''}. ${_texto(item, ['enunciado'])}'.trim(),
          detalhe: (item) => _juntar([
            _texto(item, ['dificuldade']),
            'gabarito ${_texto(item, ['resposta_correta'])}',
          ]),
        );
      case 'quizzes':
        return _VisaoDaLeitura(
          icone: Icons.fact_check_outlined,
          rotulo: 'Quizzes',
          destino: 'quiz',
          acao: 'Abrir quizzes',
          titulo: (item) => _texto(item, ['titulo']),
          detalhe: (item) => _juntar([
            '${item['questoes'] ?? 0} questões',
            _texto(item, ['situacao']),
            _texto(item, ['disciplina']),
          ]),
        );
      case 'quiz_results':
        return _VisaoDaLeitura(
          icone: Icons.leaderboard_outlined,
          rotulo: 'Resultado do quiz',
          destino: 'quiz',
          acao: 'Abrir quiz',
          titulo: (item) => '${item['posicao'] ?? ''}. '
              '${_texto(item, ['aluno'])}',
          detalhe: (item) => '${item['pontos'] ?? 0} pts · '
              '${item['acertos'] ?? 0}/${item['respostas'] ?? 0} acertos',
        );
      case 'lessons':
        return _VisaoDaLeitura(
          icone: Icons.school_outlined,
          rotulo: 'Aulas gravadas',
          destino: 'lesson',
          acao: 'Abrir aulas',
          titulo: (item) => _texto(item, ['titulo', 'disciplina']),
          detalhe: (item) => _juntar([
            _texto(item, ['data']),
            _texto(item, ['disciplina']),
            _texto(item, ['turma']),
          ]),
        );
      case 'lesson':
        return _VisaoDaLeitura(
          icone: Icons.school_outlined,
          rotulo: 'Aula',
          destino: 'lesson',
          acao: 'Abrir aula',
          titulo: (item) => _texto(item, ['aluno']),
          detalhe: (item) => '${item['pontos'] ?? 0} ponto(s) · '
              '${_texto(item, ['motivo'])}',
        );
      case 'students':
        return _VisaoDaLeitura(
          icone: Icons.people_outline,
          rotulo: 'Alunos',
          destino: 'auto',
          acao: 'Abrir turmas',
          titulo: (item) => _texto(item, ['nome']),
          detalhe: (item) => _juntar([
            _texto(item, ['turma']),
            _texto(item, ['disciplina']),
          ]),
        );
      case 'classes':
        return _VisaoDaLeitura(
          icone: Icons.groups_outlined,
          rotulo: 'Turmas',
          destino: 'auto',
          acao: 'Abrir turmas',
          titulo: (item) => _juntar([
            _texto(item, ['codigo']),
            _texto(item, ['nome'])
          ]),
          detalhe: (item) => _juntar([
            _texto(item, ['disciplina']),
            _texto(item, ['semestre']),
          ]),
        );
      case 'disciplines':
        return _VisaoDaLeitura(
          icone: Icons.menu_book_outlined,
          rotulo: 'Disciplinas',
          destino: 'auto',
          acao: 'Abrir cadastro',
          titulo: (item) => _juntar([
            _texto(item, ['codigo']),
            _texto(item, ['nome'])
          ]),
          detalhe: (item) => _texto(item, ['semestre']),
        );
      case 'study_time':
        return _VisaoDaLeitura(
          icone: Icons.timer_outlined,
          rotulo: 'Tempo de estudo',
          destino: 'auto',
          acao: 'Abrir painel',
          titulo: (item) => 'Turma ${_texto(item, ['turma'])}',
          detalhe: (item) => '${item['horas'] ?? 0}h · '
              '${item['alunos'] ?? 0} registro(s)',
        );
      default:
        // Ferramenta nova cujo card ainda nao foi desenhado: a leitura aparece
        // assim mesmo, sem botao. Some-la em silencio seria pior -- o usuario
        // teria o dado na resposta e nenhuma forma de confirmar de onde veio.
        return _VisaoDaLeitura(
          icone: Icons.storage_outlined,
          rotulo: 'Consulta ao cadastro',
          destino: null,
          acao: '',
          titulo: (item) => _texto(item, [
            'titulo',
            'nome',
            'enunciado',
            'aluno',
          ]),
          detalhe: (item) => '',
        );
    }
  }
}
