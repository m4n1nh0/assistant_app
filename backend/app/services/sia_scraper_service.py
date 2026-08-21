import httpx
import re
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import quote
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
        self.capturing_select = False

    def close(self):
        # A ultima linha da tabela nao tem <tr> seguinte pra fecha-la.
        super().close()
        if self.current_row and 'numero' in self.current_row:
            self.students.append(self.current_row)
            self.current_row = {}

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
    """Serviço para fazer scraping do SIA Estácio

    O SIA fica atras do Akamai Bot Manager (cookies _abck / bm_sz / ak_bmsc),
    que valida o fingerprint do navegador. Por isso o caminho suportado e o
    WebView buscar o HTML e mandar pra ca via `parse_*`; os metodos `fetch_*`
    ficam como fallback e costumam ser desafiados pelo bot manager.

    As paginas sao servidas em windows-1252 (o SIA urlencoda 'Lançamento' como
    'Lan%E7amento'), entao toda resposta e decodificada explicitamente.
    """

    # Mesmo UA do WebView embutido: o _abck do Akamai e emitido pra esse UA.
    USER_AGENT = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36'
    )
    ENCODING = 'cp1252'

    def __init__(self):
        self.base_url = "https://sia.estacio.br"
        self.session = httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={
                'User-Agent': self.USER_AGENT,
                'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
                # As telas do modulo 11 sao carregadas dentro do frameset.
                'Referer': 'https://sia.estacio.br/gen/asp/gen0003c.asp',
            }
        )

    def _decode(self, response: httpx.Response) -> str:
        """Decodifica a resposta como windows-1252 (o SIA nao manda charset)."""
        return response.content.decode(self.ENCODING, errors='replace')

    # ------------------------------------------------------------------
    # Parse: recebe o HTML que o WebView ja buscou (caminho principal)
    # ------------------------------------------------------------------

    def parse_session(self, html: str) -> bool:
        """Diz se o HTML veio de uma sessao autenticada."""
        return 'Pauta Eletr' in html or 'numSeqDataTurma' in html

    def parse_periodos(self, html: str) -> list[dict]:
        """Extrai os períodos acadêmicos do <select> da tela."""
        pattern = r'<option\s+value="(\d+)"[^>]*>([^<]+)</option>'
        return [
            {'value': value, 'label': label.strip()}
            for value, label in re.findall(pattern, html, re.IGNORECASE)
        ]

    def parse_turmas(self, html: str) -> list[SiaTurma]:
        """Extrai as turmas do professor da tabela de seleção."""
        turmas = []

        # Cada linha traz um radio com o num_seq_turma seguido das colunas
        # campus / curso / turno / codigo / disciplina / turma.
        row_pattern = (
            r'<input[^>]*type="radio"[^>]*value="(\d+)"[^>]*>(.*?)</tr>'
        )
        for num_seq_turma, resto in re.findall(
            row_pattern, html, re.IGNORECASE | re.DOTALL
        ):
            colunas = [
                re.sub(r'<[^>]+>', '', celula).replace('&nbsp;', ' ').strip()
                for celula in re.findall(
                    r'<td[^>]*>(.*?)</td>', resto, re.IGNORECASE | re.DOTALL
                )
            ]
            if len(colunas) < 6:
                continue

            turmas.append(SiaTurma(
                num_seq_turma=num_seq_turma,
                campus=colunas[0],
                curso=colunas[1],
                turno=colunas[2],
                codigo=colunas[3],
                disciplina=colunas[4],
                turma=colunas[5],
            ))

        return turmas

    def parse_attendance(self, html: str) -> dict:
        """Extrai a pauta (alunos, aulas e dados da turma) do HTML."""
        parser = SiaParserAttendance()
        parser.feed(html)
        parser.close()

        return {
            'turma': self._extract_turma_info(html),
            'aulas': self._extract_aulas(html),
            'students': parser.students,
            'total': len(parser.students),
        }

    # ------------------------------------------------------------------
    # Fetch: fallback server-side, sujeito ao bot manager do Akamai
    # ------------------------------------------------------------------

    async def test_session(self, cookies: dict) -> bool:
        """Testa se a sessão é válida"""
        try:
            response = await self.session.get(
                f"{self.base_url}/doc/default.asp?p1=11",
                cookies=cookies,
                follow_redirects=True
            )
            return response.status_code == 200 and self.parse_session(
                self._decode(response)
            )
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
            return self.parse_periodos(self._decode(response))
        except Exception as e:
            print(f"Erro ao extrair períodos: {e}")
            return []

    async def get_turmas(self, cookies: dict, periodo_id: str) -> list[SiaTurma]:
        """Extrai turmas do professor para um período"""
        try:
            # O SIA urlencoda o titulo em windows-1252, nao em UTF-8.
            titulo = quote('Lançamento$de$Freqüência', encoding=self.ENCODING)
            response = await self.session.post(
                f"{self.base_url}/gen/asp/gen0020a.asp"
                f"?exe=../../doc/doc0032a.asp&funcao=DOC-25-9&modulo=11"
                f"&titulo={titulo}&nfuncao={titulo}",
                cookies=cookies,
                data={'num_seq_periodo_academico': periodo_id},
            )
            return self.parse_turmas(self._decode(response))
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

            return self.parse_attendance(self._decode(response))
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
