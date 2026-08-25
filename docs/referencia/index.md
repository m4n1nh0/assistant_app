# Referencia do codigo

A referencia tem tres origens diferentes e e util saber qual e qual antes de
editar alguma coisa:

| Secao | Origem | Como se atualiza |
| --- | --- | --- |
| [Backend](backend/app/index.md) | docstrings de `backend/app/**.py` | escrevendo docstring no modulo |
| [Interface Flutter](interface.md) | comentarios `///` de `interface/lib/**.dart` | escrevendo `///` na classe/metodo |
| [Infraestrutura](infra.md) | escrita a mao | editando `docs/referencia/infra.md` |

Nenhuma pagina do backend e escrita a mao: `scripts/gen_ref_pages.py` percorre
`backend/app`, cria uma pagina por modulo e monta o indice da secao durante o
build. Um modulo novo aparece na documentacao sozinho — o que decide a qualidade
da pagina e a docstring que ele carrega.

## Convencao de docstring

O projeto usa o estilo **Google** (configurado em `mkdocs.yml`), em portugues,
sem acentos nos identificadores. Cada modulo abre com uma linha dizendo qual e a
responsabilidade dele no sistema; funcoes e classes publicas documentam o que
fazem, os argumentos que nao sao obvios e o que devolvem ou levantam.

```python
"""Roteia a conversa entre os provedores de LLM configurados pelo usuario."""


async def gerar_resposta(mensagens: list[Message], provedor: str) -> LLMResponse:
    """Envia o historico ao provedor e devolve a resposta normalizada.

    Args:
        mensagens: historico ja truncado para a janela de contexto do modelo.
        provedor: chave do provedor ativo (`ollama`, `anthropic`, ...).

    Returns:
        Resposta com texto, contagem de tokens e provedor efetivamente usado.

    Raises:
        LLMUnavailableError: quando nenhum provedor responde dentro do timeout.
    """
```

Funcoes privadas (prefixo `_`) ficam fora do site por filtro do mkdocstrings,
entao comentario interno nelas continua sendo comentario `#` normal.

## Build completo

`mkdocs build` gera so o backend e as paginas escritas a mao. Para incluir a
referencia Dart no mesmo site, use o script de build, que roda o mkdocs e em
seguida joga a saida do `dart doc` em `site/referencia/interface/api/`:

=== "Windows (PowerShell)"

    ```powershell
    ./scripts/build_docs.ps1
    ```

=== "Linux / macOS"

    ```bash
    ./scripts/build_docs.sh
    ```

O diretorio `site/` e artefato de build e esta no `.gitignore`; o que se versiona
sao as docstrings, as paginas manuais e a configuracao.
