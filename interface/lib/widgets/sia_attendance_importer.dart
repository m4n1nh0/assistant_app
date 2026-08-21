import 'package:flutter/material.dart';
import '../services/api_service.dart';

/// Widget para importar presença do SIA Estácio
class SiaAttendanceImporter extends StatefulWidget {
  final String? lessonId; // Opcional - se vazio, pergunta qual aula
  final VoidCallback? onImported;

  const SiaAttendanceImporter({
    this.lessonId,
    this.onImported,
    super.key,
  });

  @override
  State<SiaAttendanceImporter> createState() => _SiaAttendanceImporterState();
}

class _SiaAttendanceImporterState extends State<SiaAttendanceImporter> {
  final ApiService _apiService = ApiService();
  final _cookiesCtrl = TextEditingController();

  Map<String, String>? _cookies;
  List<dynamic>? _periodos;
  String? _selectedPeriodo;
  List<dynamic>? _turmas;
  String? _selectedTurma;
  Map<String, dynamic>? _attendancePage;
  List<bool>? _selectedStudents;

  bool _loading = false;
  String? _error;

  @override
  void dispose() {
    _cookiesCtrl.dispose();
    super.dispose();
  }

  Future<void> _testSession() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final cookies = _parseCookies(_cookiesCtrl.text);
      final response = await _apiService.post(
        '/education/sia/test-session',
        body: {'cookies': cookies},
      );

