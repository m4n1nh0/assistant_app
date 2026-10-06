# Quiz em grupo

O quiz pode valer por grupo de projeto em vez de por aluno. O professor liga o modo
no próprio quiz e escolhe como o grupo pontua.

**Onde:** Central de quizzes → abrir o quiz → ícone **Quiz em grupo**.

## Dois modos

| Modo | Quem responde | Quanto o grupo vale |
|---|---|---|
| **Média do grupo** | Todos, cada um no próprio celular | A média dos pontos dos integrantes que **entraram** |
| **Só o representante** | Apenas o representante do grupo | Os pontos do representante |

Na média, quem não apareceu não entra na conta (a tela mostra "2 de 3 integrantes" para
o professor julgar). No modo representante, a resposta dos outros integrantes não é
gravada, e a tela deles diz quem responde pelo grupo.

## Quais grupos jogam (turmas)

Por padrão entram os grupos da disciplina toda. Para jogar só com as turmas de um dia,
marque-as na janela do quiz em grupo; as turmas que têm aula hoje já vêm marcadas. Duas
turmas na mesma aula (3002 e 3030, na segunda) marcam-se juntas, e entram os grupos de
qualquer uma delas, inclusive os que misturam alunos das duas. Veja
[Grupos por turma](../grupos-por-turma.md).

## Como o aluno entra

A página de entrada pede a **matrícula**, não o nome. O servidor procura a matrícula nos
grupos da disciplina escolhida e liga o aluno ao grupo dele. O nome exibido vem do
cadastro, então não há nome digitado errado nem dois alunos com o mesmo nome.

- A comparação ignora pontuação e caixa: `2024-0001` e `20240001` são a mesma matrícula.
- Zeros à esquerda contam: `0123` e `123` são matrículas diferentes.
- O aluno precisa estar **vinculado a um integrante** do grupo e ter matrícula
  cadastrada. Quem não tem não consegue entrar. A janela do professor marca esses
  integrantes, e o vínculo se faz em **Grupos de projeto → Sugerir nomes e matrículas**.
- A matrícula não é segredo: quem souber a de um colega responde por ele. É o nível de
  confiança de uma sala de aula; o servidor garante só que a matrícula vale apenas dentro
  da disciplina do quiz.

## Penalidade por ausente

O professor escolhe, por quiz, o que acontece com quem falta:

| Opção | O que faz |
|---|---|
| **Sem penalidade** | O ausente aparece na lista, mas a nota do grupo não muda. |
| **Ausente conta zero** (só na média) | A média é dividida por todos que **podiam entrar**; quem faltou entra na conta valendo zero. |
| **Desconto por ausente** | Cada ausente tira uma porcentagem da nota do grupo (ex.: 10%). Os descontos somam, e o desconto nunca passa de 100%. Vale nos dois modos. |

**Quem é ausente:** o integrante que **não entrou** no quiz, ou que **entrou e não respondeu
nada**. Pular uma pergunta conta como ter respondido. No modo representante só ele
responde, então "entrou e não respondeu" vale só para ele; os outros estão presentes se
entraram.

**Quem nunca é penalizado:** integrante sem matrícula vinculada. Ele não tem como ler o
QR Code e se identificar, e punir isso seria punir uma falha de cadastro. A janela do
grupo já marca esses integrantes para o professor corrigir.

**"Ausente conta zero" no modo representante** não existe: a nota do grupo já é só a do
representante, não há média a diluir. Use o desconto por ausente.

Antes da primeira resposta, só quem **não entrou** aparece como ausente: ninguém respondeu
ainda, e isso não é ausência.

A penalidade é só uma regra de cálculo e não altera nenhuma resposta gravada. Por isso
pode ser ajustada a qualquer momento, até com o quiz encerrado, e o ranking é recalculado.
O ranking do professor mostra "1 ausente (−10%)" em cada grupo, com a nota antes do
desconto disponível na API (`score_before_penalty`).

## Representantes

No modo representante, a janela oferece:

- **Sortear representantes**: escolhe um integrante de cada grupo que ainda não tem. Só
  entra no sorteio quem tem matrícula, senão o grupo ficaria sem ninguém para responder.
- **Sortear outro**: refaz um grupo (o escolhido faltou, por exemplo).
- **Escolher manualmente**: o professor indica quem responde pelo grupo.
- **Refazer todos**.

O sorteio usa a mesma regra verificável do [sorteio de apresentação](../sorteio-de-apresentacao.md):
a semente do quiz fica à mostra, e o resultado pode ser refeito por quem a tiver.

## Ranking

O ranking do quiz em grupo sai no mesmo formato do individual, com o grupo no lugar do
aluno. A tela do aluno e o painel ao vivo do professor mostram "por grupo", e cada aluno
vê o próprio grupo destacado. O ranking individual continua disponível no painel do
professor, para ver quem puxou o grupo.

## Travas

- Só se liga, muda de modo ou se volta a individual **sem pergunta aberta** e com o quiz
  **não encerrado**. A penalidade por ausente é a exceção: muda sempre.
- Depois que a turma respondeu, não dá para trocar o modo, a disciplina nem as turmas, nem
  voltar a individual: as respostas já foram gravadas de um jeito.
- Respostas de aparelhos sem vínculo não entram no ranking de grupo.
- O mesmo aluno em dois aparelhos conta a **primeira** resposta de cada pergunta.

## Excluir um quiz

Rascunho sai direto (**Descartar**). Quiz **liberado ou encerrado** também pode ser
excluído (**Excluir**), mas leva junto as respostas, o ranking, as traduções, os
participantes e a configuração de grupo. O app pede confirmação, e o servidor só aceita
com `force=true`. Com uma pergunta aberta para a turma, o servidor recusa.

### Em lote

Na lista de quizzes, marque os quizzes (ou **Selecionar todos**) e use **Excluir selecionados**. A confirmação diz quantos são rascunhos e quantos já foram liberados ou encerrados (e perdem respostas e ranking). O que não puder sair, como um quiz com pergunta aberta, continua na lista e o app mostra o motivo. O servidor aceita até 100 quizzes por pedido.

## API

Sob `/education/quiz/{id}/group` (professor dono do quiz):

| Método | Rota | Para quê |
|---|---|---|
| `GET` | `/` | Situação (`enabled: false` se for individual), grupos, representantes e ranking |
| `PUT` | `/` | Liga ou ajusta (`mode`, `discipline_id`, `semester`, `absence_mode`: `none`, `zero` ou `percent`, e `absence_percent`) |
| `DELETE` | `/` | Volta a individual |
| `POST` | `/representatives/draw` | Sorteia os que faltam (`redraw: true` refaz todos) |
| `POST` | `/representatives/{grupo}/redraw` | Sorteia outro para um grupo |
| `PUT` | `/representatives/{grupo}` | O professor escolhe (`member_id`) |

E, para excluir quizzes:

| Método | Rota | Para quê |
|---|---|---|
| `DELETE` | `/education/quiz/{id}?force=true` | Um quiz liberado ou encerrado (rascunho dispensa `force`) |
| `POST` | `/education/quiz/bulk-delete` | Vários, com `{"ids": [...], "force": true}`; devolve `deleted`, `ignored`, `answers`, `participants` e `blocked` (id, título e motivo) |
