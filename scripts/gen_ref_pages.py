"""Gera as paginas de referencia da API do backend durante o build do mkdocs.

O script roda dentro do mkdocs (plugin `gen-files`) e nao escreve nada no disco:
para cada modulo em `backend/app` ele cria, em memoria, uma pagina Markdown com
uma diretiva `::: app.<modulo>` que o mkdocstrings expande lendo as docstrings
do codigo. Tambem monta o `SUMMARY.md` que o plugin `literate-nav` usa como
indice da secao de referencia, entao adicionar um modulo novo ao projeto ja o
faz aparecer na documentacao sem editar `mkdocs.yml`.
"""

from pathlib import Path

import mkdocs_gen_files

# Raiz do repositorio: este arquivo vive em <repo>/scripts/.
ROOT = Path(__file__).parent.parent
# `backend` entra no sys.path do griffe (ver `paths` em mkdocs.yml), por isso os
# identificadores dos modulos comecam em `app.`.
SRC = ROOT / "backend"
PACKAGE = "app"
# Prefixo das paginas geradas dentro de docs_dir.
REFERENCE_DIR = Path("referencia", "backend")

# Titulo amigavel por subpacote, usado nos cabecalhos do indice de navegacao.
SECTION_TITLES = {
    "core": "Core - configuracao, banco e seguranca",
    "models": "Models - contratos de API",
    "routers": "Routers - endpoints REST, SSE e WebSocket",
    "services": "Services - regras de negocio e integracoes",
    "utils": "Utils - agendador e utilitarios",
}

nav = mkdocs_gen_files.Nav()

for path in sorted((SRC / PACKAGE).rglob("*.py")):
    module_path = path.relative_to(SRC).with_suffix("")
    doc_path = path.relative_to(SRC).with_suffix(".md")
    full_doc_path = REFERENCE_DIR / doc_path

    parts = tuple(module_path.parts)

    if parts[-1] == "__init__":
        parts = parts[:-1]
        doc_path = doc_path.with_name("index.md")
        full_doc_path = full_doc_path.with_name("index.md")
    elif parts[-1].startswith("_"):
        # Modulos privados (`__main__`, helpers com underscore) ficam de fora.
        continue

    if not parts:
        continue

    # `app` vira "Backend"; subpacotes usam o titulo descritivo quando existir.
    nav_parts = list(parts)
    nav_parts[0] = "Backend"
    if len(nav_parts) > 1 and nav_parts[1] in SECTION_TITLES:
        nav_parts[1] = SECTION_TITLES[nav_parts[1]]
    nav[tuple(nav_parts)] = doc_path.as_posix()

    identifier = ".".join(parts)
    with mkdocs_gen_files.open(full_doc_path, "w") as fd:
        fd.write(f"# `{identifier}`\n\n")
        fd.write(f"::: {identifier}\n")

    # Liga o icone de "editar esta pagina" ao arquivo .py de origem.
    mkdocs_gen_files.set_edit_path(full_doc_path, Path("..", "..", "backend") / path.relative_to(SRC))

with mkdocs_gen_files.open(REFERENCE_DIR / "SUMMARY.md", "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())
