import 'package:assistant_app/services/education_service.dart';
import 'package:assistant_app/widgets/education_dashboard.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Discipline _discipline({
  required String id,
  required String semester,
  required bool active,
  required int classCount,
}) =>
    Discipline(
      id: id,
      code: id.toUpperCase(),
      name: 'Disciplina $id',
      label: 'Disciplina $id',
      semester: semester,
      active: active,
      classCount: classCount,
    );

ClassGroup _classGroup({
  required String id,
  required String semester,
  required int students,
  bool active = true,
  List<ClassSchedule> schedules = const [],
}) =>
    ClassGroup(
      id: id,
      code: id.toUpperCase(),
      name: 'Turma $id',
      discipline: 'Banco de Dados',
      semester: semester,
      label: 'Turma $id',
      active: active,
      studentCount: students,
      schedules: schedules,
    );

void main() {
  test('summarizes semesters using disciplines and loaded classes', () {
    final result = summarizeEducationSemesters(
      [
        _discipline(
          id: 'd1',
          semester: '2026.2',
          active: true,
          classCount: 2,
        ),
        _discipline(
          id: 'd2',
          semester: '2026.2',
          active: true,
          classCount: 1,
        ),
        _discipline(
          id: 'd3',
          semester: '2026.1',
          active: false,
          classCount: 2,
        ),
      ],
      [
        _classGroup(id: '3001', semester: '2026.2', students: 10),
        _classGroup(id: '3002', semester: '2026.2', students: 12),
      ],
    );

    expect(result.map((item) => item.code), ['2026.2', '2026.1']);
    expect(result.first.active, isTrue);
    expect(result.first.disciplineCount, 2);
    expect(result.first.classCount, 3);
    expect(result.first.studentCount, 22);
    expect(result.last.active, isFalse);
  });

  test('builds the weekly agenda in day and time order', () {
    final result = buildEducationAgenda([
      _classGroup(
        id: '3002',
        semester: '2026.2',
        students: 12,
        schedules: const [
          ClassSchedule(weekday: 2, startTime: '18:30'),
          ClassSchedule(weekday: 0, startTime: '20:00'),
        ],
      ),
      _classGroup(
        id: '3001',
        semester: '2026.2',
        students: 10,
        schedules: const [
          ClassSchedule(weekday: 0, startTime: '18:30'),
        ],
      ),
      _classGroup(
        id: 'archived',
        semester: '2026.1',
        students: 5,
        active: false,
        schedules: const [
          ClassSchedule(weekday: 0, startTime: '08:00'),
        ],
      ),
    ]);

    expect(result.map((item) => item.classCode), ['3001', '3002', '3002']);
    expect(result.map((item) => item.weekday), [0, 0, 2]);
    expect(result.map((item) => item.startTime), ['18:30', '20:00', '18:30']);
  });

  testWidgets('renders the four panels and opens existing areas',
      (tester) async {
    final classes = ValueNotifier<List<ClassGroup>?>([
      _classGroup(
        id: '3001',
        semester: currentEducationSemesterCode(DateTime.now()),
        students: 24,
        schedules: const [
          ClassSchedule(weekday: 0, startTime: '18:30'),
        ],
      ),
    ]);
    var classesOpened = false;
    var historyOpened = false;

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 1000,
            height: 720,
            child: EducationDashboard(
              classes: classes,
              loadDisciplines: () async => [
                _discipline(
                  id: 'd1',
                  semester: currentEducationSemesterCode(DateTime.now()),
                  active: true,
                  classCount: 1,
                ),
              ],
              onOpenClasses: () => classesOpened = true,
              onOpenPoints: () {},
              onOpenHistory: () => historyOpened = true,
              onOpenAttendance: () {},
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('TUDO ORGANIZADO'), findsOneWidget);
    expect(find.text('SEMESTRES'), findsOneWidget);
    expect(find.text('TURMAS E ALUNOS'), findsOneWidget);
    expect(find.text('AGENDA DA SEMANA'), findsOneWidget);
    expect(find.text('RELATORIOS EM PDF'), findsOneWidget);

    await tester.tap(find.text('ABRIR CADASTRO'));
    expect(classesOpened, isTrue);

    await tester.tap(find.text('RESUMOS'));
    expect(historyOpened, isTrue);

    classes.dispose();
  });
}
