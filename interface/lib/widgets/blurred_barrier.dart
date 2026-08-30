/// Desfoca o que estiver atras de um dialogo modal.
///
/// A barreira padrao do `showDialog` apenas escurece; o conteudo continua
/// legivel atras dela. Este widget acrescenta o desfoque, para o caso em que o
/// dialogo sobe sobre uma tela que ainda tem conteudo - por exemplo, a
/// reautenticacao depois de "trocar usuario", enquanto a tela anterior esta
/// sendo desmontada.
///
/// Nao substitui esconder o conteudo de fato: desfoque e efeito visual, e uma
/// captura de tela ainda registra as formas. Quando o conteudo e sensivel, ele
/// nao deve estar montado - veja `LockedBackdrop`.
library;

import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';

class BlurredBarrier extends StatelessWidget {
  /// O conteudo que fica nitido por cima do desfoque.
  final Widget child;

  /// Raio do desfoque aplicado ao que esta atras.
  final double sigma;

  const BlurredBarrier({
    super.key,
    required this.child,
    this.sigma = 16,
  });

  @override
  Widget build(BuildContext context) {
    // Os dois filhos sao posicionados de proposito. Um `Stack` se dimensiona
    // pelo maior filho **nao** posicionado - com o dialogo solto aqui, a pilha
    // encolheria para o tamanho dele e o desfoque cobriria so essa area,
    // deixando o resto da janela nitido.
    //
    // Com tudo posicionado, a pilha assume as constraints que recebe (a tela
    // inteira, vindas da rota do dialogo) e o filho continua recebendo as
    // mesmas constraints de antes - entao um `Dialog` segue se centralizando
    // sozinho, como faria sem este widget.
    return Stack(
      children: [
        Positioned.fill(
          child: BackdropFilter(
            filter: ImageFilter.blur(sigmaX: sigma, sigmaY: sigma),
            child: const SizedBox.expand(),
          ),
        ),
        Positioned.fill(child: child),
      ],
    );
  }
}
