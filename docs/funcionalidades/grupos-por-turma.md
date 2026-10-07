# Grupos de projeto por turma (segunda e quinta)

Disciplina que tem aula em dois dias costuma ter duas turmas, cada uma com os seus
alunos e os seus grupos, e o "GRUPO 1" existe nas duas. Os grupos pertencem a uma
**turma**, e é a turma que diz o dia de aula.

**Onde:** Modo Educação → **Grupos de projeto**.

## Cadastrar a lista de uma turma

1. Escolha a disciplina e cole (ou carregue) a lista.
2. Clique em **Conferir e cadastrar grupos**. O app pergunta **de quais turmas é a lista**,
   com uma caixa para cada turma. Se o título da lista diz o dia (por exemplo
   `Grupos turma segunda:`), as turmas que têm aula nesse dia já vêm marcadas; confira.
   Em dúvida (nenhum dia, ou dois dias no título) o app não marca nada.
3. A prévia mostra as turmas (`Turma: 3001 Presencial · segunda`), e os nomes são ligados
   só aos **alunos das turmas marcadas**, o que acerta os homônimos de turmas diferentes.

Cada turma tem os seus grupos: importar a lista da quinta **não mexe** nos grupos da
segunda, mesmo com os mesmos nomes.

### Aula reunida: grupos que misturam duas turmas

O grupo é do **dia**. Disciplina com quatro turmas (duas na segunda e duas na quinta, por
exemplo) tem grupos da segunda que misturam alunos das duas turmas da segunda, e o mesmo
na quinta. Marque **as turmas do dia** nos botões de turma da tela (tocar de novo
desmarca) e clique em **Conferir e cadastrar grupos**: a janela já abre com as turmas
marcadas, e basta confirmar. Também dá para marcá-las na própria janela. Os nomes da lista são
procurados entre os alunos das duas turmas juntas, e o grupo passa a pertencer às duas:

- ele aparece no filtro de **cada** turma (e conta nos botões das duas);
- o sorteio e o quiz em grupo de qualquer uma das duas turmas incluem o grupo;
- reimportar a mesma lista com as mesmas turmas atualiza os grupos, sem duplicar.

Ao abrir a disciplina, **todas** as turmas que têm aula hoje já vêm marcadas juntas (na
segunda, as duas turmas da segunda).

### Atualizar um grupo que já existe

O nome do grupo é único dentro de cada turma, então importar um nome que já existe nas
turmas da lista **atualiza aquele grupo** em vez de criar outro, e a prévia diz o que vai
acontecer:

- **Mesmas turmas:** atualiza os integrantes, como sempre.
- **A lista tem mais turmas do que o grupo tinha** (o `GRUPO 3` era só da 3001 e agora a
  lista é da 3001 + 3008, porque entrou gente da 3008): atualiza os integrantes e **amplia as
  turmas** do grupo para as da lista. A prévia mostra
  `GRUPO 3: de 3001 · terça para 3001 · terça + 3008 · terça`, e nada muda antes de você
  confirmar. Os vínculos com os alunos e as notas do grupo ficam.
- **A lista tem só parte das turmas do grupo** (o grupo é 3001 + 3008 e você importou só a
  3001): atualiza os integrantes e **mantém as turmas** dele; o grupo não encolhe.
- **Ambíguo:** as turmas se cruzam só em parte (o grupo é 3001 + 3008 e a lista é 3008 +
  3030), ou há mais de um grupo com aquele nome nas turmas da lista. Não dá para saber qual é
  o grupo, e o cadastro fica **bloqueado** com o aviso: marque as mesmas turmas do grupo que
  já existe ou renomeie.

Como a atualização troca a lista de integrantes, a prévia conta quantos integrantes
antigos vão sair. Uma lista sem turma só atualiza grupo sem turma.

### Formato aceito da lista

O nome pode vir com marcador de lista, como no chat: `- Nome`, `• Nome`, `* Nome`,
`1. Nome` ou `1) Nome`. O texto antes do primeiro `GRUPO` vira observação da lista. A
marca `v` no fim do nome continua sendo lida como anotação, e um hífen dentro do nome
(`Ana-Maria`) é preservado.

Lista colada do WhatsApp, do Word ou de e-mail costuma trazer caracteres que parecem
normais mas não são: espaço sem quebra entre o nome e o sobrenome, marcas invisíveis de
direção do texto, apóstrofo curvo (`D’Arc`). O cadastro os trata como espaço comum ou os
descarta antes de ler, então o nome não é mais recusado por isso. Quando um nome é recusado
de verdade, a mensagem diz a linha e **qual caractere** atrapalhou (por exemplo
`'@' (U+0040)`), para você apagá-lo na lista.

## Grupos que já estavam cadastrados (sem turma)

Grupos criados antes da separação ficam **sem turma**. O botão **Ligar grupos sem
turma** aparece enquanto houver algum: escolha a turma e todos os grupos soltos passam a
pertencer a ela. Integrantes, vínculos e notas não mudam.

Dá para ligar a **mais de uma turma** de uma vez (aula reunida). A ligação é recusada se
alguma turma de destino já tiver um grupo com o mesmo nome; nesse caso nada é alterado.

### Deduzir as turmas pelos alunos (grupos já cadastrados)

