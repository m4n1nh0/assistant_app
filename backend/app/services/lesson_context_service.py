"""Ancoragem relacional da pergunta antes de qualquer busca vetorial.

O indice vetorial nao sabe dizer "essa disciplina nao existe" nem "nao houve
aula nesse dia": ele sempre devolve o trecho mais parecido que encontrar, e num
pedido sobre uma aula que nunca aconteceu isso vira resposta inventada. Quem
sabe dessas coisas e o banco relacional, onde disciplina, aula e transcricao sao
registros com dono e data.

Este modulo faz essa verificacao - disciplina citada, data pedida, aula gravada,
transcricao disponivel - e devolve duas coisas:

- o escopo (`lesson_ids`) para restringir a busca semantica aa aula certa, em
  vez de varrer o semestre inteiro atras de parafrase;
- o texto que conta ao modelo o que foi confirmado, inclusive quando a resposta
  e "nao ha aula registrada nessa data", que e a informacao que faltava.

Nada aqui consulta vector store: a busca continua no `RetrievalGateway`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Sequence

import pytz
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import DisciplineModel, LessonModel, LessonSegmentModel
from ..ports.retrieval import RetrievedChunk

# Quantas aulas entram no escopo quando a pergunta cita a disciplina mas nao a
# data. Mais que isso dilui a busca e devolve trecho de outra semana.
_RECENT_LESSONS = 3
# Janela varrida para achar a aula mais recente de uma disciplina.
_LOOKBACK_LESSONS = 60
# Teto do resumo colado no prompt: o resumo ja e condensado, mas aula longa
# gera resumo longo e ele nao pode comer o orcamento do historico.
_SUMMARY_CHARS = 2000

_STOPWORDS = frozenset({
    "de", "da", "do", "das", "dos", "e", "em", "a", "o", "as", "os",
    "na", "no", "para", "com", "sobre", "aula", "aulas", "disciplina",
    "materia", "turma", "prof", "professor", "professora",
})

_WEEKDAYS = {
    "segunda": 0, "terca": 1, "quarta": 2, "quinta": 3,
    "sexta": 4, "sabado": 5, "domingo": 6,
}

_PREAMBLE = "\n\nVerificacao no cadastro de aulas deste professor (banco relacional):\n"

_NO_GUESSING = (
    "Responda apenas com o que estiver confirmado acima e nos trechos de "
    "transcricao. Se a aula, a data ou o conteudo pedido nao aparecerem, diga "
    "isso ao usuario em vez de supor o que foi dado em aula.\n"
)

_ACCESS_NOTE = (
    "Voce tem acesso as aulas gravadas e transcritas deste professor: elas vem "
    "do proprio aplicativo e foram verificadas acima. Nunca peca captura de "
    "tela, print, janela de editor ou que o usuario cole o material da aula - "
    "esse caminho serve para conteudo da tela do PC, nao para aula. Se faltar "
    "disciplina ou data para localizar a aula, peca exatamente esses dois "
    "dados.\n"
)

# Pedido de visao geral: quem pergunta "do que tratou a aula" quer a aula
# inteira, e nao os seis trechos mais parecidos com a frase da pergunta - que,
# numa pergunta assim, nao se parece com trecho nenhum da transcricao.
_OVERVIEW_PATTERNS = (
    r"\bresum\w+", r"\btranscric\w+", r"\bdescric\w+", r"\batividade\w*\b",
    r"\bpauta\b", r"\btopico\w*\b", r"\bassunto\w*\b", r"\bconteud\w+",
    r"\bdo que (?:tratou|falei|falamos|foi|se tratou)\b",
    r"\bsobre o que\b", r"\bcomo foi a aula\b", r"\bmaterial da aula\b",
    r"\bo que (?:dei|passei|expliquei|ensinei|vimos|falei|falamos|"
    r"aconteceu|rolou)\b",
    r"\bme (?:conta|fala|passa|mostra)\b", r"\bacess\w+",
)

# Marcas de referencia a algo ja dito. Sozinhas nao valem nada; servem para
# decidir se vale herdar disciplina e data das mensagens anteriores.
#
# Os padroes sao estreitos de proposito. `_normalize` tira o acento, entao "e"
# e "e" viram a mesma palavra: um marcador solto como "e a" casaria com "qual e
# a capital da Franca?" e colaria contexto de aula numa pergunta que nao tem
# nada com aula. Por isso a conjuncao so vale no comeco da frase.
_FOLLOW_UP_PATTERNS = (
    r"\b(?:dela|nela|dele|nele|disso|nisso|dessa|nessa|desse|nesse)\b",
    r"\b(?:essa|esse|isso|mesma|mesmo)\s+"
    r"(?:aula|materia|disciplina|turma|conteudo|atividade|assunto)\b",
    r"^e\s+(?:a|o|as|os|sobre|quanto|quando|qual|quais)\b",
    r"\bmais detalhes?\b",
    r"\b(?:continua|detalha|aprofunda|expande|explica melhor)\b",
)


@dataclass(frozen=True)
class LessonHit:
    """Uma aula encontrada no banco, com o que basta para citar a fonte."""

    lesson_id: str
    discipline: str
    day: date
    title: str = ""
    class_group: str = ""
    status: str = ""
    segments: int = 0
    summary: str = ""

    @property
    def label(self) -> str:
        parts = [self.discipline or "aula", self.day.strftime("%d/%m/%Y")]
        if self.class_group:
            parts.append(f"turma {self.class_group}")
        return ", ".join(parts)


@dataclass(frozen=True)
class LessonScope:
    """O que o banco confirmou sobre a pergunta.

    Attributes:
        catalog: disciplinas ativas do professor, para o modelo saber o que
            existe quando o usuario citar um nome parecido.
        disciplines: disciplinas do catalogo reconhecidas na pergunta.
        day: data pedida, ja no fuso do usuario.
        day_label: como a data foi pedida ("hoje", "ontem"), quando foi por
            palavra em vez de numero.
        lessons: aulas que batem com disciplina e/ou data.
        latest: aula mais recente da disciplina, preenchida so quando a data
            pedida nao tem aula - e o que permite dizer "a ultima foi em X".
        inherited: diz que disciplina e data vieram das mensagens anteriores da
            conversa, e nao desta. O modelo precisa saber disso para confirmar a
            aula com o usuario em vez de afirmar de que aula esta falando.
        future: a data pedida ainda nao chegou. Sem isso o modelo so le "nenhuma
            aula nessa data" e pede mais detalhes, quando o motivo e simples.
        swapped: aulas na data com dia e mes invertidos ("09/10" lido como 10/09),
            preenchidas so quando a data pedida nao tem aula. E o erro de
            digitacao mais comum, e a aula certa costuma estar ali.
    """

    catalog: tuple[str, ...] = ()
    disciplines: tuple[str, ...] = ()
    day: date | None = None
    day_label: str = ""
    lessons: tuple[LessonHit, ...] = ()
    latest: LessonHit | None = None
    inherited: bool = False
    future: bool = False
    swapped: tuple[LessonHit, ...] = ()

    @property
    def transcribed(self) -> tuple[LessonHit, ...]:
        """Aulas do escopo que tem transcricao gravada."""
        return tuple(item for item in self.lessons if item.segments)

    @property
    def lesson_ids(self) -> tuple[str, ...]:
        """Ids para restringir a busca vetorial."""
        return tuple(item.lesson_id for item in self.transcribed)

    @property
    def anchored(self) -> bool:
        """Diz se a pergunta encostou em algo do cadastro de aulas."""
        return bool(self.disciplines or self.lessons or self.day)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (value or "").lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _tokens(value: str) -> tuple[str, ...]:
    """Palavras significativas de um rotulo, sem acento e sem conectivo."""
    return tuple(
        token
        for token in re.findall(r"[a-z0-9]+", _normalize(value))
        if len(token) > 2 and token not in _STOPWORDS
    )


def _timezone(name: str):
    try:
        return pytz.timezone(name)
    except pytz.UnknownTimeZoneError:
        return pytz.timezone("America/Sao_Paulo")


def _local_now(timezone_name: str, now: datetime | None = None) -> datetime:
    tz = _timezone(timezone_name)
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(tz)


def _local_date(value: datetime | None, timezone_name: str) -> date | None:
    """Data da aula no fuso do professor.

    `started_at` e gravado em UTC; comparar direto com o dia local erra a aula
    da noite, que em UTC ja caiu no dia seguinte.
    """
    if value is None:
        return None
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(_timezone(timezone_name)).date()


def _numeric_day(text: str, today: date) -> date | None:
    iso = re.search(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)", text)
    if iso:
        try:
            return date(*map(int, iso.groups()))
        except ValueError:
            return None
    numeric = re.search(r"(?<!\d)(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?(?!\d)", text)
    if numeric:
        day, month, year = numeric.groups()
        parsed_year = int(year) if year else today.year
        if parsed_year < 100:
            parsed_year += 2000
        try:
            return date(parsed_year, int(month), int(day))
        except ValueError:
            return None
    bare = re.search(r"\bdia\s+(\d{1,2})(?!\d)", text)
    if bare:
        try:
            return date(today.year, today.month, int(bare.group(1)))
        except ValueError:
            return None
    return None


def _swapped_day(text: str, day: date) -> date | None:
    """A data com dia e mes invertidos, quando a pergunta escreveu dd/mm."""
    if re.search(r"(?<!\d)\d{4}-\d{1,2}-\d{1,2}(?!\d)", text):
        return None
    if not re.search(r"(?<!\d)\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?(?!\d)", text):
        return None
    if day.day > 12 or day.day == day.month:
        return None
    try:
        return date(day.year, day.day, day.month)
    except ValueError:
        return None


def parse_day(
    message: str,
    *,
    timezone_name: str = "America/Sao_Paulo",
    now: datetime | None = None,
) -> tuple[date | None, str]:
    """Data citada na pergunta, no fuso do professor.

    A data escrita em numero ganha da palavra: quem digita "14/09" esta sendo
    mais especifico que quem digita "hoje", e nas mensagens reais os dois
    aparecem juntos ("minha aula de hoje, 14/09").

    Returns:
        A data e o rotulo de como ela foi pedida ("hoje", "ontem", ""), ou
        `(None, "")` quando a pergunta nao fala de dia nenhum.
    """
    text = _normalize(message)
    local_today = _local_now(timezone_name, now).date()

    explicit = _numeric_day(text, local_today)
    if explicit:
        return explicit, ""
    if re.search(r"\banteontem\b", text):
        return local_today - timedelta(days=2), "anteontem"
    if re.search(r"\bontem\b", text):
        return local_today - timedelta(days=1), "ontem"
    if re.search(r"\bhoje\b", text):
        return local_today, "hoje"
    if re.search(r"\bdepois de amanha\b", text):
        return local_today + timedelta(days=2), "depois de amanha"
    if re.search(r"\bamanha\b", text):
        return local_today + timedelta(days=1), "amanha"

    weekday = re.search(
        r"\b(segunda|terca|quarta|quinta|sexta|sabado|domingo)(?:-feira|\s+feira)?\b",
        text,
    )
    if weekday:
        # Aula tem transcricao depois de acontecer: o dia da semana citado e a
        # ocorrencia mais recente, nao a proxima.
        target = _WEEKDAYS[weekday.group(1)]
        return local_today - timedelta(days=(local_today.weekday() - target) % 7), ""
    return None, ""


def wants_overview(message: str) -> bool:
    """Diz se o pedido e sobre a aula inteira, e nao sobre um ponto dela.

    Vale a distincao porque a busca vetorial responde mal a esse tipo de
    pergunta: "me ajuda com a descricao da atividade" nao se parece com nenhum
    trecho da fala do professor, entao os vizinhos mais proximos vem por acaso.
    Para esses pedidos, resumo e transcricao amostrada valem mais que top-k.
    """
    text = _normalize(message)
    return any(re.search(pattern, text) for pattern in _OVERVIEW_PATTERNS)


def is_follow_up(message: str) -> bool:
    """Diz se a mensagem so faz sentido a luz do que ja foi conversado.

    "Voce poderia acessar a transcricao?" nao nomeia disciplina nem data: a aula
    esta na mensagem anterior. Sem isso, cada pergunta da sequencia perde a
    ancora e o assistente volta a pedir o que o usuario ja disse.
    """
    text = _normalize(message)
    if len(text.split()) > 14:
        return False
    return any(re.search(pattern, text) for pattern in _FOLLOW_UP_PATTERNS)


def _label(row: DisciplineModel) -> str:
    code = str(row.code or "").strip()
    name = str(row.name or "").strip()
    return " - ".join(part for part in (code, name) if part)


def _mentioned(parts: Iterable[str], message: str) -> bool:
    """Diz se algum dos rotulos aparece na pergunta.

    Casa por texto inteiro ("banco de dados" dentro da frase) e por conjunto de
    palavras, que e o que salva "fizemos normalizacao em Banco de Dados II"
    quando o cadastro guarda "ARA0040 - BANCO DE DADOS".
    """
    normalized = _normalize(message)
    asked = set(_tokens(message))
    for part in parts:
        candidate = _normalize(part).strip()
        if len(candidate) >= 4 and candidate in normalized:
            return True
        tokens = _tokens(part)
        if tokens and all(token in asked for token in tokens):
            return True
    return False


def _same_discipline(first: str, second: str) -> bool:
    """Compara o rotulo da aula com o do catalogo, que nem sempre sao iguais.

    A aula pode ter sido gravada como "BANCO DE DADOS" e o catalogo guardar
    "ARA0040 - BANCO DE DADOS": um e subconjunto do outro.
    """
    left, right = set(_tokens(first)), set(_tokens(second))
    if not left or not right:
        return False
    return left <= right or right <= left


async def _segment_counts(db: AsyncSession, lesson_ids: Sequence[str]) -> dict[str, int]:
    if not lesson_ids:
        return {}
    rows = await db.execute(
        select(LessonSegmentModel.lesson_id, func.count(LessonSegmentModel.id))
        .where(LessonSegmentModel.lesson_id.in_(list(lesson_ids)))
        .group_by(LessonSegmentModel.lesson_id)
    )
    return {str(lesson_id): int(total) for lesson_id, total in rows.all()}


def _hit(row: LessonModel, day: date, segments: int) -> LessonHit:
    return LessonHit(
        lesson_id=str(row.id),
        discipline=str(row.discipline or "").strip(),
        day=day,
        title=str(row.title or "").strip(),
        class_group=str(row.class_group or "").strip(),
        status=str(row.status or "").strip(),
        segments=segments,
        summary=str(row.summary or "").strip(),
    )


async def _lessons_of_day(
    db: AsyncSession,
    *,
    tutor_id: str,
    day: date,
    timezone_name: str,
) -> list[tuple[LessonModel, date]]:
    """Aulas do dia pedido, comparando a data ja convertida para o fuso local.

    A janela no SQL e propositalmente folgada (um dia para cada lado) e o corte
    fino acontece em Python: a coluna e datetime ingenuo em UTC, e cada banco
    trata diferente a comparacao com fuso.
    """
    tz = _timezone(timezone_name)
    start = tz.localize(datetime.combine(day - timedelta(days=1), time.min))
    end = tz.localize(datetime.combine(day + timedelta(days=2), time.min))
    rows = await db.scalars(
        select(LessonModel)
        .where(
            LessonModel.tutor_id == tutor_id,
            LessonModel.started_at >= start.astimezone(timezone.utc).replace(tzinfo=None),
            LessonModel.started_at < end.astimezone(timezone.utc).replace(tzinfo=None),
        )
        .order_by(LessonModel.started_at)
    )
    return [
        (row, local)
        for row in rows.all()
        if (local := _local_date(row.started_at, timezone_name)) == day
    ]


async def _recent_lessons(
    db: AsyncSession,
    *,
    tutor_id: str,
    timezone_name: str,
) -> list[tuple[LessonModel, date]]:
    rows = await db.scalars(
        select(LessonModel)
        .where(LessonModel.tutor_id == tutor_id)
        .order_by(LessonModel.started_at.desc())
        .limit(_LOOKBACK_LESSONS)
    )
    return [
        (row, local)
        for row in rows.all()
        if (local := _local_date(row.started_at, timezone_name)) is not None
    ]


async def resolve(
    db: AsyncSession,
    *,
    tutor_id: str,
    message: str,
    context: Sequence[str] = (),
    timezone_name: str = "America/Sao_Paulo",
    now: datetime | None = None,
) -> LessonScope:
    """Confere a pergunta contra o cadastro de disciplinas e aulas.

    Quando a mensagem sozinha nao nomeia disciplina nem data, o que ja foi dito
    na conversa entra como segunda tentativa. Numa sequencia real a aula e
    nomeada uma vez e as perguntas seguintes falam dela por pronome - sem essa
    herança, so a primeira pergunta encontra a aula e o assistente volta a pedir
    o que o usuario ja tinha dito.

    Args:
        db: sessao aberta pelo chamador.
        tutor_id: perfil dono das aulas.
        message: pergunta em linguagem natural.
        context: falas anteriores da conversa, da mais antiga para a mais nova.
            Passe so quando a mensagem atual for mesmo sobre aula; herdar a
            ancora numa pergunta de outro assunto colaria contexto errado.
        timezone_name: fuso do professor, usado para "hoje" e para a data da aula.
        now: instante de referencia, para teste.

    Returns:
        O escopo com disciplina, data e aulas confirmadas, com `inherited` a
        dizer se a ancora veio da conversa. Escopo vazio quando nem a mensagem
        nem o contexto encostam no cadastro.
    """
    scope = await _resolve_text(
        db, tutor_id=tutor_id, text=message, timezone_name=timezone_name, now=now
    )
    if scope.disciplines or scope.day or not context:
        return scope

    remembered = await _resolve_text(
        db,
        tutor_id=tutor_id,
        text="\n".join([*context, message]),
        timezone_name=timezone_name,
        now=now,
    )
    if not remembered.disciplines and not remembered.day:
        return scope
    return replace(remembered, inherited=True)


async def _resolve_text(
    db: AsyncSession,
    *,
    tutor_id: str,
    text: str,
    timezone_name: str,
    now: datetime | None,
) -> LessonScope:
    """Uma passada de casamento sobre um texto - a mensagem ou ela mais o contexto."""
    message = text
    if not tutor_id or not (message or "").strip():
        return LessonScope()

    rows = (await db.scalars(
        select(DisciplineModel)
        .where(
            DisciplineModel.tutor_id == tutor_id,
            DisciplineModel.active.is_(True),
        )
        .order_by(DisciplineModel.name)
    )).all()
    catalog = tuple(label for row in rows if (label := _label(row)))
    matched = tuple(
        label
        for row in rows
        if (label := _label(row))
        and _mentioned((str(row.name or ""), str(row.code or ""), label), message)
    )

    day, day_label = parse_day(message, timezone_name=timezone_name, now=now)

    if day is not None:
        candidates = await _lessons_of_day(
            db, tutor_id=tutor_id, day=day, timezone_name=timezone_name
        )
    elif matched:
        candidates = await _recent_lessons(
            db, tutor_id=tutor_id, timezone_name=timezone_name
        )
    else:
        # Sem disciplina e sem data nao ha o que ancorar: a busca vetorial
        # generica ja atende, e varrer aula aqui seria SQL a toa.
        return LessonScope(catalog=catalog)

    if matched:
        selected = [
            item
            for item in candidates
            if any(_same_discipline(str(item[0].discipline or ""), label) for label in matched)
        ]
    else:
        # A aula pode ter sido gravada com uma disciplina que nao esta no
        # catalogo; se o rotulo dela aparece na pergunta, ele vale como recorte.
        by_lesson = [
            item for item in candidates if _mentioned((str(item[0].discipline or ""),), message)
        ]
        # Sem nenhum recorte de disciplina, a pergunta e sobre o dia
        # ("o que eu dei ontem?") e todas as aulas dele entram.
        selected = by_lesson or list(candidates)
    if day is None:
        selected = selected[:_RECENT_LESSONS]

    counts = await _segment_counts(db, [str(row.id) for row, _ in selected])
    lessons = tuple(
        _hit(row, local, counts.get(str(row.id), 0)) for row, local in selected
    )

    def _of_discipline(items):
        if not matched:
            return list(items)
        return [
            item
            for item in items
            if any(_same_discipline(str(item[0].discipline or ""), label) for label in matched)
        ]

    today = _local_now(timezone_name, now).date()
    swapped: tuple[LessonHit, ...] = ()
    if day is not None and not lessons:
        alternative = _swapped_day(_normalize(message), day)
        if alternative is not None and alternative <= today:
            found = _of_discipline(await _lessons_of_day(
                db, tutor_id=tutor_id, day=alternative, timezone_name=timezone_name
            ))
            if found:
                counted = await _segment_counts(db, [str(row.id) for row, _ in found])
                swapped = tuple(
                    _hit(row, local, counted.get(str(row.id), 0)) for row, local in found
                )

    latest: LessonHit | None = None
    if day is not None and not lessons and matched:
        recent = await _recent_lessons(db, tutor_id=tutor_id, timezone_name=timezone_name)
        previous = [
            item
            for item in recent
            if any(_same_discipline(str(item[0].discipline or ""), label) for label in matched)
            and item[1] <= day
        ]
        if previous:
            row, local = previous[0]
            counted = await _segment_counts(db, [str(row.id)])
            latest = _hit(row, local, counted.get(str(row.id), 0))

    return LessonScope(
        catalog=catalog,
        disciplines=matched,
        day=day,
        day_label=day_label,
        lessons=lessons,
        latest=latest,
        future=day is not None and day > today,
        swapped=swapped,
    )


def describe(scope: LessonScope) -> str:
    """Monta o bloco de fatos confirmados que entra no prompt.

    E aqui que o assistente ganha o "nao": sem este texto o modelo recebe so os
    trechos que a busca achou e nao tem como saber que a aula pedida nao existe.
    """
    if not scope.catalog and not scope.anchored:
        return ""

    lines: list[str] = []
    if scope.catalog:
        lines.append(f"- Disciplinas ativas: {', '.join(scope.catalog)}.")
    else:
        lines.append("- Nenhuma disciplina ativa cadastrada para este professor.")

    origin = "nas mensagens anteriores" if scope.inherited else "na pergunta"
    if scope.disciplines:
        lines.append(f"- Disciplina citada {origin}: {', '.join(scope.disciplines)}.")
    else:
        lines.append("- Nenhuma disciplina do cadastro foi reconhecida na pergunta.")

    if scope.day:
        asked = scope.day.strftime("%d/%m/%Y")
        if scope.day_label:
            asked = f"{asked} ({scope.day_label})"
        lines.append(f"- Data pedida {origin}: {asked}.")

    if scope.inherited:
        lines.append(
            "- Essa aula veio do que ja foi dito nesta conversa, e nao da ultima "
            "mensagem: confirme com o usuario que e dela que voce esta falando."
        )

    if scope.lessons:
        for lesson in scope.lessons:
            state = (
                f"{lesson.segments} trecho(s) transcrito(s)"
                if lesson.segments
                else "sem transcricao gravada"
            )
            title = f' - "{lesson.title}"' if lesson.title else ""
            lines.append(f"- Aula registrada: {lesson.label}{title}, {state}.")
        if not scope.transcribed:
            lines.append(
                "- A aula existe no cadastro, mas nao ha transcricao para "
                "consultar. Avise o usuario e nao descreva o conteudo dela."
            )
    elif scope.day:
        lines.append("- Nenhuma aula registrada nessa data para esse recorte.")
        if scope.future:
            lines.append(
                "- Essa data ainda nao chegou: aula futura nao tem gravacao nem "
                "resumo. Diga isso ao usuario em vez de pedir mais detalhes."
            )
        if scope.swapped:
            day = scope.swapped[0].day.strftime("%d/%m/%Y")
            found = "; ".join(lesson.label for lesson in scope.swapped)
            lines.append(
                f"- Com dia e mes invertidos ({day}) ha aula registrada: {found}. "
                "Pergunte se o usuario quis dizer essa data antes de falar do "
                "conteudo dela."
            )
        if scope.latest:
            lines.append(
                f"- Aula mais recente dessa disciplina: {scope.latest.label}."
            )
    elif scope.disciplines:
        lines.append("- Nenhuma aula registrada para essa disciplina.")

    return _PREAMBLE + "\n".join(lines) + "\n" + _ACCESS_NOTE + _NO_GUESSING


def summary_chunks(scope: LessonScope) -> list[RetrievedChunk]:
    """Resumo ja gerado das aulas do escopo, como fonte de contexto.

    O resumo cobre a aula inteira, enquanto o trecho vetorial cobre um ponto
    dela. Para pedido de visao geral - "do que tratou a aula", "monta a
    descricao da atividade" - ele responde melhor do que qualquer recorte.
    """
    return [
        RetrievedChunk(
            content=lesson.summary[:_SUMMARY_CHARS],
            score=1.0,
            source=lesson.discipline,
            reference=f"resumo da aula - {lesson.label}",
            metadata={"lesson_id": lesson.lesson_id, "lesson_date": lesson.day.isoformat()},
        )
        for lesson in scope.lessons
        if lesson.summary
    ]


def _spread(items: list[str], count: int) -> list[str]:
    """Escolhe `count` itens distribuidos ao longo da lista, mantendo a ordem.

    Cortar os primeiros seria pegar so a abertura da aula - chamada, avisos,
    "bom dia, vamos comecar" -, que e justamente a parte que nao responde nada.
    """
    if count <= 0 or not items:
        return []
    if len(items) <= count:
        return items
    step = len(items) / count
    return [items[int(index * step)] for index in range(count)]


async def transcript_chunks(
    db: AsyncSession,
    scope: LessonScope,
    *,
    limit: int = 6,
) -> list[RetrievedChunk]:
    """Trechos da transcricao lidos direto do banco, cobrindo a aula toda.

    Serve a dois casos: o indice vetorial sem o que devolver - a aula pode estar
    transcrita no MySQL e ausente do Qdrant, por indexacao atrasada ou embedding
    trocado - e o pedido de visao geral, em que top-k de similaridade e a
    ferramenta errada. Nos dois, a aula ja foi identificada por disciplina e
    data, entao ler a fonte e melhor do que responder sem ela.
    """
    lessons = scope.transcribed
    if not lessons or limit <= 0:
        return []
    by_id = {lesson.lesson_id: lesson for lesson in lessons}
    # Duas consultas de proposito: a primeira traz so id e ordem, para escolher
    # a amostra sem carregar a transcricao inteira de uma aula de duas horas.
    index = await db.execute(
        select(LessonSegmentModel.id, LessonSegmentModel.lesson_id)
        .where(LessonSegmentModel.lesson_id.in_(list(by_id)))
        .order_by(LessonSegmentModel.lesson_id, LessonSegmentModel.sequence)
    )
    by_lesson: dict[str, list[str]] = {}
    for segment_id, lesson_id in index.all():
        by_lesson.setdefault(str(lesson_id), []).append(str(segment_id))

    share = max(1, limit // max(1, len(by_lesson)))
    chosen = [
        segment_id
        for ids in by_lesson.values()
        for segment_id in _spread(ids, share)
    ][:limit]
    if not chosen:
        return []

    rows = await db.scalars(
        select(LessonSegmentModel)
        .where(LessonSegmentModel.id.in_(chosen))
        .order_by(LessonSegmentModel.lesson_id, LessonSegmentModel.sequence)
    )
    return [
        RetrievedChunk(
            content=text,
            score=1.0,
            source=by_id[str(segment.lesson_id)].discipline,
            reference=by_id[str(segment.lesson_id)].label,
            metadata={
                "lesson_id": str(segment.lesson_id),
                "lesson_date": by_id[str(segment.lesson_id)].day.isoformat(),
                "sequence": int(segment.sequence or 0),
            },
        )
        for segment in rows.all()
        if str(segment.lesson_id) in by_id and (text := str(segment.text or "").strip())
    ]
