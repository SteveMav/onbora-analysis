"""Settings for the internal Onbora research prototype.

Production credentials and storage endpoints are intentionally supplied only by
the deployment environment.  SQLite is the local development default.
"""

from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEBUG = os.environ.get("ONBORA_DEBUG", "1") == "1"
SECRET_KEY = os.environ.get("ONBORA_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "local-development-only-change-me"
    else:
        raise RuntimeError("ONBORA_SECRET_KEY must be set when ONBORA_DEBUG=0")
ALLOWED_HOSTS = [host for host in os.environ.get("ONBORA_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if host]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "research",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "research.context_processors.onbora_navigation",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("ONBORA_DATABASE_PATH", BASE_DIR / "db.sqlite3"),
        # Parallel collectors use short, serialized write transactions on SQLite.
        "OPTIONS": {"timeout": 30, "transaction_mode": "IMMEDIATE"},
    }
}

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "fr"
TIME_ZONE = "Africa/Kinshasa"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Local research-provider settings. SearXNG remains replaceable and is bound to
# localhost by the bundled Docker Compose configuration.
ONBORA_SEARXNG_URL = os.environ.get("ONBORA_SEARXNG_URL", "http://127.0.0.1:8080")
# Independent SerpApi test page; never selected by the regular research worker.
ONBORA_SERPAPI_API_KEY = (
    os.environ.get("SERPAPI_API_KEY") or os.environ.get("SERPAPI_KEY") or os.environ.get("SERPAPI", "")
)
ONBORA_SERPAPI_TIMEOUT_SECONDS = 35
ONBORA_SEARCH_RESULTS_PER_QUERY = int(os.environ.get("ONBORA_SEARCH_RESULTS_PER_QUERY", "10"))
ONBORA_ANALYSIS_LIMIT = int(os.environ.get("ONBORA_ANALYSIS_LIMIT", "8"))
ONBORA_RESCUE_ANALYSIS_LIMIT = int(os.environ.get("ONBORA_RESCUE_ANALYSIS_LIMIT", "4"))
ONBORA_LEAD_ANALYSIS_LIMIT = int(os.environ.get("ONBORA_LEAD_ANALYSIS_LIMIT", "4"))
ONBORA_PROFILE_ANALYSIS_LIMIT = int(os.environ.get("ONBORA_PROFILE_ANALYSIS_LIMIT", "3"))
ONBORA_MAX_PAGE_BYTES = int(os.environ.get("ONBORA_MAX_PAGE_BYTES", "2000000"))
# ARSP's public registry pages can exceed 2 MB; keep their separate cap bounded.
ONBORA_MAX_ARSP_PAGE_BYTES = int(os.environ.get("ONBORA_MAX_ARSP_PAGE_BYTES", "8000000"))

# Gemini is an optional, failure-tolerant complement: Google Search grounding is
# used when verified SearXNG pages provide no relevant evidence, then the model summarizes only evidence
# that Onbora fetched and persisted itself.
ONBORA_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ONBORA_GEMINI_ENABLED = (
    os.environ.get("ONBORA_GEMINI_ENABLED", "1") == "1" and bool(ONBORA_GEMINI_API_KEY)
)
ONBORA_GEMINI_MODEL = os.environ.get("ONBORA_GEMINI_MODEL", "gemini-3.5-flash-lite")
ONBORA_GEMINI_MAX_SEARCH_SOURCES = int(os.environ.get("ONBORA_GEMINI_MAX_SEARCH_SOURCES", "8"))
ONBORA_GEMINI_TIMEOUT_MS = int(os.environ.get("ONBORA_GEMINI_TIMEOUT_MS", "45000"))

# OpenAI performs the initial complete search with one hosted web call; SearXNG
# is the fallback when no OpenAI sources are returned. The local .env
# historically names this variable OPENAI; also accept the SDK-standard name.
ONBORA_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI", "")
ONBORA_OPENAI_ENABLED = (
    os.environ.get("ONBORA_OPENAI_ENABLED", "1") == "1" and bool(ONBORA_OPENAI_API_KEY)
)
ONBORA_OPENAI_MODEL = os.environ.get("ONBORA_OPENAI_MODEL", "gpt-6-luna")
ONBORA_OPENAI_MAX_SEARCH_SOURCES = int(os.environ.get("ONBORA_OPENAI_MAX_SEARCH_SOURCES", "5"))
ONBORA_OPENAI_TIMEOUT_SECONDS = int(os.environ.get("ONBORA_OPENAI_TIMEOUT_SECONDS", "45"))

# The commercial catalogue is trusted application configuration, never a path
# supplied by a web request.  The default points to the current local Orange
# catalogue while deployments can mount and version their own snapshot.
ONBORA_OFFER_CATALOG_PATH = Path(os.environ.get(
    "ONBORA_OFFER_CATALOG_PATH",
    BASE_DIR.parent / "onbora mvp" / "catalog" / "versions" / "v1" / "catalog.json",
))
ONBORA_LEAD_QUALIFICATION_ENABLED = os.environ.get("ONBORA_LEAD_QUALIFICATION_ENABLED", "1") == "1"

# TLS is terminated by the internal deployment boundary.  These settings stay
# off locally but fail closed in a non-debug deployment.
SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_HSTS_SECONDS = 31_536_000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = False
