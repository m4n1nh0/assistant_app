import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../utils/theme.dart';

class AuthDialog extends StatefulWidget {
  final String assistantName;
  final bool needsSetup;
  final bool inviteRegistrationEnabled;
  final bool registrationRequiresToken;
  final bool registrationDeliveryConfigured;
  final String adminEmailHint;
  final String initialUsername;

  const AuthDialog({
    super.key,
    required this.assistantName,
    required this.needsSetup,
    this.inviteRegistrationEnabled = true,
    this.registrationRequiresToken = false,
    this.registrationDeliveryConfigured = false,
    this.adminEmailHint = '',
    this.initialUsername = '',
  });

  @override
  State<AuthDialog> createState() => _AuthDialogState();
}

class _AuthDialogState extends State<AuthDialog> {
  final _userCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _passCCtrl = TextEditingController();
  final _registrationTokenCtrl = TextEditingController();
  String _status = '';
  bool _statusIsError = true;
  bool _processing = false;
  bool _requestingToken = false;
  late bool _registerMode;

  bool get _isRegister => widget.needsSetup || _registerMode;
  bool get _needsToken =>
      _isRegister &&
      (widget.needsSetup ? widget.registrationRequiresToken : true);

  @override
  void initState() {
    super.initState();
    _userCtrl.text = widget.initialUsername;
    _registerMode = widget.needsSetup;
  }

  @override
  void dispose() {
    _userCtrl.dispose();
    _passCtrl.dispose();
    _passCCtrl.dispose();
    _registrationTokenCtrl.dispose();
    super.dispose();
  }

  void _setStatus(String msg, {bool isError = true}) => setState(() {
        _status = msg;
        _statusIsError = isError;
      });

  Future<void> _submit() async {
    if (_processing) return;
    final username = _userCtrl.text.trim();
    final password = _passCtrl.text;

    if (username.isEmpty || password.isEmpty) {
      _setStatus('Preencha usuário e senha.');
      return;
    }
    if (_isRegister && password != _passCCtrl.text) {
      _setStatus('As senhas não coincidem.');
      return;
    }
    if (_needsToken && _registrationTokenCtrl.text.trim().isEmpty) {
      _setStatus('Informe o token de convite enviado por email.');
      return;
    }

    setState(() => _processing = true);
    _setStatus('');
    try {
      final result = _isRegister
          ? await api.register(
              username,
              password,
              registrationToken: _registrationTokenCtrl.text.trim(),
            )
          : await api.login(username, password);
      if (!mounted) return;
      if (result.success) {
        Navigator.of(context).pop(username);
      } else {
        setState(() => _processing = false);
        _setStatus(
            result.message.isEmpty ? 'Falha ao autenticar.' : result.message);
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _processing = false);
      _setStatus('Erro ao conectar com o backend: $e');
    }
  }

  Future<void> _requestRegistrationToken() async {
    if (_requestingToken || !widget.registrationDeliveryConfigured) return;
    setState(() => _requestingToken = true);
    _setStatus('');
    try {
      final message = await api.requestRegistrationToken();
      if (!mounted) return;
      _setStatus(message, isError: false);
    } catch (e) {
      if (!mounted) return;
      _setStatus(e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) {
        setState(() => _requestingToken = false);
      }
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
                    _isRegister
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
                    onSubmitted: (_) => _isRegister ? null : _submit(),
                  ),
                  if (_isRegister) ...[
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
                  if (_needsToken) ...[
                    const SizedBox(height: 14),
                    Text(
                      widget.needsSetup
                          ? (widget.registrationDeliveryConfigured
                              ? 'Solicite o token enviado para '
                                  '${widget.adminEmailHint}.'
                              : 'O envio do token administrativo ainda não foi '
                                  'configurado no backend.')
                          : 'Use o token recebido no email de convite.',
                      style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 10,
                        color: AssistantTheme.textSecondary,
                      ),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 8),
                    if (widget.needsSetup) ...[
                      _AuthBtn(
                        icon: '✉',
                        label: _requestingToken
                            ? 'ENVIANDO...'
                            : 'ENVIAR TOKEN AO ADMIN',
                        color: AssistantTheme.c1,
                        onTap: _requestingToken ||
                                !widget.registrationDeliveryConfigured
                            ? null
                            : _requestRegistrationToken,
                      ),
                      const SizedBox(height: 10),
                    ],
                    TextField(
                      controller: _registrationTokenCtrl,
                      style: const TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 13,
                        color: AssistantTheme.textPrimary,
                      ),
                      decoration: const InputDecoration(
                        hintText: 'Token de convite',
                      ),
                      onSubmitted: (_) => _submit(),
                    ),
                  ],
                  const SizedBox(height: 16),
                  _AuthBtn(
                    icon: '›',
                    label: _processing
                        ? 'AGUARDE...'
                        : _isRegister
                            ? 'CRIAR CONTA'
                            : 'ENTRAR',
                    color: AssistantTheme.c3,
                    onTap: _processing ? null : _submit,
                  ),
                  if (!widget.needsSetup &&
                      widget.inviteRegistrationEnabled) ...[
                    const SizedBox(height: 8),
                    TextButton(
                      onPressed: _processing
                          ? null
                          : () => setState(() {
                                _registerMode = !_registerMode;
                                _status = '';
                              }),
                      child: Text(
                        _registerMode
                            ? 'JÁ TENHO CONTA'
                            : 'CRIAR CONTA COM CONVITE',
                        style: const TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 10,
                          color: AssistantTheme.c1,
                        ),
                      ),
                    ),
                  ],
                  if (_status.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text(
                      _status,
                      style: TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 11,
                        color: _statusIsError
                            ? AssistantTheme.danger
                            : AssistantTheme.c3,
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
