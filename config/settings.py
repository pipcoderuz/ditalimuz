"""di-talim.uz LMS — sozlamalar."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(BASE_DIR / ".env")


def env(name, default=""):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return env(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [x.strip() for x in env(name, default).split(",") if x.strip()]


SECRET_KEY = env("SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "daphne",                      # ASGI server (runserver ham WebSocket'ni qo'llab-quvvatlaydi)
    "unfold",                      # zamonaviy admin dizayni (django-unfold)
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "courses",
    "assessments",
    "gamification",
    "community",
    "analytics",
    "design",
    "channels",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",   # DEBUG=False da static fayllarni (Tailwind, Unfold) o'zi beradi
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.ApprovalMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "community.context_processors.counters",
                "design.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --- Real-time chat (Django Channels) ---
# REDIS_URL berilsa (production) — Redis; aks holda bitta jarayon uchun xotiradagi qatlam (development).
if env("REDIS_URL"):
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [env("REDIS_URL")]}}}
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

if env("DB_NAME"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME"),
            "USER": env("DB_USER"),
            "PASSWORD": env("DB_PASSWORD"),
            "HOST": env("DB_HOST", "localhost"),
            "PORT": env("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"

LANGUAGE_CODE = "uz"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Topshiriq ZIP fayli chegarasi
MAX_ZIP_MB = int(env("MAX_ZIP_MB", "25"))
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = int(env("HSTS_SECONDS", "3600"))


# --- django-unfold (Django admin mavzusi) ---
from django.urls import reverse_lazy  # noqa: E402


def _nav(title, icon, name):
    return {"title": title, "icon": icon, "link": reverse_lazy(name)}


UNFOLD = {
    "SITE_TITLE": "di-talim.uz",
    "SITE_HEADER": "di-talim.uz",
    "SITE_SUBHEADER": "Boshqaruv paneli",
    "SITE_URL": "/",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "BORDER_RADIUS": "10px",
    "COLORS": {
        "primary": {
            "50": "238 242 255", "100": "224 231 255", "200": "199 210 254", "300": "165 180 252", "400": "129 140 248",
            "500": "99 102 241", "600": "79 70 229", "700": "67 56 202", "800": "55 48 163", "900": "49 46 129", "950": "30 27 75",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {"title": "Asosiy", "items": [
                {"title": "Saytga qaytish", "icon": "home", "link": "/"},
                _nav("Boshqaruv paneli", "dashboard", "accounts:admin_panel"),
                _nav("Statistika", "monitoring", "analytics:overview"),
                _nav("Dizayn markazi", "palette", "accounts:design_center"),
                _nav("Chat yo'naltirish", "alt_route", "accounts:chat_routing"),
            ]},
            {"title": "Foydalanuvchilar", "items": [
                _nav("Foydalanuvchilar", "group", "admin:accounts_user_changelist"),
                _nav("Platforma sozlamalari", "settings", "admin:accounts_platformsettings_changelist"),
            ]},
            {"title": "O'quv jarayoni", "items": [
                _nav("Kurslar", "menu_book", "admin:courses_course_changelist"),
                _nav("Modullar", "folder", "admin:courses_module_changelist"),
                _nav("Mavzular", "article", "admin:courses_topic_changelist"),
                _nav("Yozilishlar", "how_to_reg", "admin:courses_enrollment_changelist"),
                _nav("Sertifikatlar", "workspace_premium", "admin:courses_certificate_changelist"),
            ]},
            {"title": "Baholash", "items": [
                _nav("Testlar", "quiz", "admin:assessments_quiz_changelist"),
                _nav("Topshiriqlar", "assignment", "admin:assessments_assignment_changelist"),
                _nav("Ochiq savollar", "help", "admin:assessments_openquestion_changelist"),
                _nav("Yuborilgan ishlar", "upload_file", "admin:assessments_submission_changelist"),
                _nav("Plagiat ogohlantirishlari", "content_copy", "admin:assessments_plagiarismflag_changelist"),
            ]},
            {"title": "Chat va forum", "items": [
                _nav("Chat xonalari", "forum", "admin:community_chatroom_changelist"),
                _nav("Forum mavzulari", "chat", "admin:community_thread_changelist"),
                _nav("Bildirishnomalar", "notifications", "admin:community_notification_changelist"),
                _nav("Yutuqlar", "emoji_events", "admin:gamification_userbadge_changelist"),
            ]},
            {"title": "Dizayn (kodsiz)", "items": [
                _nav("Sayt dizayni (rang, logo)", "palette", "admin:design_sitetheme_changelist"),
                _nav("Navbar elementlari", "menu", "admin:design_navitem_changelist"),
                _nav("Sahifa bloklari", "view_quilt", "admin:design_siteblock_changelist"),
                _nav("Formalar", "dynamic_form", "admin:design_formdefinition_changelist"),
                _nav("Forma javoblari", "inbox", "admin:design_formsubmission_changelist"),
            ]},
        ],
    },
}
