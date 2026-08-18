import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

class IntarqBrand {
  static const name = 'INTARQ';
  static const tagline =
      'Inteligência e arquitetura para soluções tecnológicas humanas de confiança.';

  static const iconAsset = 'assets/branding/intarq-icon-transparent.png';
  static const appIconAsset = 'assets/branding/intarq-app-icon.png';
  static const lockupAsset = 'assets/branding/intarq-lockup-horizontal.png';

  static const navy = Color(0xFF0A1324);
  static const electricBlue = Color(0xFF00D6FF);
  static const premiumGold = Color(0xFFD4AF37);
  static const technologySilver = Color(0xFFB8C2CC);
  static const graphite = Color(0xFF0F141C);

  static const pdfNavy = PdfColor.fromInt(0xFF0A1324);
  static const pdfBlue = PdfColor.fromInt(0xFF00A9D4);
  static const pdfGold = PdfColor.fromInt(0xFFD4AF37);
  static const pdfSilver = PdfColor.fromInt(0xFFB8C2CC);

  static pw.MemoryImage? _pdfLockup;

  static Future<pw.MemoryImage?> loadPdfLockup() async {
    if (_pdfLockup != null) return _pdfLockup;
    try {
      final data = await rootBundle.load(lockupAsset);
      _pdfLockup = pw.MemoryImage(data.buffer.asUint8List());
      return _pdfLockup;
    } catch (_) {
      return null;
    }
  }

  static pw.Widget pdfPlaque(
    pw.MemoryImage? lockup, {
    double width = 142,
    double height = 54,
  }) {
    return pw.Container(
      width: width,
      height: height,
      padding: const pw.EdgeInsets.all(6),
      decoration: pw.BoxDecoration(
        color: pdfNavy,
        border: pw.Border.all(color: pdfGold, width: .6),
        borderRadius: const pw.BorderRadius.all(pw.Radius.circular(4)),
      ),
      child: lockup == null
          ? pw.Center(
              child: pw.Text(
                name,
                style: pw.TextStyle(
                  color: PdfColors.white,
                  fontSize: 14,
                  letterSpacing: 3,
                  fontWeight: pw.FontWeight.bold,
                ),
              ),
            )
          : pw.Image(lockup, fit: pw.BoxFit.contain),
    );
  }
}

class IntarqLockup extends StatelessWidget {
  final double width;
  final double height;

  const IntarqLockup({
    super.key,
    this.width = 180,
    this.height = 70,
  });

  @override
  Widget build(BuildContext context) => SizedBox(
        width: width,
        height: height,
        child: Image.asset(
          IntarqBrand.lockupAsset,
          fit: BoxFit.contain,
          filterQuality: FilterQuality.high,
          errorBuilder: (_, __, ___) => const Center(
            child: Text(
              IntarqBrand.name,
              style: TextStyle(
                fontWeight: FontWeight.w800,
                letterSpacing: 5,
                color: IntarqBrand.electricBlue,
              ),
            ),
          ),
        ),
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
