param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8006,
    [switch]$StartSearxng
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Test-DockerReady {
    docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

Write-Host "Installation des dépendances Python..."
python -m pip install -r .\requirements.txt
if ($LASTEXITCODE -ne 0) { throw "L'installation des dépendances Python a échoué." }

$openaiEnabled = python -c "from config.settings import ONBORA_OPENAI_ENABLED; print(int(ONBORA_OPENAI_ENABLED))"
if ($LASTEXITCODE -ne 0) { throw "La configuration Onbora n'a pas pu être chargée." }
$needsSearxng = $StartSearxng -or (($openaiEnabled | Select-Object -Last 1).Trim() -ne "1")

if ($needsSearxng) {
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
            if (Test-DockerReady) { $ready = $true; break }
        }
        if (-not $ready) { throw "Docker Desktop n'a pas démarré à temps." }
    }

    Write-Host "Démarrage de SearXNG..."
    docker compose -f .\essai\docker-compose.yml up -d
    $searxngReady = $false
    foreach ($attempt in 1..30) {
        try {
            $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "http://127.0.0.1:8080/"
            $searxngReady = $true
            break
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $searxngReady) {
        docker compose -f .\essai\docker-compose.yml logs --tail 30 searxng
        throw "SearXNG n'est pas prêt."
    }
} else {
    Write-Host "Recherche OpenAI activée : un appel web par entreprise, puis synthèse des sources vérifiées."
    Write-Host "Pour démarrer aussi le moteur de secours SearXNG : .\lancer.ps1 -StartSearxng"
}

python manage.py migrate
python manage.py import_arsp .\liste_entreprises_arsp.xlsx

$hasAdmin = python manage.py shell -c "from django.contrib.auth import get_user_model; print(int(get_user_model().objects.filter(is_superuser=True).exists()))"
$hasAdminResult = ($hasAdmin | Select-Object -Last 1).Trim()
if ($hasAdminResult -ne "1") {
    Write-Host "Création du compte administrateur local..."
    python manage.py createsuperuser
}

$worker = Start-Process -FilePath "python" -ArgumentList "manage.py", "run_research_worker", "--loop", "--concurrency", "5" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
try {
    $serverUrl = "http://127.0.0.1:$Port/"
    Start-Process $serverUrl
    Write-Host "Onbora est accessible sur $serverUrl"
    Write-Host "Appuie sur Ctrl+C pour arrêter Django et le worker."
    python manage.py runserver "127.0.0.1:$Port"
} finally {
    if ($worker -and -not $worker.HasExited) { Stop-Process -Id $worker.Id }
}
