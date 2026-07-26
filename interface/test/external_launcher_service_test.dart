import 'package:assistant_app/services/external_launcher_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('IDEs suportadas cobrem os ids enviados pelo backend', () {
    expect(ExternalLauncherService.ideLabels.keys, containsAll(['pycharm', 'vscode']));
    expect(ExternalLauncherService.ideLabels['vscode'], 'VS Code');
  });

  test('IDE desconhecida é rejeitada antes de procurar o projeto', () async {
    await expectLater(
      ExternalLauncherService.openProjectInIde(
        ide: 'sublime',
        projectQuery: 'qualquer',
      ),
      throwsA(
        isA<Exception>().having(
          (e) => e.toString(),
          'mensagem',
          contains('IDE nao suportada'),
        ),
      ),
    );
  });
}
