# Documentacao do codigo-fonte

Este site e gerado a partir do proprio codigo: as paginas do backend saem das
docstrings dos modulos Python via [mkdocstrings](https://mkdocstrings.github.io/),
e a referencia da interface sai dos comentarios `///` do Dart via `dart doc`.
Escrever a documentacao, portanto, e escrever docstring no modulo — nao ha um
segundo lugar para manter em dia.

O README do repositorio segue sendo o ponto de entrada de produto (o que a
aplicacao faz, como instalar, como configurar). Aqui esta o mapa de *como o
codigo esta organizado* e o que cada modulo expoe.

## Por onde comecar

<div class="grid cards" markdown>

- :material-api: **[Referencia do codigo](referencia/index.md)**

    Modulo a modulo do backend, da interface e da infraestrutura.

- :material-language-python: **[Backend](referencia/backend/app/index.md)**

    `app.core`, `app.models`, `app.routers`, `app.services`, `app.utils`.

- :material-flutter: **[Interface Flutter](referencia/interface.md)**

    Telas, widgets, providers e servicos locais do desktop.

- :material-docker: **[Infraestrutura](referencia/infra.md)**

    Compose, Dockerfiles, scripts de setup e variaveis de ambiente.

</div>

## Gerando o site

```bash
pip install -r backend/requirements-docs.txt
mkdocs serve          # preview em http://127.0.0.1:8000
mkdocs build          # site estatico em site/
```

Para gerar tambem a referencia Dart e juntar tudo em um unico site, use o script
de build descrito em [Referencia do codigo](referencia/index.md#build-completo).
