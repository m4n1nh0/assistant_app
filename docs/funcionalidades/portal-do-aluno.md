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
- **Atendimento:** a [agenda de atendimento](agenda-de-atendimento.md): horários semanais e os
  próximos 28 dias, com modalidade, local ou link, dias sem atendimento e horários extras,
  só das faixas que valem para o público do aluno (graduação, mentoria ou todos).

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

## Lacunas conhecidas

O portal junta **graduação e mentoria**, mas ainda não cobre quem também está em **pesquisa**.
Cenário de referência: um aluno que cursa uma disciplina, faz mentoria e participa de uma
pesquisa. Hoje:

| O quê | Situação |
|---|---|
| Disciplina + mentoria no mesmo portal | **Funciona.** A matrícula é a chave e as turmas das duas entram juntas; os pontos extras somam entre elas. |
| Ver as pesquisas em que participa | **Não existe.** O portal não tem aba de pesquisa: o aluno não vê o projeto, o papel dele, as etapas nem os prazos. |
| Entrar no portal sendo só participante de pesquisa (ou só aceito na mentoria, sem registro de aluno) | **Não funciona.** O portal procura a matrícula só entre os alunos cadastrados; quem não tem registro recebe "Não encontrei esta matrícula". Pessoas de fora, sem matrícula, não têm como entrar. |
| Visão do professor sobre um aluno só | **Não existe.** Não há ficha que mostre, de uma pessoa, as disciplinas, a mentoria (inscrição, entregas, faltas) e as pesquisas ao mesmo tempo; é preciso abrir cada aba. |

### Por que acontece

- O participante de pesquisa é um cadastro à parte (`research_participants`). A matrícula dele
  só **marca** se casa com um aluno (`ALUNO CONHECIDO`); nada liga os dois no portal.
- O portal começa pela lista de alunos ativos e, a partir das turmas deles, monta as abas. Quem
  não está em turma nenhuma fica de fora, mesmo tendo inscrição aceita ou pesquisa.
- Cada módulo guarda o próprio vínculo (turma, inscrição, participante); não existe uma
  identidade única da pessoa entre eles.

### O que fazer

1. **Aba "Pesquisa" no portal:** o projeto, o papel do aluno e as etapas com situação e prazo
   (só leitura).
2. **Entrada pela matrícula em qualquer vínculo:** aceitar também quem é participante de
   pesquisa ou aceito na mentoria, mesmo sem registro de aluno, mostrando só as abas que se
   aplicam. Quem é de fora e não tem matrícula precisa de outro caminho (por exemplo, um
   código enviado por e-mail).
3. **Ficha do aluno para o professor:** uma tela única por pessoa, juntando disciplinas,
   mentoria e pesquisas, a partir da matrícula.
4. **Reconciliar nomes e e-mails** entre os cadastros quando a mesma pessoa aparece com dados
   diferentes em cada módulo.

Ver também [pesquisas-cientificas.md](pesquisas-cientificas.md) e
[inscricao-mentorias.md](inscricao-mentorias.md).
