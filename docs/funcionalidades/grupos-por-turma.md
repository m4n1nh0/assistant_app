# Grupos de projeto por turma (segunda e quinta)

Disciplina que tem aula em dois dias costuma ter duas turmas, cada uma com os seus
alunos e os seus grupos, e o "GRUPO 1" existe nas duas. Os grupos pertencem a uma
**turma**, e é a turma que diz o dia de aula.

**Onde:** Modo Educação → **Grupos de projeto**.

## Cadastrar a lista de uma turma

1. Escolha a disciplina e cole (ou carregue) a lista.
2. Clique em **Conferir e cadastrar grupos**. O app pergunta **de qual turma é a lista**.
   Se o título da lista diz o dia (por exemplo `Grupos turma segunda:`), a turma da
   segunda já vem marcada; confira. Em dúvida o app não escolhe sozinho.
3. A prévia mostra a turma (`Turma: 3001 Presencial · segunda`), e os nomes são ligados
   só aos **alunos daquela turma**, o que acerta os homônimos de turmas diferentes.

Cada turma tem os seus grupos: importar a lista da quinta **não mexe** nos grupos da
segunda, mesmo com os mesmos nomes.

### Formato aceito da lista

O nome pode vir com marcador de lista, como no chat: `- Nome`, `• Nome`, `* Nome`,
`1. Nome` ou `1) Nome`. O texto antes do primeiro `GRUPO` vira observação da lista. A
marca `v` no fim do nome continua sendo lida como anotação, e um hífen dentro do nome
(`Ana-Maria`) é preservado.

## Grupos que já estavam cadastrados (sem turma)

Grupos criados antes da separação ficam **sem turma**. O botão **Ligar grupos sem
turma** aparece enquanto houver algum: escolha a turma e todos os grupos soltos passam a
pertencer a ela. Integrantes, vínculos e notas não mudam.

A ligação é recusada se a turma de destino já tiver um grupo com o mesmo nome; nesse caso
nada é alterado.

## Ver, sortear, jogar e imprimir por turma

- **Filtro (turmas do dia):** o bloco **Turma (dia de aula)** segue a aba Gravar. As
  turmas da disciplina aparecem em botões, as que têm aula **hoje** em **HOJE, SEGUNDA-FEIRA**
  e as demais em **OUTRAS TURMAS**; cada botão mostra o dia, os alunos e quantos grupos a
  turma tem, e há também "Todas as turmas" e "Sem turma". A turma que tem aula hoje já vem
  marcada, e só ela, então a tela abre mostrando os grupos do dia. Com duas turmas no mesmo
  dia, ou nenhuma, não há como escolher pelo dia e fica "Todas". Cada grupo mostra a turma
  no título.
- **Sorteio de apresentação:** a janela do sorteio tem o seletor de turma; só os grupos
  dela entram, e o título do sorteio leva o nome da turma. O filtro da aba já vem marcado.
- **Quiz em grupo:** ao ativar, escolha a turma. Só entram os alunos dos grupos dela; a
  matrícula de quem é de outra turma recebe "não está em nenhum grupo deste quiz".
- **Impressão:** a relação de grupos e a ordem de apresentação trazem a turma no
  cabeçalho. A relação sai com o recorte que está na tela.

## Detalhes técnicos

- O grupo ganha `class_id` (nulo para os antigos). O nome do grupo é único **dentro da
  turma**: `(professor, disciplina, turma, nome)`.
- No MySQL a troca da trava antiga (`professor, disciplina, nome`) pela nova é feita
  sozinha na subida do servidor, e é segura de repetir. No banco, grupos sem turma não
  comparam entre si (NULL), então a unicidade deles é garantida pela aplicação: importar
  sem turma só enxerga os grupos sem turma.
- API: `POST /education/project-groups/preview` e `/import` aceitam `class_id`;
  `GET /education/project-groups?class_id=...` filtra (`none` traz os sem turma);
  `POST /education/project-groups/assign-class` liga ou solta (`{"group_ids": [...],
  "class_id": "..."}`). O sorteio (`POST /education/group-draws`) e o quiz em grupo
  (`PUT /education/quiz/{id}/group`) aceitam `class_id`.
