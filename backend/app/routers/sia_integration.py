from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from loguru import logger
import json

from ..services.sia_scraper_service import SiaScraperService

router = APIRouter(prefix="/education/sia", tags=["SIA Integration"])

class SessionCookies(BaseModel):
    """Cookies da sessão do SIA"""
    cookies: dict

class PeriodoResponse(BaseModel):
    """Período acadêmico disponível"""
    value: str
    label: str

class TurmaResponse(BaseModel):
    """Turma do professor"""
    num_seq_turma: str
    campus: str
    curso: str
    turno: str
    codigo: str
    disciplina: str
    turma: str

class AulaResponse(BaseModel):
    """Aula disponível"""
    num_seq_data_turma: str
    data: str
    hora_inicio: str
    hora_fim: str

class StudentAttendanceResponse(BaseModel):
    """Dados de um aluno"""
    numero: int
    matricula: str
    nome: str
    presente: bool

class AttendancePageResponse(BaseModel):
    """Página de lançamento de frequência"""
    professor: str
    periodo: str
    campus: str
    disciplina: str
    turma: str
    aulas: list[AulaResponse]
    students: list[StudentAttendanceResponse]

class HtmlPayload(BaseModel):
    """HTML de uma tela do SIA, ja buscado pelo WebView autenticado."""
    html: str


class LancamentoConfirmado(BaseModel):
    """Confirmacao de que a pauta foi gravada no sistema da instituicao."""
    ref_id: str
    turma: str = ""
    marcados: int = 0
    detalhe: str = ""


@router.post("/mark-synced")
async def mark_synced(req: LancamentoConfirmado):
    """Registra que a chamada ja foi lancada no sistema da instituicao.

    So e chamado depois que o SIA confirma a gravacao — evita o professor
    relancar a mesma pauta sem saber.
    """
    from datetime import datetime, timezone
    from sqlalchemy import select, or_
    from ..core.database import AsyncSessionLocal, AttendanceSessionModel

    async with AsyncSessionLocal() as db:
        chamadas = (await db.execute(
            select(AttendanceSessionModel).where(or_(
                AttendanceSessionModel.id == req.ref_id,
                AttendanceSessionModel.lesson_id == req.ref_id,
            ))
        )).scalars().all()

        if not chamadas:
            raise HTTPException(status_code=404, detail="Chamada nao encontrada")

        agora = datetime.now(timezone.utc)
        detalhe = (
            f"turma {req.turma}: {req.marcados} presentes"
            if req.turma else req.detalhe
        )[:255]

        for chamada in chamadas:
            chamada.external_synced_at = agora
            chamada.external_system = 'sia'
            chamada.external_detail = detalhe

        await db.commit()

    logger.info(
        f"Chamada {req.ref_id} marcada como lancada no SIA ({detalhe})"
    )
    return {'status': 'ok', 'synced_at': agora.isoformat(), 'detalhe': detalhe}


