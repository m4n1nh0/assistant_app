import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

class IntarqBrand {
  static const name = 'INTARQ';
  // Descritor do produto: acompanha a assinatura apenas no splash, na tela de
  // acesso, no título da janela e nos metadados do executável. Barra superior
  // e relatórios seguem somente com o nome INTARQ.
  static const descriptor = 'AI ASSISTANT';
  static const windowTitle = 'INTARQ — AI Assistant';

  static const iconAsset = 'assets/branding/intarq-icon-transparent.png';
  static const appIconAsset = 'assets/branding/intarq-app-icon.png';

  static const navy = Color(0xFF0A1324);
  static const electricBlue = Color(0xFF00D6FF);
  static const premiumGold = Color(0xFFD4AF37);
  static const technologySilver = Color(0xFFB8C2CC);
  static const graphite = Color(0xFF0F141C);

  static const pdfNavy = PdfColor.fromInt(0xFF0A1324);
  static const pdfBlue = PdfColor.fromInt(0xFF00A9D4);
  static const pdfGold = PdfColor.fromInt(0xFFD4AF37);
  static const pdfSilver = PdfColor.fromInt(0xFFB8C2CC);

  static pw.MemoryImage? _pdfMark;

  static Future<pw.MemoryImage?> loadPdfMark() async {
    if (_pdfMark != null) return _pdfMark;
    try {
      final data = await rootBundle.load(iconAsset);
      _pdfMark = pw.MemoryImage(data.buffer.asUint8List());
      return _pdfMark;
    } catch (_) {
      return null;
    }
  }

  static pw.Widget pdfSignature(
    pw.MemoryImage? mark, {
    double width = 142,
    double height = 54,
  }) {
    final markSize = height > 16 ? height - 12 : height;
    final nameSize = height * .27;
    return pw.Container(
      width: width,
      height: height,
      padding: const pw.EdgeInsets.all(6),
      decoration: pw.BoxDecoration(
        color: PdfColors.white,
        border: pw.Border.all(color: pdfSilver, width: .6),
        borderRadius: const pw.BorderRadius.all(pw.Radius.circular(4)),
      ),
      child: pw.Row(
        mainAxisAlignment: pw.MainAxisAlignment.center,
        children: [
          if (mark != null) ...[
            pw.Image(
              mark,
              width: markSize,
              height: markSize,
              fit: pw.BoxFit.contain,
            ),
            pw.SizedBox(width: 5),
          ],
          pdfWordmark(fontSize: nameSize),
        ],
      ),
    );
  }

  static pw.Widget pdfWordmark({
    double fontSize = 14,
    PdfColor intarColor = pdfNavy,
  }) {
    final spacing = fontSize * .1;
    return pw.Row(
      mainAxisSize: pw.MainAxisSize.min,
      children: [
        pw.Text(
          'INTAR',
          style: pw.TextStyle(
            color: intarColor,
            fontSize: fontSize,
            letterSpacing: spacing,
            fontWeight: pw.FontWeight.bold,
          ),
        ),
        pw.Text(
          'Q',
          style: pw.TextStyle(
            color: pdfBlue,
            fontSize: fontSize,
            letterSpacing: spacing,
            fontWeight: pw.FontWeight.bold,
          ),
        ),
      ],
    );
  }
}

class IntarqLockup extends StatelessWidget {
  final double width;
  final double height;
  final bool showDescriptor;

  const IntarqLockup({
    super.key,
    this.width = 180,
    this.height = 70,
    this.showDescriptor = false,
  });

  @override
  Widget build(BuildContext context) {
    if (!showDescriptor) {
      return SizedBox(width: width, height: height, child: _signature(height));
    }
    final signatureHeight = height * .72;
    return SizedBox(
      width: width,
      height: height,
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          SizedBox(
            height: signatureHeight,
            child: _signature(signatureHeight),
          ),
          SizedBox(height: (height * .05).clamp(3, 12).toDouble()),
          FittedBox(
            fit: BoxFit.scaleDown,
            child: Text(
              IntarqBrand.descriptor,
              key: const Key('intarq-descriptor'),
              maxLines: 1,
              style: TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: (height * .1).clamp(8, 15).toDouble(),
                letterSpacing: (height * .055).clamp(3, 10).toDouble(),
                color: IntarqBrand.technologySilver.withOpacity(.78),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _signature(double height) => Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          IntarqMark(
            size: (height * .78).clamp(18, width * .34).toDouble(),
          ),
          SizedBox(
            width: (height * .14).clamp(5, 22).toDouble(),
          ),
          Expanded(
            child: FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Text.rich(
                const TextSpan(
                  children: [
                    TextSpan(text: 'INTAR'),
                    TextSpan(
                      text: 'Q',
                      style: TextStyle(color: IntarqBrand.electricBlue),
                    ),
                  ],
                ),
                key: const Key('intarq-wordmark'),
                maxLines: 1,
                style: TextStyle(
                  fontFamily: 'Rajdhani',
                  fontSize: height * .42,
                  fontWeight: FontWeight.w700,
                  letterSpacing: (height * .08).clamp(2, 10).toDouble(),
                  color: IntarqBrand.technologySilver,
                ),
              ),
            ),
          ),
        ],
      );
}

class IntarqMark extends StatelessWidget {
  final double size;

  const IntarqMark({super.key, this.size = 34});

  @override
  Widget build(BuildContext context) => SizedBox.square(
        dimension: size,
        child: Image.asset(
          IntarqBrand.iconAsset,
          fit: BoxFit.contain,
          filterQuality: FilterQuality.high,
          errorBuilder: (_, __, ___) => const Icon(
            Icons.architecture_outlined,
            color: IntarqBrand.electricBlue,
          ),
        ),
      );
}
