import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../utils/theme.dart';

class AuthDialog extends StatefulWidget {
  final String assistantName;
  final bool needsSetup;
  final String initialUsername;

  const AuthDialog({
    super.key,
    required this.assistantName,
    required this.needsSetup,
    this.initialUsername = '',
  });

  @override
  State<AuthDialog> createState() => _AuthDialogState();
}

class _AuthDialogState extends State<AuthDialog> {
  final _userCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _passCCtrl = TextEditingController();
  String _status = '';
  bool _processing = false;

  @override
  void initState() {
    super.initState();
    _userCtrl.text = widget.initialUsername;
  }

  @override
  void dispose() {
    _userCtrl.dispose();
    _passCtrl.dispose();
    _passCCtrl.dispose();
    super.dispose();
  }

  void _setStatus(String msg) => setState(() => _status = msg);

  Future<void> _submit() async {
    if (_processing) return;
    final username = _userCtrl.text.trim();
    final password = _passCtrl.text;

    if (username.isEmpty || password.isEmpty) {
      _setStatus('Preencha usuário e senha.');
      return;
    }
    if (widget.needsSetup && password != _passCCtrl.text) {
      _setStatus('As senhas não coincidem.');
      return;
    }

    setState(() => _processing = true);
    _setStatus('');
    try {
      final result = widget.needsSetup
          ? await api.register(username, password)
          : await api.login(username, password);
      if (!mounted) return;
      if (result.success) {
        Navigator.of(context).pop(username);
      } else {
        setState(() => _processing = false);
        _setStatus(result.message.isEmpty
            ? 'Falha ao autenticar.'
            : result.message);
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _processing = false);
      _setStatus('Erro ao conectar com o backend: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      backgroundColor: AssistantTheme.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
      child: Container(
        width: 400,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: AssistantTheme.border2),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              height: 2,
              decoration: const BoxDecoration(
                borderRadius: BorderRadius.vertical(top: Radius.circular(6)),
                gradient: LinearGradient(colors: [
                  AssistantTheme.c1,
                  AssistantTheme.c2,
                  AssistantTheme.c3
                ]),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(28),
              child: Column(
                children: [
                  Text(
                    '${widget.assistantName} — ACESSO',
                    style: const TextStyle(
                      fontFamily: 'Rajdhani',
                      fontSize: 20,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 5,
                      color: AssistantTheme.c1,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    widget.needsSetup
                        ? 'Crie a conta de acesso ao assistente'
                        : 'Entre com usuário e senha para continuar',
                    style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 11,
                        color: AssistantTheme.textMuted),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 24),
                  TextField(
                    controller: _userCtrl,
                    autofocus: true,
                    style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 13,
                        color: AssistantTheme.textPrimary),
                    decoration: const InputDecoration(hintText: 'Usuário'),
                    onSubmitted: (_) => _submit(),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: _passCtrl,
                    obscureText: true,
                    style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 13,
                        color: AssistantTheme.textPrimary),
                    decoration: const InputDecoration(hintText: 'Senha'),
                    onSubmitted: (_) => widget.needsSetup ? null : _submit(),
                  ),
                  if (widget.needsSetup) ...[
                    const SizedBox(height: 10),
                    TextField(
                      controller: _passCCtrl,
                      obscureText: true,
                      style: const TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 13,
                          color: AssistantTheme.textPrimary),
                      decoration:
                          const InputDecoration(hintText: 'Confirmar senha'),
                      onSubmitted: (_) => _submit(),
                    ),
                  ],
                  const SizedBox(height: 16),
                  _AuthBtn(
                    icon: '›',
                    label: _processing
                        ? 'AGUARDE...'
                        : widget.needsSetup
                            ? 'CRIAR CONTA'
                            : 'ENTRAR',
                    color: AssistantTheme.c3,
                    onTap: _processing ? null : _submit,
                  ),
                  if (_status.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text(
                      _status,
                      style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 11,
                        color: AssistantTheme.danger,
                      ),
                      textAlign: TextAlign.center,
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AuthBtn extends StatefulWidget {
  final String icon;
  final String label;
  final Color color;
  final VoidCallback? onTap;

  const _AuthBtn(
      {required this.icon,
      required this.label,
      required this.color,
      this.onTap});

  @override
  State<_AuthBtn> createState() => _AuthBtnState();
}

class _AuthBtnState extends State<_AuthBtn> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) => MouseRegion(
        onEnter: (_) => setState(() => _hovered = true),
        onExit: (_) => setState(() => _hovered = false),
        child: GestureDetector(
          onTap: widget.onTap,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 150),
            width: double.infinity,
            padding: const EdgeInsets.symmetric(vertical: 13),
            decoration: BoxDecoration(
              border: Border.all(color: widget.color.withOpacity(0.4)),
              borderRadius: BorderRadius.circular(3),
              color: (_hovered && widget.onTap != null)
                  ? widget.color.withOpacity(0.1)
                  : Colors.transparent,
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(widget.icon, style: const TextStyle(fontSize: 16)),
                const SizedBox(width: 10),
                Text(
                  widget.label,
                  style: TextStyle(
                    fontFamily: 'Rajdhani',
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 3,
                    color: widget.onTap == null
                        ? widget.color.withOpacity(0.5)
                        : widget.color,
                  ),
                ),
              ],
            ),
          ),
        ),
      );
}
