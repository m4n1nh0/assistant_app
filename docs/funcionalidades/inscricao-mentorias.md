# Inscrição em mentorias

Você descreve a mentoria, a **IA monta o formulário**, você ajusta e publica um **link**. Quem
se inscreve aparece numa lista; ao aceitar, a mentoria vira uma **disciplina com uma turma** e
cada aceito entra nela como aluno.

**Onde:** Modo Educação → **11. Mentorias** (e um cartão na Visão geral).

## Fluxo

1. **Descrever.** Em **Nova mentoria**, dê o nome e descreva o tema (público, frequência,
   objetivo). **Gerar campos com IA** propõe as perguntas.
2. **Ajustar.** Edite o texto de cada pergunta, o tipo, se é obrigatória, remova ou acrescente.
   Opcionalmente defina **vagas** e **prazo** (vale até o fim do dia escolhido).
3. **Publicar.** Ao criar, o card mostra o link e o QR Code. Mande para os alunos.
4. **Acompanhar.** A lista mostra cada inscrito com as respostas. **Aceitar** põe o aluno na
   turma da mentoria; **Recusar** libera a vaga; **Remover da turma** tira quem não está
   entregando (o aluno fica inativo na turma, sem apagar o histórico).
5. **Exportar.** **Copiar CSV** leva os inscritos para uma planilha (separador `;`).

## O que o inscrito preenche

Uma página pública, sem login. **Sempre** pede:

- matrícula (obrigatória, **não é validada**: o app não tem como),
- nome completo,
- e-mail,
- telefone com DDD.

Os demais campos vêm do formulário. Se a IA não responder, entram os padrão: **idade, curso,
período e horários livres**.

Tipos de campo: texto curto, texto longo, número, escolha de opção e **horários livres**
(grade de dias da semana × manhã/tarde/noite, guardada como `sab-manha`, `seg-noite`...).

- A mesma matrícula não se inscreve duas vezes (pontuação e caixa não importam).
- Ao enviar, o inscrito recebe um **e-mail de confirmação**, se o envio de e-mail estiver
  configurado (o mesmo do convite de cadastro). Falha no e-mail não desfaz a inscrição.

## Aluno conhecido

Como a matrícula não é validada, a inscrição é **marcada** (`ALUNO CONHECIDO`) quando a
matrícula casa com um aluno ativo de alguma turma do **mesmo semestre** do formulário. Quem
não casa pode ser aceito do mesmo jeito: a marca só ajuda a reconhecer quem é de fora.

## Vagas e prazo

O link fecha sozinho quando as vagas acabam ou o prazo termina; também dá para **Fechar
inscrições** à mão e reabrir. Inscrições pendentes e aceitas ocupam vaga; **recusar** ou
**remover** libera.

## Ao aceitar

- Cria a disciplina `MENTORIA - <nome>` e a turma dela, uma vez; os seguintes entram na mesma.
- Cada aceito vira aluno da turma (com a matrícula informada). Dali em diante valem presença,
  pontos, quiz e **reunião online** como em qualquer turma.
- Aceitar de novo quem foi removido reativa o mesmo aluno, sem duplicar.
- Apagar o formulário não apaga a turma nem os alunos já aceitos.

## Rotas

Do professor (autenticadas), em `/education/mentorships`: `POST /generate-fields`,
`POST` (criar), `GET` (listar), `PATCH /{id}`, `DELETE /{id}`, `GET /{id}/signups`,
`POST /{id}/signups/status`, `GET /{id}/export`.

Públicas, em `/education/mentorship-signup/{token}`: `GET` (a página) e `POST` (enviar).

## Ainda não existe

Plano de encontros (cruzar os horários livres dos inscritos com os seus), entrega de
atividades pelo link e a regra para tirar do grupo quem não entrega ficam para as próximas
fases.
