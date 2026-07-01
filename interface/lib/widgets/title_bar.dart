import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:window_manager/window_manager.dart';
import '../providers/app_provider.dart';
import '../utils/theme.dart';

class AssistantTitleBar extends ConsumerWidget {
  const AssistantTitleBar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final config = ref.watch(configProvider);
    final isAuth = ref.watch(isAuthenticatedProvider);

    return GestureDetector(
      onPanStart: (_) => windowManager.startDragging(),
      child: Container(
        height: 48,
        decoration: const BoxDecoration(
          color: Color(0xFF090C13),
          border: Border(bottom: BorderSide(color: AssistantTheme.border, width: 1)),
        ),
        child: Row(
          children: [
            const SizedBox(width: 16),

            Text(
              config.assistantName.trim(),
              style: const TextStyle(
                fontFamily: 'Rajdhani',
                fontSize: 20,
                fontWeight: FontWeight.w800,
                letterSpacing: 8,
                color: AssistantTheme.c1,
                shadows: [Shadow(color: Color(0x6038BDF8), blurRadius: 20)],
              ),
            ),

            const SizedBox(width: 16),

            _StatusPill(isOnline: isAuth),

            const Spacer(),

            if (config.userName.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(right: 12),
                child: Text(
                  config.userName.toUpperCase(),
                  style: const TextStyle(
                    fontFamily: 'JetBrains Mono',
                    fontSize: 10,
                    letterSpacing: 3,
                    color: AssistantTheme.textMuted,
                  ),
                ),
              ),

            _TitleBtn(
              icon: Icons.settings_outlined,
              tooltip: 'Configurações',
              onTap: () => Navigator.pushNamed(context, '/config'),
            ),

            _TitleBtn(
              icon: Icons.remove,
              tooltip: 'Minimizar',
              onTap: windowManager.minimize,
            ),

            _TitleBtn(
              icon: Icons.crop_square_outlined,
              tooltip: 'Maximizar',
              onTap: () async {
                if (await windowManager.isMaximized()) {
                  windowManager.unmaximize();
                } else {
                  windowManager.maximize();
                }
              },
            ),

            _TitleBtn(
              icon: Icons.close,
              tooltip: 'Fechar',
              onTap: windowManager.close,
              hoverColor: AssistantTheme.danger,
            ),

            const SizedBox(width: 4),
          ],
        ),
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  final bool isOnline;
  const _StatusPill({required this.isOnline});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        border: Border.all(color: AssistantTheme.border),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 6, height: 6,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: isOnline ? AssistantTheme.c3 : AssistantTheme.textMuted,
              boxShadow: isOnline ? [BoxShadow(color: AssistantTheme.c3.withOpacity(0.6), blurRadius: 6)] : null,
            ),
          ),
          const SizedBox(width: 6),
          Text(
            isOnline ? 'ONLINE' : 'OFFLINE',
            style: TextStyle(
              fontFamily: 'JetBrains Mono',
              fontSize: 9,
              letterSpacing: 2,
              color: isOnline ? AssistantTheme.c3 : AssistantTheme.textMuted,
            ),
          ),
        ],
      ),
    );
  }
}

class _TitleBtn extends StatefulWidget {
  final IconData icon;
  final String tooltip;
  final VoidCallback onTap;
  final Color? hoverColor;

  const _TitleBtn({required this.icon, required this.tooltip, required this.onTap, this.hoverColor});

  @override
  State<_TitleBtn> createState() => _TitleBtnState();
}

class _TitleBtnState extends State<_TitleBtn> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: widget.tooltip,
      child: MouseRegion(
        onEnter: (_) => setState(() => _hovered = true),
        onExit: (_) => setState(() => _hovered = false),
        child: GestureDetector(
          onTap: widget.onTap,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 150),
            width: 40, height: 40,
            decoration: BoxDecoration(
              color: _hovered
                  ? (widget.hoverColor ?? AssistantTheme.c1).withOpacity(0.12)
                  : Colors.transparent,
            ),
            child: Icon(
              widget.icon,
              size: 16,
              color: _hovered
                  ? (widget.hoverColor ?? AssistantTheme.c1)
                  : AssistantTheme.textMuted,
            ),
          ),
        ),
      ),
    );
  }
}