@router.get("/lesson/{ref_id}/attendance")
async def lesson_attendance(ref_id: str):
    """Presenca registrada no INTARQ, pronta para espelhar na pauta do SIA.

    `ref_id` aceita tanto o id de uma chamada (`attendance_sessions.id`) quanto
    o de uma aula (`lessons.id`): quem faz check-in fica preso a chamada, e uma
    aula pode ter mais de uma chamada — juntamos todas.
    """
    from sqlalchemy import select, or_
    from ..core.database import (
        AsyncSessionLocal, AttendanceRecordModel, AttendanceRosterModel,
        AttendanceSessionModel, LessonModel,
    )

    async with AsyncSessionLocal() as db:
        chamadas = (await db.execute(
            select(AttendanceSessionModel).where(or_(
                AttendanceSessionModel.id == ref_id,
                AttendanceSessionModel.lesson_id == ref_id,
            ))
        )).scalars().all()

        # A chamada por QR nao guarda `lesson_id` (so o fluxo que abre a
        # chamada a partir de uma aula preenche esse campo). Para o botao do
        # historico funcionar, caimos no par disciplina + dia da aula.
        casado_por = 'id'
        if not chamadas:
            aula = (await db.execute(
                select(LessonModel).where(LessonModel.id == ref_id)
            )).scalars().first()

            if aula is not None and aula.started_at is not None:
                dia = aula.started_at.date().isoformat()
                chamadas = (await db.execute(
                    select(AttendanceSessionModel).where(
                        AttendanceSessionModel.tutor_id == aula.tutor_id,
                        AttendanceSessionModel.attendance_date == dia,
                        AttendanceSessionModel.discipline == aula.discipline,
                    )
                )).scalars().all()
                if chamadas:
                    casado_por = 'disciplina+data'

        if not chamadas:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Nenhuma chamada encontrada para este identificador. "
                    "Abra pela aba PRESENÇA, na chamada que quer lançar."
                ),
            )

        ids = [c.id for c in chamadas]

        presentes = (await db.execute(
            select(AttendanceRecordModel)
            .where(AttendanceRecordModel.session_id.in_(ids))
        )).scalars().all()

        # A lista da chamada permite reportar quem faltou, nao so quem veio.
        matriculados = (await db.execute(
            select(AttendanceRosterModel)
            .where(AttendanceRosterModel.session_id.in_(ids))
        )).scalars().all()

    # A pauta do SIA e por turma, mas uma chamada pode juntar varias
    # (ex.: "3001 + 3029"). A turma de cada aluno so existe na lista da
    # chamada, entao ela vem de la para o app filtrar depois.
    turma_do_aluno = {
        (r.session_id, r.student_id): r.class_label for r in matriculados
    }

    principal = chamadas[0]
    turmas = sorted({r.class_label for r in matriculados if r.class_label})

    return {
        'ref_id': ref_id,
        'chamadas': len(chamadas),
        'casado_por': casado_por,
        'discipline': principal.discipline,
        'class_group': principal.class_label,
        'data': principal.attendance_date,
        'turmas': turmas,
        'presentes': [
            {
                'matricula': r.enrollment,
                'nome': r.student_name,
                'origem': r.source,
                'turma': turma_do_aluno.get((r.session_id, r.student_id), ''),
            }
            for r in presentes
        ],
        'matriculados': [
            {
                'matricula': r.enrollment,
                'nome': r.student_name,
                'turma': r.class_label,
            }
            for r in matriculados
        ],
    }


@router.post("/parse-session")
async def parse_session(req: HtmlPayload):
    """Confirma que o HTML veio de uma sessao autenticada do SIA."""
    return {'valid': SiaScraperService().parse_session(req.html)}


@router.post("/parse-periodos")
async def parse_periodos(req: HtmlPayload):
    """Extrai os periodos academicos do HTML."""
    return SiaScraperService().parse_periodos(req.html)


@router.post("/parse-turmas")
async def parse_turmas(req: HtmlPayload):
    """Extrai as turmas do professor do HTML."""
    return [vars(t) for t in SiaScraperService().parse_turmas(req.html)]


@router.post("/parse-attendance")
async def parse_attendance(req: HtmlPayload):
    """Extrai a pauta (alunos, aulas, turma) do HTML."""
    page = SiaScraperService().parse_attendance(req.html)
    turma = page['turma']

    return {
        'professor': turma.get('professor', ''),
        'periodo': turma.get('periodo', ''),
        'campus': turma.get('campus', ''),
        'disciplina': turma.get('disciplina', ''),
        'turma': turma.get('turma', ''),
        'aulas': [vars(a) for a in page['aulas']],
        'students': [
            {
                'numero': s.get('numero'),
                'matricula': s.get('matricula', ''),
                'nome': s.get('nome', ''),
                'presente': s.get('presente', False),
            }
            for s in page['students']
        ],
    }


@router.post("/test-session")
async def test_sia_session(req: SessionCookies):
    cookies = req.cookies
    """
    Testa se a sessão do SIA é válida

    Recebe os cookies da sessão após login automático
    """
    try:
        scraper = SiaScraperService()
        valid = await scraper.test_session(cookies)
        await scraper.close()

        return {'valid': valid}
    except Exception as e:
        logger.exception(f"Erro ao testar sessão SIA: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/periodos")
async def get_periodos(req: SessionCookies):
    cookies = req.cookies
    """
    Lista períodos acadêmicos disponíveis
    """
    try:
        scraper = SiaScraperService()
        periodos = await scraper.get_periodos(cookies)
        await scraper.close()

        return periodos
    except Exception as e:
        logger.exception(f"Erro ao extrair períodos: {e}")
        raise HTTPException(status_code=400, detail=str(e))

class TurmasRequest(BaseModel):
    """Requisição para listar turmas"""
    cookies: dict
    periodo_id: str

