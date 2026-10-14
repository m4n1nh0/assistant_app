# Portal do aluno

Um **link único** para o aluno ver, com a matrícula, o que é dele: resumos das aulas,
resultado dos quizzes em grupo, pontos extras, materiais e, na mentoria, as atividades.

**Onde pegar o link:** Modo Educação → **1. Turmas** → **Portal do aluno** (copiar, QR Code e
abrir/fechar o acesso).

## O que o aluno vê

Depois de digitar a matrícula (pontuação e caixa não importam), o portal junta tudo o que
está ligado às turmas em que ele está, de graduação e de mentoria:

- **Aulas:** os resumos das aulas das turmas dele, do mais recente para o mais antigo, com
  títulos, listas e negrito. Aula sem resumo não aparece. Os resumos de reuniões e
  gravações da mentoria vêm marcados com **Mentoria**.
- **Quizzes:** nos quizzes em grupo em que ele respondeu: o grupo dele, a posição entre os
  grupos, a pontuação do grupo, e a parte dele (pontos, acertos e respostas). É a mesma conta
  do ranking do professor (média do grupo, representante, penalidade por ausência). Quiz ainda
  aberto aparece como **Em andamento**.
- **Pontos:** o total de pontos extras e cada um, com a data, a disciplina e o motivo.
- **Materiais:** os materiais das disciplinas das turmas dele (não os que os grupos enviam),
  com botão **Ler no portal** para ver o texto extraído.
- **Mentoria:** só para quem foi **aceito**: as atividades com a situação de cada uma
  (entregue, entregue com atraso, prazo vencido, pendente) e o atalho para a página de
  entrega.

Tudo é lido ao vivo: o que você gera no app aparece sozinho, sem publicar item a item. O
aluno nunca vê a lista de colegas nem dados de outra turma ou de outro professor.

## Acesso e privacidade

O acesso é **só pela matrícula**, por escolha. Isso tem um custo: quem souber a matrícula de
um colega vê os resultados dele. Para reduzir o risco:

- as consultas são limitadas por IP (30 por minuto), o que barra varredura em massa;
- o portal mostra só o que é do próprio aluno ou coletivo da turma dele;
- **Portal aberto** desliga o acesso inteiro sem apagar nada.

Se for preciso proteger mais, o próximo passo é pedir um código enviado por e-mail (o envio
já existe), pelo menos para pontos e resultados de quiz.

## Rotas

Professor (autenticadas): `GET|PATCH /education/portal-link`.

Públicas, em `/education/portal/{token}`: `GET` (a página), `POST /lookup` e `POST /material`.

## Qual ambiente estou acessando?

O cabeçalho do app mostra uma etiqueta com o ambiente e o endereço do servidor conectado:
**PRODUÇÃO** (discreta, em verde), **LOCAL** ou **HOMOLOGAÇÃO** (em destaque âmbar) e
**SEM CONEXÃO** quando o servidor não responde. O tooltip traz o endereço completo, o commit
em execução e há quanto tempo o servidor está no ar.

O servidor informa o ambiente em `/health/live` (campo `environment`): `APP_ENV` manda quando
definido; sem ele, estar na Railway vale `production` (ou o nome do ambiente da Railway, se
for outro) e fora dela vale `local`. Nas páginas web (portal, quiz, inscrição, chamada), a
barra INTARQ ganha o selo **AMBIENTE LOCAL · TESTE** fora da produção; em produção o aluno
vê só a marca.
