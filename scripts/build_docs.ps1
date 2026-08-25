# Gera a documentacao completa do codigo-fonte em site/:
#   - backend: mkdocs + mkdocstrings, a partir das docstrings de backend/app
#   - interface: dart doc, a partir dos comentarios /// de interface/lib
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Usa o python do venv do projeto quando existir.
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

Write-Host '==> mkdocs build (backend + paginas manuais)'
& $python -m mkdocs build --clean

Write-Host '==> dart doc (interface Flutter)'
if (Get-Command flutter -ErrorAction SilentlyContinue) {
    Push-Location (Join-Path $root 'interface')
    try {
        flutter pub get
        # A saida vai para dentro do site do mkdocs, entao o link relativo
        # referencia/interface/api/ funciona no site final.
        dart doc --output (Join-Path $root 'site\referencia\interface\api')
    }
    finally { Pop-Location }
}
else {
    Write-Warning 'flutter nao encontrado no PATH; pulando a referencia Dart.'
}

Write-Host "==> pronto: $(Join-Path $root 'site\index.html')"