@router.post("/turmas")
async def get_turmas(req: TurmasRequest):
    """
    Lista turmas do professor para um período
    """
    cookies = req.cookies
    periodo_id = req.periodo_id
    try:
        scraper = SiaScraperService()
        turmas = await scraper.get_turmas(cookies, periodo_id)
        await scraper.close()

        return [
            {
                'num_seq_turma': t.num_seq_turma,
                'campus': t.campus,
                'curso': t.curso,
                'turno': t.turno,
                'codigo': t.codigo,
                'disciplina': t.disciplina,
                'turma': t.turma
            }
            for t in turmas
        ]
    except Exception as e:
        logger.exception(f"Erro ao extrair turmas: {e}")
        raise HTTPException(status_code=400, detail=str(e))

class AttendanceRequest(BaseModel):
    """Requisição para extrair página de frequência"""
    cookies: dict
    turma_id: str
    periodo_id: str

@router.post("/attendance")
async def get_attendance_page(req: AttendanceRequest):
    """
    Extrai página de lançamento de frequência

    Retorna alunos e suas presenças atuais
    """
    cookies = req.cookies
    turma_id = req.turma_id
    periodo_id = req.periodo_id
    try:
        scraper = SiaScraperService()
        page = await scraper.get_attendance_page(
            cookies,
            turma_id,
            periodo_id
        )
        await scraper.close()

        if not page:
            raise HTTPException(status_code=404, detail="Página não encontrada")

        turma = page['turma']

        return {
            'professor': turma.get('professor', ''),
            'periodo': turma.get('periodo', ''),
            'campus': turma.get('campus', ''),
            'disciplina': turma.get('disciplina', ''),
            'turma': turma.get('turma', ''),
            'aulas': [
                {
                    'num_seq_data_turma': a.num_seq_data_turma,
                    'data': a.data,
                    'hora_inicio': a.hora_inicio,
                    'hora_fim': a.hora_fim
                }
                for a in page['aulas']
            ],
            'students': [
                {
                    'numero': s['numero'],
                    'matricula': s['matricula'],
                    'nome': s['nome'],
                    'presente': s['presente']
                }
                for s in page['students']
            ]
        }
    except Exception as e:
        logger.exception(f"Erro ao extrair página de presença: {e}")
        raise HTTPException(status_code=400, detail=str(e))

class ImportAttendanceRequest(BaseModel):
    """Requisição para importar presença"""
    lesson_id: str
    students_data: list[dict]

@router.post("/import-attendance")
async def import_attendance(req: ImportAttendanceRequest):
    """
    Importa dados de presença do SIA para a aula

    Cria registros de presença para alunos marcados como presentes
    """
    lesson_id = req.lesson_id
    students_data = req.students_data
    try:
        from sqlalchemy import select

        if not lesson_id:
            raise HTTPException(status_code=400, detail="lesson_id obrigatório")

        from ..core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            # Busca a aula
            from ..core.database import LessonModel
            stmt = select(LessonModel).where(LessonModel.id == lesson_id)
            result = await session.execute(stmt)
            lesson = result.scalars().first()

            if not lesson:
                raise HTTPException(status_code=404, detail="Aula não encontrada")

            # Importa presença dos alunos
            from ..core.database import AttendanceRecordModel
            imported = 0

            for student in students_data:
                if not student.get('presente', False):
                    continue  # Só importa presentes

                try:
                    # Tenta criar registro de presença
                    record = AttendanceRecordModel(
                        session_id=lesson_id,
                        student_id=student.get('matricula', ''),
                        enrollment=student.get('matricula', ''),
                        student_name=student.get('nome', ''),
                        source='sia'  # Fonte: SIA
                    )
                    session.add(record)
                    imported += 1
                except Exception as e:
                    logger.warning(f"Falha ao importar {student.get('nome')}: {e}")
                    continue

            # Confirma todas as mudanças
            await session.commit()

            logger.info(
                f"Importação SIA concluída: {imported} alunos presentes "
                f"para aula {lesson.id} ({lesson.discipline})"
            )

        return {
            'status': 'success',
            'imported': imported,
            'total': len(students_data),
            'lesson_id': lesson_id,
            'message': f'{imported} presentes registrados'
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Erro ao importar presença: {e}")
        raise HTTPException(status_code=400, detail=str(e))
