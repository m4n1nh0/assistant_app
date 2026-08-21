from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from loguru import logger
import json

from ..services.sia_scraper_service import SiaScraperService
from ..core.database import education

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

@router.post("/test-session", response_model=dict)
async def test_sia_session(req: SessionCookies):
    """
    Testa se a sessão do SIA é válida

    Recebe os cookies da sessão após login manual
    """
    try:
        scraper = SiaScraperService()
        valid = await scraper.test_session(req.cookies)
        await scraper.close()

        return {'valid': valid}
    except Exception as e:
        logger.exception(f"Erro ao testar sessão SIA: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/periodos", response_model=list[PeriodoResponse])
async def get_periodos(req: SessionCookies):
    """
    Lista períodos acadêmicos disponíveis
    """
    try:
        scraper = SiaScraperService()
        periodos = await scraper.get_periodos(req.cookies)
        await scraper.close()

        return [
            PeriodoResponse(**p) for p in periodos
        ]
    except Exception as e:
        logger.exception(f"Erro ao extrair períodos: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/turmas", response_model=list[TurmaResponse])
async def get_turmas(
    req: SessionCookies,
    periodo_id: str
):
    """
    Lista turmas do professor para um período
    """
    try:
        scraper = SiaScraperService()
        turmas = await scraper.get_turmas(req.cookies, periodo_id)
        await scraper.close()

        return [
            TurmaResponse(
                num_seq_turma=t.num_seq_turma,
                campus=t.campus,
                curso=t.curso,
                turno=t.turno,
                codigo=t.codigo,
                disciplina=t.disciplina,
                turma=t.turma
            )
            for t in turmas
        ]
    except Exception as e:
        logger.exception(f"Erro ao extrair turmas: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/attendance", response_model=AttendancePageResponse)
async def get_attendance_page(
    req: SessionCookies,
    turma_id: str,
    periodo_id: str
):
    """
    Extrai página de lançamento de frequência

    Retorna alunos e suas presenças atuais
    """
    try:
        scraper = SiaScraperService()
        page = await scraper.get_attendance_page(
            req.cookies,
            turma_id,
            periodo_id
        )
        await scraper.close()

        if not page:
            raise HTTPException(status_code=404, detail="Página não encontrada")

        turma = page['turma']

        return AttendancePageResponse(
            professor=turma.get('professor', ''),
            periodo=turma.get('periodo', ''),
            campus=turma.get('campus', ''),
            disciplina=turma.get('disciplina', ''),
            turma=turma.get('turma', ''),
            aulas=[
                AulaResponse(
                    num_seq_data_turma=a.num_seq_data_turma,
                    data=a.data,
                    hora_inicio=a.hora_inicio,
                    hora_fim=a.hora_fim
                )
                for a in page['aulas']
            ],
            students=[
                StudentAttendanceResponse(
                    numero=s['numero'],
                    matricula=s['matricula'],
                    nome=s['nome'],
                    presente=s['presente']
                )
                for s in page['students']
            ]
        )
    except Exception as e:
        logger.exception(f"Erro ao extrair página de presença: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/import-attendance")
async def import_attendance(
    lesson_id: str,
    students_data: list[dict]  # [{'matricula': '...', 'nome': '...', 'presente': True}, ...]
):
    """
    Importa dados de presença do SIA para a aula

    Cria registros de presença para alunos marcados como presentes
    """
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