Para a disciplina que já tem os grupos cadastrados e vinculados aos alunos (sem turma), o
botão **Deduzir turmas pelos alunos** liga cada grupo às turmas dos seus integrantes: o
grupo só de alunos de uma turma fica nela; o que mistura duas fica nas duas. Só mexe em
grupo sem turma. Ficam de fora, e a mensagem lista os nomes: grupos sem nenhum integrante
vinculado a aluno (vincule os nomes e tente de novo, ou use **Ligar grupos sem turma**) e
nomes que já existem em grupo de turmas que se cruzam.

## Remover um integrante do grupo

Para tirar quem foi cadastrado por engano ou saiu do grupo, clique no nome do integrante
(o mesmo clique do vínculo com o aluno) e em **Remover do grupo**. Antes de remover, o app
avisa o que depende dele:

- **Quiz em grupo:** em quantos quizzes ele entrou. O aparelho dele sai do grupo e o
  resultado do grupo nesses quizzes passa a ser calculado **sem ele**.
- **Representante:** se ele era o representante de algum quiz, o grupo fica sem
  representante até novo sorteio.
- **Sorteio de apresentação:** se ele foi sorteado como representante, esse sorteio é
  desfeito e pode ser refeito entre os que sobraram.

O aluno **continua cadastrado** na turma; só sai deste grupo. Os outros integrantes mantêm
a ordem. O **último integrante não pode ser removido**: para isso, apague o grupo. Se a
lista for importada de novo com o nome dele, ele volta ao grupo.

## Ver, sortear, jogar e imprimir por turma

- **Filtro (turmas do dia):** o bloco **Turma (dia de aula)** segue a aba Gravar. As
  turmas da disciplina aparecem em botões, as que têm aula **hoje** em **HOJE, SEGUNDA-FEIRA**
  e as demais em **OUTRAS TURMAS**; cada botão mostra o dia, os alunos e quantos grupos a
  turma tem, e há também "Todas as turmas" e "Sem turma". Os botões podem ser marcados
  juntos: aparecem os grupos de qualquer uma das turmas marcadas. As turmas que têm aula
  hoje já vêm marcadas, então a tela abre mostrando os grupos do dia (as duas da segunda,
  por exemplo). Sem aula hoje, fica "Todas". Cada grupo mostra as suas turmas no título.
- **Sorteio de apresentação:** a janela do sorteio tem o seletor de turma; só os grupos
  dela entram, e o título do sorteio leva o nome da turma. O filtro da aba já vem marcado.
  Com **duas ou mais turmas marcadas** na tela, a primeira opção do seletor é "as turmas
  marcadas (N grupos)": o sorteio leva exatamente os grupos que estão listados.
- **Quiz em grupo:** ao ativar, escolha as turmas nos mesmos botões da tela de grupos
  (HOJE e OUTRAS TURMAS; as turmas que têm aula hoje já vêm marcadas, e "Todas as turmas
  da disciplina" é nenhuma marcada). Pode marcar mais de uma, para a aula reunida. Só
  entram os alunos dos grupos de qualquer uma das turmas marcadas; a matrícula de quem é
  de outra turma recebe "não está em nenhum grupo deste quiz". Depois que a turma
  respondeu, as turmas não mudam (como o modo e a disciplina).
- **Impressão:** a relação de grupos e a ordem de apresentação trazem a turma no
  cabeçalho. A relação sai com o recorte que está na tela.

## Detalhes técnicos

- O grupo ganha `class_id` (nulo para os antigos), que é a turma principal. Na aula
  reunida as turmas ficam na tabela `project_group_classes` (`group_id`, `class_id`) e a
  principal é a primeira em ordem de id; sem linhas ali, vale só `class_id`. O nome do
  grupo é único **dentro da turma**: `(professor, disciplina, turma, nome)` no banco, e
  entre turmas que se cruzam pela aplicação.
- No MySQL a troca da trava antiga (`professor, disciplina, nome`) pela nova é feita
  sozinha na subida do servidor, e é segura de repetir. No banco, grupos sem turma não
  comparam entre si (NULL), então a unicidade deles é garantida pela aplicação: importar
  sem turma só enxerga os grupos sem turma.
- API: `POST /education/project-groups/preview` e `/import` aceitam `class_ids` (lista) e
  ainda `class_id` (aparelhos antigos); a prévia devolve `class_ids`, `class_label` com as
  turmas juntas (`3002 A + 3030 B`) e `conflicting_names`. `GET /education/project-groups`
  devolve `class_ids` e filtra por `?class_id=...` (o grupo de aula reunida aparece nas
  suas turmas; `none` traz os sem turma). `POST /education/project-groups/assign-class`
  liga ou solta (`{"group_ids": [...], "class_ids": [...]}`; lista vazia solta).
  `POST /education/project-groups/infer-classes` (`{"discipline_id": "...",
  "group_ids": []}`) deduz as turmas dos grupos sem turma pelos alunos vinculados e
  devolve `assigned`, `without_linked_members` e `conflicting`.
  `GET /education/project-groups/{grupo}/members/{integrante}/usage` conta o que depende do
  integrante (`quiz_participations`, `quiz_representations`, `draw_representations`) e
  `DELETE` no mesmo caminho o remove, devolvendo o que foi desfeito em `cleaned`. O quiz em grupo
  (`PUT /education/quiz/{id}/group`) aceita `class_ids` (e ainda `class_id`) e devolve
  `class_ids` e `class_label` com as turmas juntas; o servidor guarda a lista em
  `quiz_group_configs.class_ids` (texto separado por vírgula), e quiz antigo, sem a lista,
  vale a turma `class_id`. O sorteio (`POST /education/group-draws`) e o quiz em grupo
  (`PUT /education/quiz/{id}/group`) aceitam `class_id`.
