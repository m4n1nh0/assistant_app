/// Fundo da janela enquanto nao ha sessao ativa.
///
/// E o que aparece atras do dialogo de acesso. Existe para responder a uma
/// pergunta de privacidade: antes deste widget, a tela principal montava os tres
/// paineis assim que a janela abria, e o dialogo de acesso subia um quadro
/// depois - entao a conversa do usuario anterior ficava visivel atras dele, e
/// aparecia inteira num screenshot ou numa tela compartilhada.
///
/// Por isso ele nao recebe nem exibe dado nenhum do app: so a marca.
library;

import 'package:flutter/material.dart';

import '../branding/intarq_brand.dart';
import '../utils/theme.dart';

class LockedBackdrop extends StatelessWidget {
  /// Opacidade da marca ao fundo. Baixa de proposito: e plano de fundo, nao
  /// elemento de destaque - quem tem que chamar atencao e o dialogo por cima.
  final double markOpacity;

  /// Largura da marca em pixels logicos.
  final double markWidth;

  const LockedBackdrop({
    super.key,
    this.markOpacity = 0.16,
    this.markWidth = 190,
  });

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: const BoxDecoration(
        gradient: RadialGradient(
          center: Alignment.center,
          radius: 0.9,
          colors: [AssistantTheme.bg2, AssistantTheme.bg],
        ),
      ),
      child: Center(
        child: Opacity(
          opacity: markOpacity,
          child: Image.asset(
            IntarqBrand.iconAsset,
            width: markWidth,
            filterQuality: FilterQuality.medium,
            // Marca ausente nao pode virar tela de erro: o que importa aqui e
            // nao mostrar conteudo, e o fundo vazio ja cumpre isso.
            errorBuilder: (_, __, ___) => const SizedBox.shrink(),
          ),
        ),
      ),
    );
  }
}
