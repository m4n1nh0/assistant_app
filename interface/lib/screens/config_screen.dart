import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/app_provider.dart';
import '../services/storage_service.dart';
import '../services/api_service.dart';
import '../services/external_launcher_service.dart';
import '../services/neural_tts_service.dart';
import '../services/neural_audio_player.dart';
import '../services/notification_service.dart';
import '../models/app_config.dart';
import '../utils/theme.dart';
import '../widgets/title_bar.dart';

class ConfigScreen extends ConsumerStatefulWidget {
  const ConfigScreen({super.key});

  @override
  ConsumerState<ConfigScreen> createState() => _ConfigScreenState();
}

class _ConfigScreenState extends ConsumerState<ConfigScreen> {
  int _tab = 0;
  late AppConfig _draft;

  final _nameCtrl = TextEditingController();
  final _userCtrl = TextEditingController();
  final _personCtrl = TextEditingController();
  final _curPassCtrl = TextEditingController();
  final _newPassCtrl = TextEditingController();
  final _newPassCCtrl = TextEditingController();
  final _inviteEmailCtrl = TextEditingController();
  final _tgTokenCtrl = TextEditingController();
  final _tgChatCtrl = TextEditingController();
  final _waNumCtrl = TextEditingController();
  final _waTokCtrl = TextEditingController();
  final _reminderMinutesCtrl = TextEditingController();
  final _gcalClientCtrl = TextEditingController();
  final _gcalSecretCtrl = TextEditingController();
  final _msClientCtrl = TextEditingController();
  final _msSecretCtrl = TextEditingController();
  final _msTenantCtrl = TextEditingController();
  final _backendUrlCtrl = TextEditingController();
  bool _backendTestBusy = false;
  final _voicePreviewPlayer = NeuralAudioPlayer();
  bool _voiceTestBusy = false;
  Map<String, List<CalendarAccount>> _calendarAccounts = const {
    'google': [],
    'microsoft': [],
  };
  bool _calendarBusy = false;
  CurrentAccount? _account;
  List<AdminUser> _users = const [];
  bool _inviteBusy = false;