      if (response.success && response.data['valid'] == true) {
        setState(() => _cookies = cookies);
        _loadPeriodos();
      } else {
        setState(() => _error = 'Sessão inválida. Tente fazer login novamente.');
      }
    } catch (e) {
      setState(() => _error = 'Erro ao testar sessão: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadPeriodos() async {
    if (_cookies == null) return;

    setState(() => _loading = true);

    try {
      final response = await _apiService.post(
        '/education/sia/periodos',
        body: {'cookies': _cookies},
      );

      if (response.success) {
        setState(() {
          _periodos = (response.data as List<dynamic>?) ?? [];
          _selectedPeriodo = null;
        });
      } else {
        setState(() => _error = 'Erro ao carregar períodos');
      }
    } catch (e) {
      setState(() => _error = 'Erro ao carregar períodos: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadTurmas() async {
    if (_cookies == null || _selectedPeriodo == null) return;

    setState(() => _loading = true);

    try {
      final response = await _apiService.post(
        '/education/sia/turmas',
        body: {
          'cookies': _cookies,
          'periodo_id': _selectedPeriodo,
        },
      );

      if (response.success) {
        setState(() {
          _turmas = (response.data as List<dynamic>?) ?? [];
          _selectedTurma = null;
        });
      } else {
        setState(() => _error = 'Erro ao carregar turmas');
      }
    } catch (e) {
      setState(() => _error = 'Erro ao carregar turmas: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadAttendance() async {
    if (_cookies == null || _selectedPeriodo == null || _selectedTurma == null) {
      return;
    }

    setState(() => _loading = true);

    try {
      final response = await _apiService.post(
        '/education/sia/attendance',
        body: {
          'cookies': _cookies,
          'turma_id': _selectedTurma,
          'periodo_id': _selectedPeriodo,
        },
      );

      if (response.success) {
        final page = response.data;
        setState(() {
          _attendancePage = page;
          _selectedStudents = List.filled(page['students']?.length ?? 0, false);
          // Pré-seleciona alunos que já estão marcados como presentes
          for (int i = 0; i < (page['students']?.length ?? 0); i++) {
            _selectedStudents![i] = page['students'][i]['presente'] == true;
          }
        });
      } else {
        setState(() => _error = 'Erro ao carregar presença');
      }
    } catch (e) {
      setState(() => _error = 'Erro ao carregar presença: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _importAttendance() async {
    if (_selectedStudents == null || _attendancePage == null) return;

    setState(() => _loading = true);

    try {
      if (widget.lessonId == null || widget.lessonId!.isEmpty) {
        setState(() => _error = 'Nenhuma aula selecionada. Por favor, selecione uma aula primeira.');
        return;
      }

      final students = _attendancePage!['students'] as List;
      final toImport = [];

      for (int i = 0; i < students.length; i++) {
        toImport.add({
          'matricula': students[i]['matricula'],
          'nome': students[i]['nome'],
          'presente': _selectedStudents![i],
        });
      }

      final response = await _apiService.post(
        '/education/sia/import-attendance',
        body: {
          'lesson_id': widget.lessonId!,
          'students_data': toImport,
        },
      );

      if (response.success) {
        widget.onImported?.call();
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('${toImport.length} alunos importados!'),
              backgroundColor: Colors.green,
            ),
          );
          Navigator.pop(context);
        }
      } else {
        setState(() => _error = 'Erro ao importar presença');
      }
    } catch (e) {
      setState(() => _error = 'Erro ao importar: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Map<String, String> _parseCookies(String cookieString) {
    final cookies = <String, String>{};
    for (final cookie in cookieString.split(';')) {
      final parts = cookie.trim().split('=');
      if (parts.length == 2) {
        cookies[parts[0]] = parts[1];
      }
    }
    return cookies;
  }

  @override
  Widget build(BuildContext context) {
    // Se lessonId é nulo, mostra tela de seleção de aula
    if (widget.lessonId == null || widget.lessonId!.isEmpty) {
      return Dialog(
        child: Container(
          constraints: const BoxConstraints(maxWidth: 600, maxHeight: 500),
          child: Column(
            children: [
              // Header
              Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: [Colors.blue[400]!, Colors.blue[600]!],
                  ),
                  borderRadius: const BorderRadius.only(
                    topLeft: Radius.circular(8),
                    topRight: Radius.circular(8),
                  ),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.cloud_download, color: Colors.white),
                    const SizedBox(width: 12),
                    const Expanded(
                      child: Text(
                        'Importar Presença do SIA 📚',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                    IconButton(
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.close, color: Colors.white),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.info_outline, size: 48, color: Colors.blue),
                        const SizedBox(height: 16),
                        const Text(
                          'Nenhuma aula selecionada',
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        const SizedBox(height: 8),
                        const Text(
                          'Para importar presença, você precisa primeiro abrir uma aula na aba "GRAVAR AULA" e depois voltar para importar.',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            fontSize: 12,
                            color: Colors.grey,
                          ),
                        ),
                        const SizedBox(height: 24),
                        ElevatedButton(
                          onPressed: () => Navigator.pop(context),
                          child: const Text('OK'),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      );
    }

    // Fluxo normal com lessonId fornecido
    return Dialog(
      child: Container(
        constraints: const BoxConstraints(maxWidth: 600, maxHeight: 800),
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Header
              Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: [Colors.blue[400]!, Colors.blue[600]!],
                  ),
                  borderRadius: const BorderRadius.only(
                    topLeft: Radius.circular(8),
                    topRight: Radius.circular(8),
                  ),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.cloud_download, color: Colors.white),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            'Importar Presença do SIA 📚',
                            style: TextStyle(
                              color: Colors.white,
                              fontSize: 18,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                          const Text(
                            'Estácio - Pauta Eletrônica',
                            style: TextStyle(
                              color: Colors.white70,
                              fontSize: 12,
                            ),
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.close, color: Colors.white),
                    ),
                  ],
                ),
              ),

              Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Passo 1: Cola cookies
                    if (_cookies == null) ...[
                      Text(
                        'Passo 1: Autenticação',
                        style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        '1. Faça login em https://sia.estacio.br\n'
                        '2. Abra DevTools (F12) → Network\n'
                        '3. Copie o header "Cookie:" completo\n'
                        '4. Cole abaixo',
                        style: TextStyle(fontSize: 12, color: Colors.grey),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: _cookiesCtrl,
                        maxLines: 4,
                        decoration: InputDecoration(
                          labelText: 'Cookies da Sessão',
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(8),
                          ),
                          hintText: 'JSESSIONID=...; Path=...',
                        ),
                      ),
                      const SizedBox(height: 12),
                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton.icon(
                          onPressed: _loading ? null : _testSession,
                          icon: _loading
                              ? const SizedBox(
                                  width: 16,
                                  height: 16,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                              : const Icon(Icons.login),
                          label: const Text('Testar Sessão'),
                          style: ElevatedButton.styleFrom(
                            padding: const EdgeInsets.symmetric(vertical: 12),
                          ),
                        ),
                      ),
                    ] else ...[
                      // Passo 2: Seleciona período
                      Text(
                        'Passo 2: Período Acadêmico',
                        style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 12),
                      if (_periodos == null)
                        const CircularProgressIndicator()
                      else
                        DropdownButtonFormField<String>(
                          value: _selectedPeriodo,
                          decoration: InputDecoration(
                            labelText: 'Período',
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(8),
                            ),
                          ),
                          items: [
                            for (final p in _periodos!)
                              DropdownMenuItem(
                                value: p['value'],
                                child: Text(p['label']),
                              ),
                          ],
                          onChanged: (value) {
                            setState(() => _selectedPeriodo = value);
                            if (value != null) _loadTurmas();
                          },
                        ),
                      const SizedBox(height: 20),

                      // Passo 3: Seleciona turma
                      if (_selectedPeriodo != null) ...[
                        Text(
                          'Passo 3: Turma',
                          style:
                              Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        const SizedBox(height: 12),
                        if (_turmas == null)
                          const CircularProgressIndicator()
                        else
                          DropdownButtonFormField<String>(
                            value: _selectedTurma,
                            decoration: InputDecoration(
                              labelText: 'Turma',
                              border: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(8),
                              ),
                            ),
                            items: [
                              for (final t in _turmas!)
                                DropdownMenuItem(
                                  value: t['num_seq_turma'],
                                  child: Text(
                                    '${t['disciplina']} - ${t['turma']} (${t['turno']})',
                                  ),
                                ),
                            ],
                            onChanged: (value) {
                              setState(() => _selectedTurma = value);
                              if (value != null) _loadAttendance();
                            },
                          ),
                        const SizedBox(height: 20),
                      ],

                      // Passo 4: Presença
                      if (_attendancePage != null) ...[
                        Text(
                          'Passo 4: Alunos Presentes',
                          style:
                              Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          '${_attendancePage!['disciplina']} - Turma ${_attendancePage!['turma']}',
                          style: const TextStyle(
                            fontSize: 12,
                            color: Colors.grey,
                          ),
                        ),
                        const SizedBox(height: 12),
                        Container(
                          height: 300,
                          decoration: BoxDecoration(
                            border: Border.all(color: Colors.grey[300]!),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: ListView.separated(
                            itemCount:
                                _attendancePage!['students']?.length ?? 0,
                            separatorBuilder: (_, __) =>
                                const Divider(height: 1),
                            itemBuilder: (_, index) {
                              final student =
                                  _attendancePage!['students'][index];
                              return CheckboxListTile(
                                title: Text(student['nome']),
                                subtitle: Text(student['matricula']),
                                value: _selectedStudents![index],
                                onChanged: (value) {
                                  setState(() {
                                    _selectedStudents![index] = value ?? false;
                                  });
                                },
                              );
                            },
                          ),
                        ),
                        const SizedBox(height: 12),
                        SizedBox(
                          width: double.infinity,
                          child: ElevatedButton.icon(
                            onPressed: _loading ? null : _importAttendance,
                            icon: _loading
                                ? const SizedBox(
                                    width: 16,
                                    height: 16,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const Icon(Icons.cloud_upload),
                            label: const Text('Importar Presença'),
                            style: ElevatedButton.styleFrom(
                              padding:
                                  const EdgeInsets.symmetric(vertical: 12),
                              backgroundColor: Colors.blue,
                            ),
                          ),
                        ),
                      ],
                    ],

                    // Erro
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.red[100],
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: Colors.red),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.error, color: Colors.red),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                _error!,
                                style:
                                    TextStyle(color: Colors.red[900]),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
