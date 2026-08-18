import 'package:assistant_app/branding/intarq_brand.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('renders the mark and the legible INTARQ-only signature',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: Column(
            children: [
              IntarqMark(),
              IntarqLockup(width: 142, height: 38),
              IntarqLockup(width: 245, height: 92),
              IntarqLockup(width: 390, height: 160),
            ],
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(Image), findsNWidgets(4));
    expect(find.text('INTARQ'), findsNWidgets(3));
    expect(tester.takeException(), isNull);
  });

  test('loads the isolated mark used beside INTARQ in PDFs', () async {
    final image = await IntarqBrand.loadPdfMark();
    expect(image, isNotNull);
  });

  test('keeps the official palette values stable', () {
    expect(IntarqBrand.navy.toARGB32(), 0xFF0A1324);
    expect(IntarqBrand.electricBlue.toARGB32(), 0xFF00D6FF);
    expect(IntarqBrand.premiumGold.toARGB32(), 0xFFD4AF37);
    expect(IntarqBrand.technologySilver.toARGB32(), 0xFFB8C2CC);
    expect(IntarqBrand.graphite.toARGB32(), 0xFF0F141C);
  });
}