  @override
  void initState() {
    super.initState();
    _draft = ref.read(configProvider);
    _populate();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadNotificationConfig();
      _loadCalendarAccounts();
      _loadAccountManagement();
    });
  }

  void _populate() {
    _nameCtrl.text = _draft.assistantName;
    _userCtrl.text = _draft.userName;
    _personCtrl.text = _draft.personality;
    _populateNotifFields();
    _gcalClientCtrl.text = _draft.calendar.gcalClientId;
    _gcalSecretCtrl.text = _draft.calendar.gcalClientSecret;
    _msClientCtrl.text = _draft.calendar.msClientId;
    _msSecretCtrl.text = _draft.calendar.msClientSecret;
    _msTenantCtrl.text = _draft.calendar.msTenantId.isEmpty
        ? 'common'
        : _draft.calendar.msTenantId;
    _backendUrlCtrl.text = _draft.backendUrl;
  }

  void _populateNotifFields() {
    _tgTokenCtrl.text = _draft.notif.tgToken;
    _tgChatCtrl.text = _draft.notif.tgChatId;
    _waNumCtrl.text = _draft.notif.waNumber;
    _waTokCtrl.text = _draft.notif.waToken;
    _reminderMinutesCtrl.text = '${_draft.notif.reminderMinutes}';
  }

  Future<void> _loadNotificationConfig() async {
    try {
      final notif = await api.getNotificationConfig();
      if (!mounted) return;
      setState(() {
        _draft.notif = notif;
        _populateNotifFields();
      });
    } catch (_) {}
  }

  Future<void> _loadAccountManagement() async {
    final account = await api.currentAccount();
    if (!mounted) return;
    setState(() => _account = account);
    if (account?.isAdmin != true) return;
    try {
      final users = await api.listUsers();
      if (mounted) setState(() => _users = users);
    } catch (_) {}
  }

  Future<void> _inviteUser() async {
    final email = _inviteEmailCtrl.text.trim();
    if (email.isEmpty || _inviteBusy) {
      _showSnack('Informe o email do novo usuario.');
      return;
    }
    setState(() => _inviteBusy = true);
    try {
      final message = await api.inviteUser(email);
      _inviteEmailCtrl.clear();
      _showSnack(message);
    } catch (e) {
      _showSnack(e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _inviteBusy = false);
    }
  }

  Future<void> _save() async {
    _draft.assistantName =
        _nameCtrl.text.trim().isEmpty ? 'Assistente' : _nameCtrl.text.trim();
    _draft.userName = _userCtrl.text.trim();
    _draft.personality = _personCtrl.text.trim();

    _draft.notif.tgToken = _tgTokenCtrl.text.trim();
    _draft.notif.tgChatId = _tgChatCtrl.text.trim();
    _draft.notif.tgEnabled = _draft.notif.tgToken.isNotEmpty;
    _draft.notif.waNumber = _waNumCtrl.text.trim();
    _draft.notif.waToken = _waTokCtrl.text.trim();
    _draft.notif.waEnabled = _draft.notif.waNumber.isNotEmpty;
    final reminderMinutes = int.tryParse(_reminderMinutesCtrl.text.trim());
    if (reminderMinutes == null ||
        reminderMinutes < 5 ||
        reminderMinutes > 1440) {
      _showSnack('A antecedencia deve ficar entre 5 e 1440 minutos.');
      return;
    }
    _draft.notif.reminderMinutes = reminderMinutes;

    try {
      _draft.notif = await api.saveNotificationConfig(_draft.notif);
      _populateNotifFields();
    } catch (e) {
      _showSnack('Erro ao salvar notificacoes no backend: $e');
      return;
    }

    final gcalClientId = _gcalClientCtrl.text.trim();
    final gcalClientSecret = _gcalSecretCtrl.text.trim();
    final msClientId = _msClientCtrl.text.trim();
    final msClientSecret = _msSecretCtrl.text.trim();
    final msTenantId = _msTenantCtrl.text.trim().isEmpty
        ? 'common'
        : _msTenantCtrl.text.trim();

    if ((gcalClientId.isEmpty) != (gcalClientSecret.isEmpty)) {
      _showSnack('Preencha Client ID e Client Secret do Google.');
      return;
    }
    if ((msClientId.isEmpty) != (msClientSecret.isEmpty)) {
      _showSnack('Preencha Client ID e Client Secret da Microsoft.');
      return;
    }

    try {
      if (gcalClientId.isNotEmpty && gcalClientSecret.isNotEmpty) {
        await api.saveGoogleOAuthApp(
          clientId: gcalClientId,
          clientSecret: gcalClientSecret,
        );
      }
      if (msClientId.isNotEmpty && msClientSecret.isNotEmpty) {
        await api.saveMicrosoftOAuthApp(
          clientId: msClientId,
          clientSecret: msClientSecret,
          tenantId: msTenantId,
        );
      }
    } catch (e) {
      _showSnack('Erro ao salvar credenciais da agenda: $e');
      return;
    }

    try {
      _calendarAccounts = await api.listCalendarAccounts();
    } catch (_) {}

    _draft.calendar.gcalClientId = gcalClientId;
    _draft.calendar.gcalClientSecret = gcalClientSecret;
    _draft.calendar.gcalRefreshToken = '';
    _draft.calendar.gcalEnabled =
        _calendarAccounts['google']?.any((item) => item.connected) == true;
    _draft.calendar.msClientId = msClientId;
    _draft.calendar.msClientSecret = msClientSecret;
    _draft.calendar.msTenantId = msTenantId;
    _draft.calendar.msRefreshToken = '';
    _draft.calendar.msEnabled =
        _calendarAccounts['microsoft']?.any((item) => item.connected) == true;

    await StorageService.saveConfig(_draft);
    ref.read(configProvider.notifier).replaceInMemory(_draft);

    if (mounted) {
      ref.read(isAuthenticatedProvider.notifier).state = false;
      Navigator.pushReplacementNamed(context, '/main');
    }
  }

  Future<void> _applyBackendUrl() async {
    final typed = _backendUrlCtrl.text.trim();
    if (typed.isEmpty) {
      _showSnack('Informe o endereço do backend.');
      return;
    }
    setState(() => _backendTestBusy = true);
    api.configure(typed);
    _draft.backendUrl = api.baseUrl;
    _backendUrlCtrl.text = api.baseUrl;
    await StorageService.saveConfig(_draft);
    ref.read(configProvider.notifier).replaceInMemory(_draft);
    try {
      await api.health().timeout(const Duration(seconds: 8));
      _showSnack('Conectado em ${api.baseUrl}');
    } catch (e) {
      _showSnack('Backend salvo, mas não respondeu em ${api.baseUrl}: $e');
    } finally {
      if (mounted) setState(() => _backendTestBusy = false);
    }
  }

  Future<void> _testVoice() async {
    setState(() => _voiceTestBusy = true);
    try {
      final bytes = await NeuralTtsService.synthesize(
        'Oi! Sou a ${_nameCtrl.text.trim().isEmpty ? 'assistente' : _nameCtrl.text.trim()}. '
        'E assim que eu vou falar com voce.',
        voice: NeuralTtsService.resolveVoice(
            _draft.ttsVoice, _draft.assistantGender),
        ratePercent: _draft.ttsRatePercent,
        pitchHz: _draft.ttsPitchHz,
      ).timeout(const Duration(seconds: 15));
      if (bytes.isEmpty) {
        _showSnack('Nao foi possivel gerar a voz.');
        return;
      }
      await _voicePreviewPlayer.stop();
      await _voicePreviewPlayer.play(bytes);
    } catch (e) {
      _showSnack('Falha ao gerar a voz (precisa de internet): $e');
    } finally {
      if (mounted) setState(() => _voiceTestBusy = false);
    }
  }

  Future<void> _loadCalendarAccounts() async {
    try {
      final accounts = await api.listCalendarAccounts();
      if (!mounted) return;
      setState(() => _calendarAccounts = accounts);
    } catch (_) {}
  }

  Future<void> _openGoogleAuthorization() async {
    await _runCalendarAction(() async {
      final clientId = _gcalClientCtrl.text.trim();
      final clientSecret = _gcalSecretCtrl.text.trim();
      if ((clientId.isEmpty) != (clientSecret.isEmpty)) {
        throw Exception('preencha Client ID e Client Secret do Google');
      }

      final result = clientId.isNotEmpty
          ? await api.connectGoogleCalendar(
              clientId: clientId,
              clientSecret: clientSecret,
            )
          : await api.startGoogleCalendarAuth();
      if (result.authUrl.isEmpty || result.accountId.isEmpty) {
        throw Exception('backend nao retornou a URL de autorizacao Google');
      }
      await ExternalLauncherService.openUrl(result.authUrl);
      _showSnack(
          'Autorize no navegador. Vou detectar a conexao automaticamente.');
      final connected = await _waitForCalendarConnection(
        provider: 'google',
        accountId: result.accountId,
      );
      if (connected) {
        _showSnack('Conta Google conectada automaticamente.');
      } else {
        _showSnack('Autorizacao aberta. A conta aparece aqui ao concluir.');
      }
    });
  }

  Future<void> _openMicrosoftAuthorization() async {
    await _runCalendarAction(() async {
      final clientId = _msClientCtrl.text.trim();
      final clientSecret = _msSecretCtrl.text.trim();
      final tenantId = _msTenantCtrl.text.trim().isEmpty
          ? 'common'
          : _msTenantCtrl.text.trim();
      if ((clientId.isEmpty) != (clientSecret.isEmpty)) {
        throw Exception('preencha Client ID e Client Secret da Microsoft');
      }

      final result = clientId.isNotEmpty
          ? await api.connectMicrosoftCalendar(
              clientId: clientId,
              clientSecret: clientSecret,
              tenantId: tenantId,
            )
          : await api.startMicrosoftCalendarAuth();
      if (result.authUrl.isEmpty || result.accountId.isEmpty) {
        throw Exception('backend nao retornou a URL de autorizacao Microsoft');
      }
      await ExternalLauncherService.openUrl(result.authUrl);
      _showSnack(
          'Autorize no navegador. Vou detectar a conexao automaticamente.');
      final connected = await _waitForCalendarConnection(
        provider: 'microsoft',
        accountId: result.accountId,
      );
      if (connected) {
        _showSnack('Conta Microsoft conectada automaticamente.');
      } else {
        _showSnack('Autorizacao aberta. A conta aparece aqui ao concluir.');
      }
    });
  }

  Future<void> _disconnectCalendarAccount(CalendarAccount account) async {
    await _runCalendarAction(() async {
      await api.disconnectCalendarAccount(
        provider: account.provider,
        accountId: account.id,
      );
      await _loadCalendarAccounts();
      _showSnack('Agenda removida: ${account.label}');
    });
  }

  Future<void> _runCalendarAction(Future<void> Function() action) async {
    if (_calendarBusy) return;
    setState(() => _calendarBusy = true);
    try {
      await action();
    } catch (e) {
      _showSnack('Erro na agenda: $e');
    } finally {
      if (mounted) setState(() => _calendarBusy = false);
    }
  }

  Future<bool> _waitForCalendarConnection({
    required String provider,
    required String accountId,
  }) async {
    for (var i = 0; i < 45; i++) {
      await Future.delayed(const Duration(seconds: 2));
      await _loadCalendarAccounts();
      final accounts = _calendarAccounts[provider] ?? const [];
      final connected = accounts.any(
        (account) => account.id == accountId && account.connected,
      );
      if (connected) return true;
    }
    return false;
  }

  @override
  Widget build(BuildContext context) {
    final tabs = [
      'IDENTIDADE',
      'AUTENTICAÇÃO',
      'NOTIFICAÇÕES',
      'AGENDAS',
      'SISTEMA'
    ];

    return Scaffold(
      backgroundColor: AssistantTheme.bg,
      body: Column(
        children: [
          const AssistantTitleBar(),
          Expanded(
            child: Row(
              children: [
                Container(
                  width: 180,
                  color: const Color(0xFF090C13),
                  child: Column(
                    children: [
                      const SizedBox(height: 24),
                      ...List.generate(
                          tabs.length,
                          (i) => _TabBtn(
                                label: tabs[i],
                                active: _tab == i,
                                onTap: () => setState(() => _tab = i),
                              )),
                      const Spacer(),
                      Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          children: [
                            _SaveBtn(onTap: _save),
                            const SizedBox(height: 8),
                            if (Navigator.canPop(context))
                              _CancelBtn(onTap: () => Navigator.pop(context)),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                Expanded(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.all(32),
                    child: [
                      _buildIdentity(),
                      _buildAuth(),
                      _buildNotif(),
                      _buildCalendar2(),
                      _buildSystem(),
                    ][_tab],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildIdentity() => _TabContent(title: 'IDENTIDADE', children: [
        _Field('NOME DO APP', _nameCtrl, hint: 'Ex: MAX, VERA, NEXUS, KAMI...'),
        _Field('SEU NOME', _userCtrl, hint: 'Como você prefere ser chamado'),
        _Field('PERFIL DE ATENDIMENTO', _personCtrl,
            hint: 'Descreva o tom, foco e preferências de resposta...',
            maxLines: 5),
        _Label('SEXO DA ASSISTENTE'),
        _Dropdown(
          value: _draft.assistantGender,
          items: const {
            'f': 'Feminino',
            'm': 'Masculino',
          },
          onChanged: (v) => setState(() => _draft.assistantGender = v!),
        ),
        const SizedBox(height: 12),
        _Label('IDIOMA'),
        _Dropdown(
          value: _draft.language,
          items: const {
            'pt-BR': 'Português BR',
            'en-US': 'English US',
            'es-ES': 'Español'
          },
          onChanged: (v) => setState(() => _draft.language = v!),
        ),
        const SizedBox(height: 12),
        _Label('MODO DE RESPOSTA PADRÃO'),
        _Dropdown(
          value: _draft.responseMode,
          items: const {
            'single': 'Resposta padrão',
            'multi': 'Consulta paralela',
            'chain': 'Refinamento em etapas',
          },
          onChanged: (v) => setState(() => _draft.responseMode = v!),
        ),
      ]);

  Widget _buildAuth() => _TabContent(title: 'AUTENTICAÇÃO', children: [
        _SectionCard(title: '🔑 TROCAR SENHA', children: [
          _InlineField(_curPassCtrl, hint: 'Senha atual', obscure: true),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(
                child: _InlineField(_newPassCtrl,
                    hint: 'Nova senha', obscure: true)),
            const SizedBox(width: 10),
            Expanded(
                child: _InlineField(_newPassCCtrl,
                    hint: 'Confirmar nova senha', obscure: true)),
          ]),
          const SizedBox(height: 10),
          _ActionBtn(
            label: 'Salvar nova senha',
            color: AssistantTheme.c2,
            onTap: _changePassword,
          ),
          _InfoBox(
              'O acesso ao assistente é protegido por usuário e senha, exigidos toda vez que o app inicia sem uma sessão válida.'),
        ]),
        _SectionCard(title: '↪ SESSÃO', children: [
          _ActionBtn(
            label: 'Trocar usuário',
            color: AssistantTheme.c2,
            onTap: _switchUser,
          ),
          _InfoBox(
              'Encerra a sessão atual e abre a tela de login. Os dados locais permanecem separados por conta.'),
        ]),
        if (_account?.isAdmin == true)
          _SectionCard(title: '👥 USUÁRIOS E CONVITES', children: [
            _InfoBox(
                'Somente administradores enviam convites. Cada conta recebe conversas, agenda, notificações, memórias e configurações próprias.'),
            _InlineField(
              _inviteEmailCtrl,
              hint: 'Email do novo usuário',
            ),
            const SizedBox(height: 10),
            _ActionBtn(
              label: _inviteBusy ? 'Enviando...' : 'Enviar convite',
              color: AssistantTheme.c1,
              onTap: _inviteUser,
            ),
            if (_users.isNotEmpty) ...[
              const SizedBox(height: 12),
              ..._users.map(
                (item) => Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Row(
                    children: [
                      Icon(
                        item.isActive
                            ? Icons.check_circle_outline
                            : Icons.block_outlined,
                        size: 14,
                        color: item.isActive
                            ? AssistantTheme.c3
                            : AssistantTheme.danger,
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          item.email.isEmpty
                              ? item.username
                              : '${item.username} — ${item.email}',
                          style: const TextStyle(
                            fontFamily: 'JetBrains Mono',
                            fontSize: 10.5,
                            color: AssistantTheme.textSecondary,
                          ),
                        ),
                      ),
                      Text(
                        item.role.toUpperCase(),
                        style: const TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 9,
                          color: AssistantTheme.textMuted,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ]),
      ]);

  Future<void> _changePassword() async {
    final current = _curPassCtrl.text;
    final next = _newPassCtrl.text;
    if (current.isEmpty || next.isEmpty) {
      _showSnack('Preencha a senha atual e a nova senha.');
      return;
    }
    if (next != _newPassCCtrl.text) {
      _showSnack('A confirmação de senha não confere.');
      return;
    }
    try {
      await api.changePassword(currentPassword: current, newPassword: next);
      _curPassCtrl.clear();
      _newPassCtrl.clear();
      _newPassCCtrl.clear();
      _showSnack('Senha alterada com sucesso.');
    } catch (e) {
      _showSnack('Erro ao trocar senha: $e');
    }
  }

  Future<void> _switchUser() async {
    await StorageService.clearAuthToken();
    api.logout();
    ref.read(isAuthenticatedProvider.notifier).state = false;
    if (mounted) {
      Navigator.pushNamedAndRemoveUntil(context, '/main', (_) => false);
    }
  }

  Widget _buildNotif() => _TabContent(title: 'NOTIFICAÇÕES', children: [
        _SectionCard(title: '✈️ TELEGRAM', children: [
          _Field('BOT TOKEN', _tgTokenCtrl,
              hint: '123456789:AABBcc...', obscure: true),
          _Field('CHAT ID', _tgChatCtrl,
              hint: 'Seu chat ID (use @userinfobot)'),
          _ActionBtn(
              label: '📨 Testar Telegram',
              onTap: () async {
                final svc = NotificationService(
                  NotifConfig(
                      tgToken: _tgTokenCtrl.text.trim(),
                      tgChatId: _tgChatCtrl.text.trim(),
                      tgEnabled: true),
                  _nameCtrl.text.isEmpty ? 'Assistente' : _nameCtrl.text,
                );
                final ok = await svc.testTelegram();
                _showSnack(ok
                    ? '✅ Telegram funcionando!'
                    : '❌ Erro — verifique token e chat ID');
              }),
          _InfoBox(
              'Obtenha o token em @BotFather e o Chat ID em @userinfobot no Telegram.'),
        ]),
        _SectionCard(title: '💬 WHATSAPP', children: [
          _Label('PROVEDOR'),
          _Dropdown(
            value: _draft.notif.waProvider,
            items: const {
              'callmebot': 'CallMeBot (gratuito)',
              'zapi': 'Z-API',
              'twilio': 'Twilio'
            },
            onChanged: (v) => setState(() => _draft.notif.waProvider = v!),
          ),
          const SizedBox(height: 10),
          _Field('NÚMERO DE DESTINO', _waNumCtrl, hint: '+5511999999999'),
          _Field('API KEY / TOKEN', _waTokCtrl,
              hint: 'Token do provedor escolhido', obscure: true),
          _ActionBtn(
              label: '📱 Testar WhatsApp',
              onTap: () => _showSnack(
                  'Configure o número e token, depois clique "Salvar" antes de testar')),
        ]),
        _SectionCard(title: '⚙ CONFIGURAÇÕES DE ALERTA', children: [
          _Toggle('Notificar com antecedência', _draft.notif.notify15min,
              (v) => setState(() => _draft.notif.notify15min = v)),
          if (_draft.notif.notify15min)
            _Field(
              'ANTECEDÊNCIA EM MINUTOS',
              _reminderMinutesCtrl,
              hint: 'Ex.: 10, 30, 60 ou 1440',
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            ),
          _Toggle('Notificar também no horário', _draft.notif.notifyOnTime,
              (v) => setState(() => _draft.notif.notifyOnTime = v)),
          const _InfoBox(
            'O horário do aviso acompanha o evento no calendário. Para aulas, '
            'altere o horário no cadastro da turma antes de sincronizar a agenda.',
          ),
          _Toggle(
              'Fallback (Telegram → WhatsApp)',
              _draft.notif.fallbackEnabled,
              (v) => setState(() => _draft.notif.fallbackEnabled = v)),
          _Toggle('Incluir link da reunião', _draft.notif.includeLink,
              (v) => setState(() => _draft.notif.includeLink = v)),
        ]),
      ]);

  Widget _buildCalendar2() => _TabContent(title: 'AGENDAS', children: [
        _SectionCard(title: 'CRIAÇÃO DE EVENTOS', children: [
          _InfoBox(
              'Quando autorizada, a assistente cria pedidos claros de eventos sem abrir a confirmação. A primeira conta compatível é usada; se o provedor não for informado, o Google tem preferência. Esta opção vem desligada por segurança.'),
          _Toggle(
            'Autorizar criação automática',
            _draft.calendar.autoCreateEvents,
            (value) => setState(() => _draft.calendar.autoCreateEvents = value),
          ),
        ]),
        _SectionCard(title: 'GOOGLE CALENDAR', children: [
          _InfoBox(
              'Informe as credenciais OAuth uma vez ou use as que ja estao salvas no backend. O botao libera leitura e criacao de eventos. Reconecte contas antigas para autorizar escrita.'),
          _Field('CLIENT ID', _gcalClientCtrl, hint: 'Google OAuth Client ID'),
          _Field('CLIENT SECRET', _gcalSecretCtrl,
              hint: 'Google OAuth Client Secret', obscure: true),
          _ActionBtn(
            label: _calendarBusy ? 'Aguarde...' : 'Conectar Google Agenda',
            onTap: _openGoogleAuthorization,
          ),
          _CalendarAccountList(
            accounts: _calendarAccounts['google'] ?? const [],
            onRemove: _disconnectCalendarAccount,
          ),
        ]),
        _SectionCard(title: 'MICROSOFT (Teams + Outlook)', children: [
          _InfoBox(
              'Informe as credenciais OAuth uma vez ou use as que ja estao salvas no backend. O botao libera leitura e criacao de eventos. Reconecte contas antigas para autorizar escrita.'),
          _Field('CLIENT ID', _msClientCtrl,
              hint: 'Microsoft Application Client ID'),
          _Field('CLIENT SECRET', _msSecretCtrl,
              hint: 'Microsoft Client Secret', obscure: true),
          _Field('TENANT', _msTenantCtrl, hint: 'common'),
          _ActionBtn(
            label: _calendarBusy ? 'Aguarde...' : 'Conectar Outlook',
            onTap: _openMicrosoftAuthorization,
          ),
          _CalendarAccountList(
            accounts: _calendarAccounts['microsoft'] ?? const [],
            onRemove: _disconnectCalendarAccount,
          ),
        ]),
      ]);

  Widget _buildSystem() => _TabContent(title: 'SISTEMA', children: [
        _SectionCard(title: '🌐 CONEXÃO COM O BACKEND', children: [
          _Field('ENDEREÇO DO BACKEND', _backendUrlCtrl,
              hint: 'http://localhost:8000 ou https://seu-app.up.railway.app'),
          _ActionBtn(
            label: _backendTestBusy ? 'TESTANDO...' : 'APLICAR E TESTAR',
            onTap: _backendTestBusy ? () {} : _applyBackendUrl,
          ),
        ]),
        _SectionCard(title: '🔊 VOZ DA ASSISTENTE', children: [
          _Label('VOZ'),
          _Dropdown(
            value: NeuralTtsService.resolveVoice(
                _draft.ttsVoice, _draft.assistantGender),
            items: NeuralTtsService.voices,
            onChanged: (v) => setState(() => _draft.ttsVoice = v ?? ''),
          ),
          const SizedBox(height: 12),
          _NumberSetting(
            label: 'Velocidade (%)',
            value: _draft.ttsRatePercent,
            min: -50,
            max: 50,
            step: 2,
            onChanged: (v) => setState(() => _draft.ttsRatePercent = v),
          ),
          _NumberSetting(
            label: 'Tom (Hz)',
            value: _draft.ttsPitchHz,
            min: -50,
            max: 50,
            step: 5,
            onChanged: (v) => setState(() => _draft.ttsPitchHz = v),
          ),
          _ActionBtn(
            label: _voiceTestBusy ? 'FALANDO...' : '▶ OUVIR ESTA VOZ',
            onTap: _voiceTestBusy ? () {} : _testVoice,
          ),
          const _InfoBox(
            'Vozes neurais geradas na propria interface, sem custo e sem passar '
            'pelo backend. Sem internet, a assistente usa a voz do Windows.',
          ),
        ]),
        _SectionCard(title: '🖥 PREFERÊNCIAS', children: [
          _Toggle('Iniciar minimizado', _draft.startMinimized,
              (v) => setState(() => _draft.startMinimized = v)),
          _Toggle('Iniciar com o sistema', _draft.autoLaunch,
              (v) => setState(() => _draft.autoLaunch = v)),
          _Toggle('Resposta por voz', _draft.ttsEnabled,
              (v) => setState(() => _draft.ttsEnabled = v)),
          _Toggle('Enter envia mensagem', _draft.sendMessageOnEnter,
              (v) => setState(() => _draft.sendMessageOnEnter = v)),
          const _InfoBox(
            'Ligado: Enter envia e Shift+Enter quebra a linha. Desligado: '
            'Enter quebra a linha e Ctrl+Enter envia.',
          ),
          _Toggle(
              'Microfone ativo por nome da assistente',
              _draft.continuousVoiceMode,
              (v) => setState(() => _draft.continuousVoiceMode = v)),
          _NumberSetting(
            label: 'Tentativas para pedir instrução',
            value: _draft.voicePromptRetries,
            min: 1,
            max: 6,
            onChanged: (v) => setState(() => _draft.voicePromptRetries = v),
          ),
        ]),
        _SectionCard(title: '⚠️ DADOS', children: [
          _ActionBtn(
            label: '🗑 Limpar todos os dados',
            color: AssistantTheme.danger,
            onTap: () async {
              final ok = await showDialog<bool>(
                  context: context,
                  builder: (_) => AlertDialog(
                        backgroundColor: AssistantTheme.surface,
                        title: const Text('Confirmar',
                            style:
                                TextStyle(color: AssistantTheme.textPrimary)),
                        content: const Text(
                            'Isso apagará configurações, dados locais e histórico. Continuar?',
                            style:
                                TextStyle(color: AssistantTheme.textSecondary)),
                        actions: [
                          TextButton(
                              onPressed: () => Navigator.pop(context, false),
                              child: const Text('Cancelar')),
                          TextButton(
                              onPressed: () => Navigator.pop(context, true),
                              child: const Text('Apagar',
                                  style:
                                      TextStyle(color: AssistantTheme.danger))),
                        ],
                      ));
              if (ok == true) {
                await StorageService.clearAll();
                if (mounted) Navigator.pushReplacementNamed(context, '/config');
              }
            },
          ),
        ]),
      ]);

  void _showSnack(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(msg,
            style: const TextStyle(fontFamily: 'JetBrains Mono', fontSize: 11)),
        backgroundColor: AssistantTheme.surface2));
  }

  @override
  void dispose() {
    for (final c in [
      _nameCtrl,
      _userCtrl,
      _personCtrl,
      _curPassCtrl,
      _newPassCtrl,
      _newPassCCtrl,
      _inviteEmailCtrl,
      _tgTokenCtrl,
      _tgChatCtrl,
      _waNumCtrl,
      _waTokCtrl,
      _reminderMinutesCtrl,
      _gcalClientCtrl,
      _gcalSecretCtrl,
      _msClientCtrl,
      _msSecretCtrl,
      _msTenantCtrl,
      _backendUrlCtrl,
    ]) {
      c.dispose();
    }
    _voicePreviewPlayer.dispose();
    super.dispose();
  }
}

class _CalendarAccountList extends StatelessWidget {
  final List<CalendarAccount> accounts;
  final Future<void> Function(CalendarAccount account) onRemove;

  const _CalendarAccountList({
    required this.accounts,
    required this.onRemove,
  });

  @override
  Widget build(BuildContext context) {
    if (accounts.isEmpty) {
      return const Padding(
        padding: EdgeInsets.only(top: 10),
        child: Text(
          'Nenhuma conta conectada ainda.',
          style: TextStyle(
            fontFamily: 'JetBrains Mono',
            fontSize: 10,
            color: AssistantTheme.textMuted,
          ),
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Column(
        children: accounts
            .map(
              (account) => Container(
                margin: const EdgeInsets.only(bottom: 6),
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                decoration: BoxDecoration(
                  border: Border.all(color: AssistantTheme.border),
                  borderRadius: BorderRadius.circular(3),
                ),
                child: Row(
                  children: [
                    Icon(
                      account.connected
                          ? Icons.check_circle_outline
                          : Icons.pending_outlined,
                      size: 15,
                      color: account.connected
                          ? AssistantTheme.c3
                          : AssistantTheme.textMuted,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        account.label.isEmpty
                            ? account.provider
                            : account.label,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontFamily: 'JetBrains Mono',
                          fontSize: 10.5,
                          color: AssistantTheme.textSecondary,
                        ),
                      ),
                    ),
                    Text(
                      account.connected ? 'ATIVA' : 'PENDENTE',
                      style: TextStyle(
                        fontFamily: 'JetBrains Mono',
                        fontSize: 8,
                        color: account.connected
                            ? AssistantTheme.c3
                            : AssistantTheme.textMuted,
                      ),
                    ),
                    IconButton(
                      onPressed: () => onRemove(account),
                      icon: const Icon(
                        Icons.delete_outline,
                        size: 16,
                        color: AssistantTheme.danger,
                      ),
                    ),
                  ],
                ),
              ),
            )
            .toList(),
      ),
    );
  }
}

class _Field extends StatelessWidget {
  final String label;
  final TextEditingController ctrl;
  final String? hint;
  final bool obscure;
  final int maxLines;
  final TextInputType? keyboardType;
  final List<TextInputFormatter>? inputFormatters;
  const _Field(this.label, this.ctrl,
      {this.hint,
      this.obscure = false,
      this.maxLines = 1,
      this.keyboardType,
      this.inputFormatters});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label,
              style: const TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 9,
                  letterSpacing: 3,
                  color: AssistantTheme.textMuted)),
          const SizedBox(height: 5),
          TextField(
              controller: ctrl,
              obscureText: obscure,
              maxLines: maxLines,
              keyboardType: keyboardType,
              inputFormatters: inputFormatters,
              style: const TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 12,
                  color: AssistantTheme.textPrimary),
              decoration: InputDecoration(hintText: hint)),
        ]),
      );
}

class _InlineField extends StatelessWidget {
  final TextEditingController ctrl;
  final String? hint;
  final bool obscure;
  const _InlineField(this.ctrl, {this.hint, this.obscure = false});

  @override
  Widget build(BuildContext context) => TextField(
        controller: ctrl,
        obscureText: obscure,
        style: const TextStyle(
            fontFamily: 'JetBrains Mono',
            fontSize: 12,
            color: AssistantTheme.textPrimary),
        decoration: InputDecoration(hintText: hint),
      );
}

class _Label extends StatelessWidget {
  final String text;
  const _Label(this.text);
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 5),
        child: Text(text,
            style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 9,
                letterSpacing: 3,
                color: AssistantTheme.textMuted)),
      );
}

class _Dropdown extends StatelessWidget {
  final String value;
  final Map<String, String> items;
  final ValueChanged<String?> onChanged;
  const _Dropdown(
      {required this.value, required this.items, required this.onChanged});

  @override
  Widget build(BuildContext context) => DropdownButtonFormField<String>(
        value: items.containsKey(value) ? value : items.keys.first,
        dropdownColor: AssistantTheme.surface,
        style: const TextStyle(
            fontFamily: 'JetBrains Mono',
            fontSize: 12,
            color: AssistantTheme.textPrimary),
        decoration: const InputDecoration(),
        items: items.entries
            .map((e) => DropdownMenuItem(value: e.key, child: Text(e.value)))
            .toList(),
        onChanged: onChanged,
      );
}

class _Toggle extends StatelessWidget {
  final String label;
  final bool value;
  final ValueChanged<bool> onChanged;
  const _Toggle(this.label, this.value, this.onChanged);

  @override
  Widget build(BuildContext context) => Row(children: [
        Text(label,
            style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 11,
                color: AssistantTheme.textSecondary)),
        const Spacer(),
        Switch(
            value: value, onChanged: onChanged, activeColor: AssistantTheme.c3),
      ]);
}

class _NumberSetting extends StatelessWidget {
  final String label;
  final int value;
  final int min;
  final int max;
  final ValueChanged<int> onChanged;

  final int step;

  const _NumberSetting({
    required this.label,
    required this.value,
    required this.onChanged,
    this.min = 0,
    this.max = 10,
    this.step = 1,
  });

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          children: [
            Expanded(
              child: Text(
                label,
                style: const TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 11,
                    color: AssistantTheme.textSecondary),
              ),
            ),
            _MiniStepButton(
              label: '-',
              onTap: value > min
                  ? () => onChanged((value - step).clamp(min, max))
                  : null,
            ),
            SizedBox(
              width: 34,
              child: Text(
                '$value',
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 12,
                  color: AssistantTheme.textPrimary,
                ),
              ),
            ),
            _MiniStepButton(
              label: '+',
              onTap: value < max
                  ? () => onChanged((value + step).clamp(min, max))
                  : null,
            ),
          ],
        ),
      );
}

