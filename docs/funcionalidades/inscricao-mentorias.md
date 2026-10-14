# Inscrição em mentorias

Você descreve a mentoria, a **IA monta o formulário**, você ajusta e publica um **link**. Quem
se inscreve aparece numa lista; ao aceitar, a mentoria vira uma **disciplina com uma turma** e
cada aceito entra nela como aluno.

**Onde:** Modo Educação → **2. Mentorias** (e um cartão na Visão geral).

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

## Atividades e entregas

Cada mentoria tem as suas **atividades**, que os alunos aceitos entregam por um link próprio.

**Onde:** na mesma aba, logo abaixo da lista de inscritos (**Atividades e entregas**).

1. **Nova atividade.** Título, instruções e, se quiser, **prazo** (data e hora). Com prazo,
   dá para ligar o **lembrete por e-mail**, enviado uma vez, cerca de 24 h antes de vencer,
   só para quem ainda não entregou. Mudar o prazo rearma o lembrete.
2. **Link de entrega.** Um por mentoria, mostrado no painel (copiar). O aluno abre, digita a
   matrícula e vê as atividades. **Só entra quem foi aceito**: pendente, recusado ou removido
   recebe uma mensagem explicando. O e-mail de aceite já leva esse link (quando o servidor
   tem endereço público configurado).
3. **Entrega.** Texto (até 10.000 caracteres, serve para um link de repositório) e/ou arquivo
   (PDF, DOCX, PPTX, XLSX, TXT, MD, ZIP, PNG, JPG; até 8 MB). Reenviar **substitui** a entrega
   anterior. Depois do prazo ainda dá para entregar, e a entrega fica marcada como
   **atrasada**.
4. **Acompanhar.** A tabela **Quem entregou** cruza aceitos e atividades: entregue (verde),
   atrasada (amarelo), vencida sem entrega (vermelho) e pendente (cinza). Clicar numa
   entrega abre o texto e permite **baixar o arquivo**. O painel se atualiza sozinho.
5. **Quem está faltando.** Lista os aceitos que não entregaram as **últimas N atividades
   vencidas** (N de 1 a 4; padrão 2). A contagem vai da atividade vencida mais recente para
   trás, e qualquer entrega, mesmo atrasada, zera a sequência. **O app só sugere**: o botão
   *Tirar da mentoria* pede confirmação e põe o aluno como removido (sai da turma, com o
   histórico guardado; dá para aceitar de novo).

O arquivo entregue fica guardado no banco (não só o texto), por isso o limite de 8 MB.

## Rotas

Do professor (autenticadas), em `/education/mentorships`: `POST /generate-fields`,
`POST` (criar), `GET` (listar), `PATCH /{id}`, `DELETE /{id}`, `GET /{id}/signups`,
`POST /{id}/signups/status`, `GET /{id}/export`; e, para atividades, `GET|POST
/{id}/activities`, `PATCH|DELETE /activities/{id}`, `GET /{id}/deliveries`,
`GET /{id}/at-risk?misses=N`, `GET /deliveries/{id}` e `GET /deliveries/{id}/file`.

Públicas: `/education/mentorship-signup/{token}` (inscrição: `GET` a página, `POST` enviar) e
`/education/mentorship-deliver/{token}` (entrega: `GET` a página, `POST /lookup`, `POST /send`).

## Ainda não existe

Plano de encontros: cruzar os horários livres dos inscritos com as suas noites livres e o
sábado de manhã para sugerir o dia dos encontros.
