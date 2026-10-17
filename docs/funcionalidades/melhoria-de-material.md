# Melhoria de material por IA

O texto que sai de um PDF, DOCX ou PPTX é o que o arquivo tem, não o que o aluno precisa ler:
palavra por linha, rodapé repetido em todo slide, títulos sem marca. A melhoria pede a uma IA
que **reorganize** esse texto em Markdown limpo, sem resumir e sem acrescentar nada.

## Como usar

Em **Material** (modo educação), cada linha tem o botão **Melhorar texto com IA**:

1. Escolha **quem reescreve**: *Automático* (a fila do backend, do gratuito ao pago), um provedor
   fixo, ou um **agente conectado** (Codex, Claude Code) que roda neste computador.
2. Se quiser, escreva um **pedido extra** ("manter os nomes das plataformas em inglês").
3. Toque em **Melhorar**. Um material grande leva alguns minutos.

Depois a linha mostra *melhorado por…*, e aparecem **Ver texto melhorado** (para conferir) e
**Voltar ao texto original** (descarta a melhoria). Melhorar de novo substitui a versão anterior.

## O que muda

- O **portal do aluno** passa a mostrar a versão melhorada, com títulos, listas e índice. Sem
  melhoria, continua o texto extraído, estruturado por heurística.
- Os **blocos de indexação** (`material_chunks`) são refeitos a partir da versão melhorada, e
  cortam pelos títulos `##` que a IA marcou.
- O **texto original não é tocado**: fica em `materials.content`, e a melhoria numa tabela ao
  lado (`material_improvements`). Descartar volta ao original e refaz os blocos.

O quiz ainda lê o texto original.

## Fidelidade

O prompt proíbe resumir, inventar, traduzir e mudar a ordem. Além disso o servidor confere o
**tamanho**: uma saída com menos de 45% ou mais de 160% do original é resumo ou invenção, e é
**recusada** em vez de gravada (o professor vê "não parece uma reescrita fiel" e pode tentar
outra IA). A saída é só Markdown simples (`##`, `-`, `**negrito**`): é o que o portal e o
cortador de blocos sabem ler.

## Dois caminhos, como no resumo da aula

| Quem reescreve | Como roda |
| --- | --- |
| Provedor do backend | O servidor divide o texto em partes de ~9 mil caracteres, manda cada uma ao modelo e junta o resultado. |
| Agente conectado (Codex, Claude Code) | O backend entrega o prompt, o agente lê o material **inteiro de uma vez** na máquina do professor e devolve o texto para ser gravado. |

## Rotas (autenticadas)

| Rota | Para quê |
| --- | --- |
| `POST /education/materials/{id}/improve` | Reescreve com um provedor do backend (`llm` opcional, `instructions` opcional). |
| `GET /education/materials/{id}/improve/prompt` | Prompt pronto para um agente conectado. |
| `POST /education/materials/{id}/improve/external` | Guarda o texto que o agente devolveu. |
| `GET /education/materials/{id}/improved` | A versão melhorada, para conferir. |
| `DELETE /education/materials/{id}/improved` | Descarta e volta ao original. |

`GET /education/materials` passa a informar `improved`, `improved_llm` e `improved_at` em cada
material.

## Limites conhecidos

- O quiz e a geração de provas ainda usam o texto original; passar a usar a versão melhorada é
  o próximo passo natural.
- Um PDF digitalizado sem OCR continua sem texto: a melhoria reorganiza texto, não o cria.
- Materiais enviados antes da melhoria não têm blocos refeitos até alguém melhorá-los.
