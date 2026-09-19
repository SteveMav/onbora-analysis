$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Création de l'environnement Python isolé..."
    python -m venv .venv
}

& $venvPython -c "from importlib.metadata import version; import google.genai, openpyxl, dotenv; parts=tuple(int(part) for part in version('google-genai').split('.')[:2]); raise SystemExit(0 if parts >= (2, 3) else 1)" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Mise à jour des dépendances Python (Interactions API Gemini)..."
    & $venvPython -m pip install --upgrade -r .\requirements.txt
}

& $venvPython .\app.py