class _MiniStepButton extends StatelessWidget {
  final String label;
  final VoidCallback? onTap;

  const _MiniStepButton({required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) => SizedBox(
        width: 30,
        height: 28,
        child: OutlinedButton(
          onPressed: onTap,
          style: OutlinedButton.styleFrom(
            padding: EdgeInsets.zero,
            side: BorderSide(color: AssistantTheme.border2.withOpacity(0.8)),
            foregroundColor: AssistantTheme.c1,
          ),
          child: Text(
            label,
            style: const TextStyle(
              fontFamily: 'JetBrains Mono',
              fontSize: 12,
            ),
          ),
        ),
      );
}

class _SectionCard extends StatelessWidget {
  final String title;
  final List<Widget> children;
  const _SectionCard({required this.title, required this.children});

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 16),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
            border: Border.all(color: AssistantTheme.border),
            borderRadius: BorderRadius.circular(4),
            color: AssistantTheme.surface.withOpacity(0.5)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title,
              style: const TextStyle(
                  fontFamily: 'Rajdhani',
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 2,
                  color: AssistantTheme.c1)),
          const SizedBox(height: 12),
          ...children,
        ]),
      );
}

class _InfoBox extends StatelessWidget {
  final String text;
  const _InfoBox(this.text);
  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
            border: Border.all(color: AssistantTheme.c2.withOpacity(0.2)),
            borderRadius: BorderRadius.circular(3),
            color: AssistantTheme.c2.withOpacity(0.04)),
        child: Text(text,
            style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 10,
                color: AssistantTheme.textSecondary,
                height: 1.6)),
      );
}

