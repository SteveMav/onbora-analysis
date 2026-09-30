$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Création de l'environnement Python isolé..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& $venvPython -c "from importlib.metadata import distributions; import importlib.util as util; packages = {item.metadata['Name'].lower(): item.version for item in distributions()}; openai_version = tuple(int(part) for part in packages.get('openai', '0.0').split('.')[:2]); raise SystemExit(0 if openai_version >= (2, 43) and util.find_spec('openpyxl') and util.find_spec('dotenv') else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Mise à jour des dépendances Python (Responses API OpenAI)..."
    & $venvPython -m pip install --upgrade -r .\requirements.txt
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& $venvPython .\app.py
exit $LASTEXITCODE
