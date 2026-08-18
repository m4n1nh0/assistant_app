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
    expect(find.byKey(const Key('intarq-wordmark')), findsNWidgets(3));
    final wordmark = tester.widget<Text>(
      find.byKey(const Key('intarq-wordmark')).first,
    );
    final rootSpan = wordmark.textSpan! as TextSpan;
    final qSpan = rootSpan.children!.last as TextSpan;
    expect(rootSpan.toPlainText(), 'INTARQ');
    expect(wordmark.style!.color, IntarqBrand.technologySilver);
    expect(qSpan.style!.color, IntarqBrand.electricBlue);
    expect(tester.takeException(), isNull);
  });

  testWidgets('shows the AI ASSISTANT descriptor only when requested',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: Column(
            children: [
              IntarqLockup(width: 142, height: 38),
              IntarqLockup(width: 390, height: 160, showDescriptor: true),
            ],
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('intarq-descriptor')), findsOneWidget);
    final descriptor = tester.widget<Text>(
      find.byKey(const Key('intarq-descriptor')),
    );
    expect(descriptor.data, IntarqBrand.descriptor);
    expect(find.byKey(const Key('intarq-wordmark')), findsNWidgets(2));
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