class _ActionBtn extends StatelessWidget {
  final String label;
  final VoidCallback onTap;
  final Color color;
  const _ActionBtn(
      {required this.label,
      required this.onTap,
      this.color = AssistantTheme.c1});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 4, bottom: 4),
        child: SizedBox(
          width: double.infinity,
          child: OutlinedButton(
            onPressed: onTap,
            style: OutlinedButton.styleFrom(
              side: BorderSide(color: color.withOpacity(0.4)),
              foregroundColor: color,
              padding: const EdgeInsets.symmetric(vertical: 12),
            ),
            child: Text(label,
                style: TextStyle(
                    fontFamily: 'Rajdhani',
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 3,
                    color: color)),
          ),
        ),
      );
}

class _TabBtn extends StatelessWidget {
  final String label;
  final bool active;
  final VoidCallback onTap;
  const _TabBtn(
      {required this.label, required this.active, required this.onTap});

  @override
  Widget build(BuildContext context) => GestureDetector(
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 150),
          margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(3),
            color: active
                ? AssistantTheme.c1.withOpacity(0.08)
                : Colors.transparent,
            border: Border.all(
              color: active ? AssistantTheme.c1 : Colors.transparent,
              width: active ? 1 : 0,
            ),
          ),
          child: Text(label,
              style: TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 10,
                  letterSpacing: 2,
                  color:
                      active ? AssistantTheme.c1 : AssistantTheme.textMuted)),
        ),
      );
}

