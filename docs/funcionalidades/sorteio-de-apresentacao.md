# Sorteio de apresentação por grupo

Sorteia a ordem em que os grupos de projeto de uma disciplina apresentam, e deixa o
resultado à mostra para a turma conferir.

**Onde:** Modo Educação → aba **Grupos de projeto** → **Sortear apresentação**.

## Dois modos

| Modo | Como funciona |
|---|---|
| **Ordem completa** | Todos os grupos saem de uma vez, já com posição e dia. |
| **Um grupo por vez** | Cada clique sorteia o próximo grupo, na hora da apresentação. |

A ordem final dos dois é a mesma para a mesma semente; muda só o momento em que ela é
revelada.

## Apresentações no mesmo dia

Em **Apresentações por dia** o professor diz quantos grupos apresentam por dia. A fila
é dividida em dias (1º ao 3º no dia 1, 4º ao 6º no dia 2, e assim por diante). Vazio
significa tudo no mesmo dia.

## Acompanhamento

Cada grupo sorteado pode ser marcado como **na vez**, **apresentou** ou **ausente**.
O contador no topo mostra quantos já apresentaram. Um sorteio fica salvo: ao reabrir,
o último é carregado, e os anteriores ficam na lista de sorteios.

## Representante do grupo

**Sortear representante** escolhe um integrante do grupo, entre os cadastrados.
Chamar de novo sorteia outro (por exemplo, se o escolhido faltou). Grupo sem
integrantes cadastrados não tem representante.

## Tela de projeção

O ícone de projetar troca a lista por uma tela grande para o telão: o grupo na vez, o
representante, quem vem depois, e o botão de sortear o próximo (com os nomes girando
antes do resultado).

## Imprimir

Há dois PDFs, com o mesmo padrão dos outros documentos do app, e cada um pergunta se vai para a impressora ou para um arquivo:

- **Relação de grupos** - aba **Grupos de projeto** → **Imprimir relação**. Lista cada grupo da disciplina com o título do projeto, os integrantes (na ordem da lista) e a matrícula de cada um. Integrante cujo nome ainda não foi ligado a um aluno cadastrado sai com "—" na matrícula. Os grupos saem em ordem numérica ("Grupo 2" antes de "Grupo 10").
- **Ordem de apresentação** - janela do sorteio → ícone da impressora. Traz a posição, o grupo, o representante e a situação, dividido por dia quando houver mais de um, e a lista dos grupos ainda não sorteados. No rodapé vão a semente e a regra do sorteio, para quem quiser conferir.

## Como o sorteio é provado justo

O sorteio não usa gerador aleatório escondido. Cada passo vem de um hash:

1. O servidor cria uma **semente** de 128 bits no momento do sorteio. O professor não
   escolhe a semente, para não dar para testar várias até sair a ordem desejada.
2. No passo `n`, entre os grupos que ainda não saíram, vence o de menor
   `SHA-256("semente:n:id-do-grupo")`.
3. O representante sai igual: menor `SHA-256("semente:rep:id-do-grupo:rodada:id-do-integrante")`.

Quem tiver a semente e a lista de grupos refaz a conta e chega na mesma ordem. A tela
mostra a semente e o algoritmo (`sha256-v1`) e avisa se a ordem gravada não bate com
a semente. Se a conta mudar um dia, nasce `sha256-v2` e os sorteios antigos continuam
verificáveis pela regra com que foram feitos.

## API

Todas sob `/education/group-draws`, só para o professor dono:

| Método | Rota | Para quê |
|---|---|---|
| `POST` | `/` | Cria o sorteio (`discipline_id`, `semester`, `mode`, `per_day`, `group_ids`) |
| `GET` | `/` | Lista os sorteios da disciplina |
| `GET` | `/{id}` | Detalhe com a ordem, a semente e a conferência |
| `POST` | `/{id}/next` | Sorteia o próximo grupo (modo `avulso`) |
| `PATCH` | `/{id}/entries/{entry}` | Marca `pendente`, `apresentando`, `apresentou` ou `ausente` |
| `POST` | `/{id}/entries/{entry}/representative` | Sorteia (ou sorteia outro) representante |
| `DELETE` | `/{id}` | Exclui o sorteio |

## Ainda não existe

- Página pública para os alunos verem a ordem (como a do quiz).
- Ligação automática do representante sorteado aqui ao quiz em grupo (hoje o quiz
  em grupo tem o próprio sorteio de representantes; veja [Quiz em grupo](quiz/quiz-em-grupo.md)).
