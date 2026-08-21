import httpx
import re
from html.parser import HTMLParser
from typing import Optional
from datetime import datetime
from dataclasses import dataclass

@dataclass
class SiaStudent:
    """Aluno extraído do SIA"""
    numero: int
    matricula: str
    nome: str
    presente: bool
    numSeqAlunoTurma: str

@dataclass
class SiaAula:
    """Aula extraída do SIA"""
    data: str
    hora_inicio: str
    hora_fim: str
    num_seq_data_turma: str

@dataclass
class SiaTurma:
    """Turma extraída do SIA"""
    campus: str
    curso: str
    turno: str
    codigo: str
    disciplina: str
    turma: str
    num_seq_turma: str

class SiaParserAttendance(HTMLParser):
    """Parser para extrair dados de presença da página do SIA"""

    def __init__(self):
        super().__init__()
        self.students = []
        self.current_row = {}
        self.in_table = False
        self.cell_count = 0
        self.capturing_name = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == 'table' and attrs_dict.get('border') == '0':
            # Tabela de alunos
            for attr, value in attrs:
                if attr == 'width' and value == '100%':
                    self.in_table = True
                    return

        if self.in_table:
            if tag == 'tr':
                if self.current_row:  # Salva linha anterior
                    if 'numero' in self.current_row:
                        self.students.append(self.current_row)
                self.current_row = {}
                self.cell_count = 0

            elif tag == 'td' and self.cell_count < 4:
                self.cell_count += 1
                if self.cell_count == 3:  # Coluna de nome
                    self.capturing_name = True

            elif tag == 'input':
                input_name = attrs_dict.get('name', '')
                input_type = attrs_dict.get('type', '')

                # Captura checkbox de presença
                if input_type == 'checkbox' and input_name.startswith('ckdPresenca_'):
                    self.current_row['presente'] = 'checked' in attrs_dict
                    idx = input_name.replace('ckdPresenca_', '')
                    self.current_row['numero'] = int(idx)

                # Captura ID do aluno (hidden field)
                elif input_type == 'hidden' and input_name.startswith('numSeqAlunoTurma_'):
                    self.current_row['numSeqAlunoTurma'] = attrs_dict.get('value', '')

            elif tag == 'select':
                # Captura ID da data da aula
                select_name = attrs_dict.get('name', '')
                if select_name == 'numSeqDataTurma':
                    self.capturing_select = True

    def handle_data(self, data):
        if self.capturing_name and data.strip():
            texto = data.strip()
            # Ignora headers e labels
            if texto and not texto.startswith('Matrícula') and len(texto) > 3:
                self.current_row['nome'] = texto
                self.capturing_name = False

        elif 'numero' in self.current_row and 'matricula' not in self.current_row:
            # Próximo dado é matrícula
            texto = data.strip()
            if texto and texto.isdigit():
                self.current_row['matricula'] = texto

