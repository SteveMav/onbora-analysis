$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Test-DockerReady {
    docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

if (-not (Test-DockerReady)) {
    $dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path -LiteralPath $dockerDesktop)) {
        throw "Docker Desktop n'est pas installé. Installe-le puis relance ce fichier."
    }

    Write-Host "Démarrage de Docker Desktop..."
    Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
    $ready = $false
    foreach ($attempt in 1..45) {
        Start-Sleep -Seconds 2
        if (Test-DockerReady) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        throw "Docker Desktop n'a pas démarré à temps. Ouvre Docker Desktop puis relance ce fichier."
    }
}

Write-Host "Démarrage de SearXNG..."
docker compose up -d

$searxngReady = $false
foreach ($attempt in 1..30) {
    try {
        $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "http://127.0.0.1:8080/"
        $searxngReady = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $searxngReady) {
    docker compose logs --tail 30 searxng
    throw "SearXNG n'est pas prêt. Consulte les messages ci-dessus."
}

python -c "import openpyxl, trafilatura" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installation de la petite dépendance Python..."
    python -m pip install -r .\requirements.txt
}

python .\app.py
