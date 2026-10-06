# Material das apresentações e quiz rápido

Os alunos enviam o PDF ou PPTX da apresentação do grupo por um **link**, o app junta esse
material com a **gravação** da apresentação, e dali sai um **quiz rápido** para os outros
grupos responderem.

**Onde:** Modo Educação → **Grupos de projeto** → **Material das apresentações**.

## Fluxo

1. **Link.** Você cria um link por disciplina (ou só para as turmas marcadas) e manda para
   a turma, copiando o endereço ou mostrando o QR Code.
2. **Envio.** O aluno abre o link, digita a **matrícula**, vê o grupo dele e envia o
   arquivo. Os grupos de aula reunida (que misturam duas turmas) são achados pelas duas.
3. **Painel.** Cada grupo mostra o que chegou (arquivo, quem enviou, quando) e a gravação
   da apresentação, e o que ainda falta.
4. **Quiz rápido.** Em um clique o app gera as perguntas com o material e a gravação, e o
   quiz já sai em grupo, **sem o grupo que apresentou**.

## Link de envio

- **Nome, turmas e prazo.** Sem turmas marcadas, vale a disciplina toda. As turmas que
  estão marcadas na tela de grupos já vêm marcadas. O prazo (opcional) vale até o fim do
  dia escolhido.
- **Acompanhamento.** O cartão do link mostra quantos grupos já enviaram e quantos
  arquivos chegaram (`2 de 10 grupos enviaram · 3 arquivo(s)`).
- **Fechar e reabrir.** Fechar encerra o recebimento na hora; reabrir um link vencido
  tira o prazo. **Apagar** derruba o endereço, mas o que já foi enviado continua nos
  materiais.
- **Endereço do servidor.** O link usa o endereço do servidor configurado no app. Se for
  `localhost` ou um IP da rede local, o cartão avisa: os alunos só abrem um endereço
  público.

### O que o aluno vê

Uma página simples, sem login. Ele digita a matrícula (pontuação e caixa não importam:
`2024-0001` é `20240001`) e vê o grupo e os integrantes. Depois escolhe o arquivo e envia:

- **Formatos:** PDF, PPTX e DOCX, até **20 MB**. `.ppt` (PowerPoint antigo) é recusado com
  a instrução de salvar como `.pptx` ou PDF. Arquivo que é só imagem (sem texto) é recusado
  com a dica de exportar em PDF com texto.
- **Substituir.** Enviar de novo um arquivo com o mesmo nome troca o anterior, em vez de
  duplicar.
- **Limite por grupo:** 5 arquivos (configurável no link, até 20). O aluno pode remover um
  arquivo do próprio grupo, só enquanto o link está aberto.
- **Mensagens claras** quando a matrícula não existe, não está em nenhum grupo ou o link
  foi fechado.

> A matrícula não é segredo: quem souber a de um colega pode enviar pelo grupo dele. É o
> mesmo nível de segurança do quiz em grupo; por isso o painel mostra **quem enviou** cada
> arquivo e você pode soltar o que estiver errado.

Só o **texto extraído** é guardado, não o arquivo original (o disco do servidor é
descartado a cada atualização). É o mesmo que o material didático já faz.

## Painel por grupo

Cada grupo mostra os selos **material ✓ / sem material** e **gravação ✓ / sem gravação**,
a lista de arquivos (título, `12 slides`, quem enviou, data) e as gravações (data e
quantidade de trechos transcritos). Uma gravação só vale como fonte se tem **transcrição**.

Ações:

- **Ligar material:** liga ao grupo um material que já estava na disciplina (os slides que
  chegaram por e-mail ou chat). Passa a valer como o enviado pelo link.
- **Soltar** (ícone no arquivo): desliga o material do grupo, sem apagá-lo.
- **Ligar gravação:** liga ao grupo uma gravação feita como palestra (ou apresentação sem
  grupo). Ela passa a ser do tipo **apresentação** e o resumo fala dela assim. Aula não
  entra: pertence às turmas.

Se a tela de grupos tem turmas marcadas, o painel mostra só os grupos delas.

## Quiz rápido

O botão **QUIZ RÁPIDO** de um grupo abre a escolha:

- **Fontes:** o material enviado e a gravação da apresentação, todos marcados. Você decide
  na hora (só o material, só a gravação, ou os dois). Falta alguma? O aviso diz o que
  faltou e o quiz usa só o que existe. Sem nenhuma fonte, o botão não liga.
- **Perguntas:** 5, 8 (padrão), 10 ou 15.
- **Formato:** média do grupo ou só o representante (como no quiz em grupo).
- **Quem joga:** os grupos das **mesmas turmas** do grupo que apresentou, que fica **de
  fora**: não responde ao quiz sobre o próprio trabalho e não conta como ausente. O
  integrante dele que tentar entrar vê "Seu grupo apresentou este trabalho e não responde
  este quiz".

O pedido entra na fila de geração (**Central de quizzes**) e o quiz sai como **rascunho**,
já em grupo. Você revisa as perguntas e libera o QR Code como em qualquer outro quiz; o
aviso de fim sai pelos mesmos canais. Se não for possível ligar o quiz aos grupos, ele
continua valendo como quiz individual e a mensagem do pedido diz por quê.

## Detalhes técnicos

- **Tabelas.** `material_submission_links` (token, disciplina, turmas, prazo, ativo,
  limite) é nova. `materials` ganha `group_id`, `student_id`, `uploader_name` e
  `link_id`, e `quiz_group_configs` ganha `excluded_group_ids`, criadas sozinhas na subida
  do servidor.
- **Páginas públicas (sem login):** `GET /education/material-submit/{token}` (a página),
  `POST .../lookup` (matrícula → grupo), `POST .../send` (arquivo) e `POST .../remove`.
  Respostas de erro trazem `code` (`unknown`, `no_group`, `format`, `size`, `limit`,
  `closed`, `expired`, `empty`, `extract`) e a mensagem para o aluno.
- **Professor (autenticado):** `POST/GET /education/material-links`,
  `PATCH/DELETE /education/material-links/{id}`, `GET /education/presentations`
  (`?discipline_id=&class_id=`), `PUT /education/materials/{id}/group` e
  `PUT /education/lessons/{id}/presentation-group`.
- **Quiz já em grupo.** `POST /education/quiz/generate/async` aceita `titulo` e
  `group_setup` (`mode`, `discipline_id`, `class_ids`, `exclude_group_ids`, penalidade); o
  job liga o quiz aos grupos quando termina. A configuração de grupo do quiz
  (`PUT /education/quiz/{id}/group`) aceita `exclude_group_ids` e o painel devolve
  `excluded_groups`. Depois que a turma respondeu, os grupos de fora não mudam.
- **Fontes.** O quiz lê o texto de `materials` e a transcrição da gravação pelo mesmo
  caminho dos outros quizzes (`material_ids` e `lesson_ids`); de cada pergunta continua
  rastreável de onde saiu.