class SiaScraperService:
    """Serviço para fazer scraping do SIA Estácio"""

    def __init__(self):
        self.base_url = "https://sia.estacio.br"
        self.session = httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )

    async def test_session(self, cookies: dict) -> bool:
        """Testa se a sessão é válida"""
        try:
            response = await self.session.get(
                f"{self.base_url}/doc/default.asp?p1=11",
                cookies=cookies,
                follow_redirects=True
            )
            return response.status_code == 200 and 'Pauta Eletrônica' in response.text
        except Exception as e:
            print(f"Erro ao testar sessão: {e}")
            return False

    async def get_periodos(self, cookies: dict) -> list[dict]:
        """Extrai períodos acadêmicos disponíveis"""
        try:
            response = await self.session.get(
                f"{self.base_url}/doc/default.asp?p1=11",
                cookies=cookies
            )

            # Regex para extrair opções do select de períodos
            pattern = r'<option value="(\d+)"[^>]*>([^<]+)</option>'
            matches = re.findall(pattern, response.text)

            return [
                {'value': value, 'label': label.strip()}
                for value, label in matches
            ]
        except Exception as e:
            print(f"Erro ao extrair períodos: {e}")
            return []

    async def get_turmas(self, cookies: dict, periodo_id: str) -> list[SiaTurma]:
        """Extrai turmas do professor para um período"""
        try:
            # Navega para página de seleção de turma
            response = await self.session.post(
                f"{self.base_url}/gen/asp/gen0020a.asp",
                cookies=cookies,
                data={'num_seq_periodo_academico': periodo_id},
                params={
                    'exe': '../../doc/doc0032a.asp',
                    'funcao': 'DOC-25-9',
                    'modulo': '11',
                    'titulo': 'Lançamento$de$Freqüência',
                    'nfuncao': 'Lançamento$de$Freqüência'
                }
            )

            turmas = []
            # Regex para extrair linhas da tabela de turmas
            pattern = r'<tr><td><p[^>]*><input type="radio"[^>]*value="(\d+)"[^>]*></p></td>' \
                     r'<td><p[^>]*><font[^>]*>([^<]+)</font></p></td>' \
                     r'<td><p[^>]*><font[^>]*>([^<]+)</font></p></td>' \
                     r'<td><p[^>]*><font[^>]*>([^<]+)</font></p></td>' \
                     r'<td><p[^>]*><font[^>]*>([^<]+)</font></p></td>' \
                     r'<td><p[^>]*><font[^>]*>([^<]+)</font></p></td>' \
                     r'<td><p[^>]*><font[^>]*>([^<]+)</font></p></td></tr>'

            matches = re.findall(pattern, response.text, re.IGNORECASE)

            for match in matches:
                turma = SiaTurma(
                    num_seq_turma=match[0],
                    campus=match[1].strip(),
                    curso=match[2].strip(),
                    turno=match[3].strip(),
                    codigo=match[4].strip(),
                    disciplina=match[5].strip(),
                    turma=match[6].strip()
                )
                turmas.append(turma)

            return turmas
        except Exception as e:
            print(f"Erro ao extrair turmas: {e}")
            return []

    async def get_attendance_page(
        self,
        cookies: dict,
        turma_id: str,
        periodo_id: str
    ) -> Optional[dict]:
        """Extrai página de lançamento de frequência"""
        try:
            # POST para selecionar turma e avançar
            response = await self.session.post(
                f"{self.base_url}/doc/doc0032a.asp",
                cookies=cookies,
                data={
                    'selecao': turma_id,
                    'num_seq_periodo_academico': periodo_id,
                    'acao': 'Continuar'
                }
            )

            if response.status_code != 200:
                return None

            # Parse da página de presença
            parser = SiaParserAttendance()
            parser.feed(response.text)

            # Extrai informações da turma do formulário
            turma_info = self._extract_turma_info(response.text)
            aulas = self._extract_aulas(response.text)

            return {
                'turma': turma_info,
                'aulas': aulas,
                'students': parser.students,
                'total': len(parser.students)
            }
        except Exception as e:
            print(f"Erro ao extrair página de presença: {e}")
            return None

    def _extract_turma_info(self, html: str) -> dict:
        """Extrai informações da turma do HTML"""
        info = {}

        # Professor
        prof_match = re.search(r'Prof\.:\s*([^\<]+)', html)
        if prof_match:
            info['professor'] = prof_match.group(1).strip()

        # Período
        periodo_match = re.search(r'<input[^>]*name="nom_fantasia"[^>]*value="([^"]+)"', html)
        if periodo_match:
            info['periodo'] = periodo_match.group(1)

        # Campus
        campus_match = re.search(r'<input[^>]*name="nomCampus"[^>]*value="([^"]+)"', html)
        if campus_match:
            info['campus'] = campus_match.group(1)

        # Disciplina
        disc_match = re.search(r'<input[^>]*name="txtDisciplina"[^>]*value="([^"]+)"', html)
        if disc_match:
            info['disciplina'] = disc_match.group(1)

        # Turma
        turma_match = re.search(r'<input[^>]*name="txtTurma"[^>]*value="([^"]+)"', html)
        if turma_match:
            info['turma'] = turma_match.group(1)

        return info

    def _extract_aulas(self, html: str) -> list[SiaAula]:
        """Extrai datas/horas de aula disponíveis"""
        aulas = []
        pattern = r'<option value="(\d+)">([^<]+)</option>'

        matches = re.findall(pattern, html)
        for value, label in matches:
            # Formato: "06/08/2026 - 18:30 - 21:10"
            if ' - ' in label:
                parts = label.split(' - ')
                if len(parts) >= 3:
                    aula = SiaAula(
                        num_seq_data_turma=value,
                        data=parts[0].strip(),
                        hora_inicio=parts[1].strip(),
                        hora_fim=parts[2].strip()
                    )
                    aulas.append(aula)

        return aulas

    async def close(self):
        """Fecha a sessão HTTP"""
        await self.session.aclose()
