"""Baixa o CLI do Infisical na versao fixada e confere o hash antes de aceitar.

Roda so no build da imagem. O hash esta gravado no Dockerfile, no repositorio: se o arquivo
publicado mudar (corrompido ou adulterado), o build falha em vez de embutir o binario. Sem
curl, sem apt e sem executar script remoto - so Python.

Uso: python fetch_infisical.py <versao> <amd64|arm64> <sha256> <destino>
"""

from __future__ import annotations

import hashlib
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

URL = "https://github.com/Infisical/cli/releases/download/v{version}/cli_{version}_linux_{arch}.tar.gz"


def main(version: str, arch: str, expected: str, target: str) -> int:
    if arch not in ("amd64", "arm64"):
        print(f"arquitetura sem suporte: {arch}", file=sys.stderr)
        return 2
    with urllib.request.urlopen(URL.format(version=version, arch=arch), timeout=120) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected.lower():
        print(f"hash do CLI nao confere: esperado {expected}, veio {digest}", file=sys.stderr)
        return 1
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        member = archive.extractfile("infisical")  # so este arquivo, por nome: sem caminho do tar
        if member is None:
            print("o pacote nao traz o binario infisical", file=sys.stderr)
            return 1
        binary = member.read()
    out = Path(target)
    out.write_bytes(binary)
    out.chmod(0o755)
    print(f"infisical {version} ({arch}) instalado em {out}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(*sys.argv[1:]))
