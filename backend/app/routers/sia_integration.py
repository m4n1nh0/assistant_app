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


@router.get("/lesson/{lesson_id}/attendance")
async def lesson_attendance(lesson_id: str):
    """Presenca registrada no INTARQ para uma aula.

    E a fonte da verdade que sera espelhada na pauta do SIA: quem fez check-in
    (QR code ou chamada) entra como presente.
    """
    from sqlalchemy import select
    from ..core.database import (
        SessionLocal, AttendanceRecordModel, AttendanceRosterModel, LessonModel
    )

    async with SessionLocal() as session:
        lesson = (await session.execute(
            select(LessonModel).where(LessonModel.id == lesson_id)
        )).scalars().first()
        if not lesson:
            raise HTTPException(status_code=404, detail="Aula nao encontrada")

        presentes = (await session.execute(
            select(AttendanceRecordModel)
            .where(AttendanceRecordModel.session_id == lesson_id)
        )).scalars().all()

        # A lista da chamada permite reportar quem faltou, nao so quem veio.
        matriculados = (await session.execute(
            select(AttendanceRosterModel)
            .where(AttendanceRosterModel.session_id == lesson_id)
        )).scalars().all()

    return {
        'lesson_id': lesson_id,
        'discipline': lesson.discipline,
        'class_group': lesson.class_group,
        'presentes': [
            {
                'matricula': r.enrollment,
                'nome': r.student_name,
                'origem': r.source,
            }
            for r in presentes
        ],
        'matriculados': [
            {'matricula': r.enrollment, 'nome': r.student_name}
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
        from sqlalchemy.ext.asyncio import AsyncSession
        from ..core.database import get_session_maker

        if not lesson_id:
            raise HTTPException(status_code=400, detail="lesson_id obrigatório")

        # Usa o SessionLocal do banco
        from ..core.database import SessionLocal

        async with SessionLocal() as session:
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
