"""Leitura do SIA (sistema academico Estacio) para importar turmas e presenca.

O SIA fica atras do Akamai Bot Manager, que valida fingerprint de navegador.
Por isso o caminho suportado inverte o normal: **a interface busca o HTML** com
o WebView autenticado e manda para ca, e o backend so faz o parse (`parse_*`).
Os `get_*`/`fetch_*` continuam existindo como fallback, mas costumam ser
barrados pelo bot manager.

As paginas vem em windows-1252, entao toda resposta e decodificada
explicitamente - decodificar como UTF-8 corrompe acento em nome de aluno.
"""

import httpx
import re
from html import unescape
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

def _texto(html: str) -> str:
    """Remove tags e normaliza entidades/espacos de um trecho de HTML."""
    limpo = re.sub(r'<[^>]+>', ' ', html)
    return unescape(limpo).replace('\xa0', ' ').strip()


def _linhas(html: str) -> list[tuple[str, list[str]]]:
    """Devolve cada <tr> como (html da linha, celulas).

    A linha inteira vem junto porque o SIA poe campos hidden fora das <td>.
    """
    return [
        (
            linha,
            re.findall(
                r'<t[dh][^>]*>(.*?)</t[dh]>', linha, re.IGNORECASE | re.DOTALL
            ),
        )
        for linha in re.findall(
            r'<tr[^>]*>(.*?)</tr>', html, re.IGNORECASE | re.DOTALL
        )
    ]


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
        """Extrai a pauta (alunos, aulas e dados da turma) do HTML.

        A tabela da tela de Lançamento de Frequência tem as colunas
        Nº | Matrícula | Aluno | Presença | Abono | Bloqueado. A leitura e feita
        por posicao de coluna, sem depender do `name` dos checkboxes.
        """
        students = []

        for linha, celulas in _linhas(html):
            if len(celulas) < 4:
                continue

            numero = _texto(celulas[0])
            matricula = _texto(celulas[1])
            nome = _texto(celulas[2])

            # Cabecalho e linhas de layout caem fora deste filtro.
            if not numero.isdigit() or not matricula.isdigit() or not nome:
                continue

            checkbox = re.search(r'<input[^>]*>', celulas[3], re.IGNORECASE)
            if not checkbox:
                continue

            aluno_turma = re.search(
                r'name="numSeqAlunoTurma[^"]*"[^>]*value="([^"]*)"',
                linha,
                re.IGNORECASE,
            )

            students.append({
                'numero': int(numero),
                'matricula': matricula,
                'nome': nome,
                'presente': 'checked' in checkbox.group(0).lower(),
                'numSeqAlunoTurma': aluno_turma.group(1) if aluno_turma else '',
            })

        return {
            'turma': self._extract_turma_info(html),
            'aulas': self._extract_aulas(html),
            'students': students,
            'total': len(students),
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

    def _valor_do_rotulo(self, html: str, rotulo: str) -> str:
        """Le o valor do campo que segue um rotulo da ficha da turma.

        Os `name` dos inputs nao sao estaveis entre telas do SIA, mas o rotulo
        visivel e. O `.` nos padroes cobre acentos que variam com o encoding.
        """
        achado = re.search(
            rotulo + r'.*?<input[^>]*value="([^"]*)"',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        return unescape(achado.group(1)).strip() if achado else ''

    def _extract_turma_info(self, html: str) -> dict:
        """Extrai a ficha da turma (professor, disciplina, turma...) do HTML."""
        # Os rotulos vem acentuados como entidade (`Per&iacute;odo`) ou como
        # byte cp1252, dependendo da tela; resolver as entidades uniformiza.
        texto = unescape(html)

        professor = re.search(r'Prof\.:\s*([^<]+)', texto)
        matricula = re.search(r'Matr.cula:\s*(\d+)', texto)

        return {
            'professor': professor.group(1).strip() if professor else '',
            'matricula_professor': matricula.group(1) if matricula else '',
            'periodo': self._valor_do_rotulo(texto, r'Per.odo\s+Acad.mico'),
            'campus': self._valor_do_rotulo(texto, r'Campus'),
            'disciplina': self._valor_do_rotulo(texto, r'Disciplina'),
            'turma': self._valor_do_rotulo(texto, r'Turma'),
        }

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