class _SaveBtn extends StatelessWidget {
  final VoidCallback onTap;
  const _SaveBtn({required this.onTap});

  @override
  Widget build(BuildContext context) => SizedBox(
        width: double.infinity,
        child: ElevatedButton(
          onPressed: onTap,
          style: ElevatedButton.styleFrom(
            backgroundColor: AssistantTheme.c1.withOpacity(0.12),
            side: const BorderSide(color: AssistantTheme.c1, width: 1),
            padding: const EdgeInsets.symmetric(vertical: 13),
          ),
          child: const Text('✅  SALVAR',
              style: TextStyle(
                  fontFamily: 'Rajdhani',
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 4,
                  color: AssistantTheme.c1)),
        ),
      );
}

class _CancelBtn extends StatelessWidget {
  final VoidCallback onTap;
  const _CancelBtn({required this.onTap});

  @override
  Widget build(BuildContext context) => SizedBox(
        width: double.infinity,
        child: OutlinedButton(
          onPressed: onTap,
          style: OutlinedButton.styleFrom(
              side: const BorderSide(color: AssistantTheme.border),
              padding: const EdgeInsets.symmetric(vertical: 11)),
          child: const Text('CANCELAR',
              style: TextStyle(
                  fontFamily: 'JetBrains Mono',
                  fontSize: 10,
                  letterSpacing: 2,
                  color: AssistantTheme.textMuted)),
        ),
      );
}

class _TabContent extends StatelessWidget {
  final String title;
  final List<Widget> children;
  const _TabContent({required this.title, required this.children});

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style: const TextStyle(
                  fontFamily: 'Rajdhani',
                  fontSize: 26,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 6,
                  color: AssistantTheme.c1)),
          const SizedBox(height: 4),
          Container(
              height: 1,
              decoration: const BoxDecoration(
                  gradient: LinearGradient(
                      colors: [AssistantTheme.c1, Colors.transparent]))),
          const SizedBox(height: 24),
          ...children,
        ],
      );
}
