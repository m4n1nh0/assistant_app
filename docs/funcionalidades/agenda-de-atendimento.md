# Agenda de atendimento

Você publica quando atende, o aluno vê no portal e o plano de encontros da mentoria usa a
mesma agenda para sugerir o melhor dia.

**Onde:** Modo Educação → **4. Atendimento**.

## O que se cadastra

- **Faixas semanais:** dia da semana e horário (`19:00` às `21:00`), que se repetem toda
  semana. Cada faixa tem **modalidade** (presencial, online ou as duas), **local ou link** da
  reunião online, **para quem vale** (todos, só graduação ou só mentoria) e uma observação.
  Dá para desligar uma faixa sem apagá-la.
- **Exceções por data:** **não atendo no dia** (viagem, feriado), que tira o dia da semana e
  mostra o motivo ao aluno, ou **horário extra** numa data, com o mesmo tipo, local e público.

Os horários são de parede, no relógio de quem atende, sem fuso: `19:00` é 19:00 onde você está.
Só o "hoje" usa o fuso de São Paulo.

## Como o aluno vê

Na aba **Atendimento** do [portal do aluno](portal-do-aluno.md): os horários da semana e os
próximos 28 dias, dia a dia, com a modalidade, o local (o link da reunião online é clicável),
os dias sem atendimento e os horários extras. Cada aluno só vê as faixas do público dele:

| Aluno | Vê faixas |
|---|---|
| Só graduação | para todos e para graduação |
| Só mentoria | para todos e para mentoria |
| Graduação e mentoria | as três |

## Prévia e choques com o calendário

O painel **Como o aluno vê** mostra os próximos 28 dias como cada público enxergaria (você pode
alternar entre "Tudo", "Aluno de graduação" e "Aluno de mentoria"). Cada atendimento é cruzado
com os eventos do seu Google ou Microsoft Calendar: se um evento cai dentro de uma faixa, a
linha ganha o aviso **Choca com: nome do evento** e o painel conta quantos choques há.

Se o calendário não responder (nenhuma conta conectada, por exemplo), a tela diz que os
choques **não foram conferidos**, em vez de dizer que não há nenhum. O cruzamento é só um
aviso: nada é bloqueado nem alterado no seu calendário.

## Plano de encontros da mentoria

Na tela de cada mentoria, a seção **Encontros** cruza as suas faixas (as de "todos" e as de
"só mentoria") com os **horários livres** que cada aceito marcou na inscrição (`qui-noite`,
`sáb-manhã`...). Uma faixa serve a um aluno quando cobre pelo menos 30 minutos do turno que
ele marcou (manhã 06–12, tarde 12–18, noite 18–24).

O plano ordena as faixas por quantos alunos conseguem ir, marca a **melhor opção**, mostra
quem consegue cada uma e lista quem **não consegue nenhuma** das suas faixas. Só sugere: marcar
o encontro continua sendo seu. Aceito que não informou horários conta como sem cobertura.

## Rotas

Autenticadas, em `/education/availability`: `GET` (faixas e exceções de hoje em diante),
`GET /preview?days=&audience=`, `POST /slots`, `PATCH|DELETE /slots/{id}`,
`POST /exceptions`, `DELETE /exceptions/{id}`. O plano fica em
`GET /education/mentorships/{id}/meeting-plan`.

## Ainda não existe

- **Reserva pelo aluno:** hoje o aluno só vê a agenda. Pedir ou reservar um horário, com
  confirmação sua e aviso por e-mail, é a próxima fase.
- **Criar o encontro a partir do plano:** o plano sugere o dia, mas não cria o evento no
  calendário nem avisa os alunos.
