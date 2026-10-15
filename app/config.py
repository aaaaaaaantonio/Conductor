import os
from pathlib import Path

# Project root. Default file locations hang off it, so they don't depend on
# the directory Conductor is started from.
BASE_DIR = Path(__file__).resolve().parent.parent


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    # A typo here would otherwise surface as a bare int() traceback at import.
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {raw!r}") from None
    if value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {raw!r}")
    return value


DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'test_runner.db'}")

JENKINS_BASE_URL = os.environ.get("JENKINS_BASE_URL", "http://localhost:8080")
JENKINS_JOB_NAMES = {
    "java": os.environ.get("JENKINS_JOB_NAME_JAVA", "java-tests"),
    "python": os.environ.get("JENKINS_JOB_NAME_PYTHON", "python-tests"),
}

PYTHON_TEST_RUNNER_PATH = os.environ.get("PYTHON_TEST_RUNNER_PATH", "./run-python-tests.sh")

ALLURE_BASE_URL = os.environ.get("ALLURE_BASE_URL", "")
# Jira Server/DC with Zephyr; the Zephyr token is a Jira Personal Access Token.
JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "")

# Personal Jenkins/Allure tokens live in an encrypted HttpOnly cookie
# (app/credentials.py). Any string works as the key; changing it signs
# everyone out. Empty means a random per-process key (tokens are lost on
# restart) — fine for development only.
CONDUCTOR_SECRET_KEY = os.environ.get("CONDUCTOR_SECRET_KEY", "")
# Set to true once Conductor is served over HTTPS.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
# Sliding idle windows, in seconds: every request re-issues the cookie, so
# tokens expire only after this long without using Conductor.
CREDS_SESSION_IDLE_TTL = _int_env("CREDS_SESSION_IDLE_TTL", 12 * 3600)
CREDS_REMEMBER_IDLE_TTL = _int_env("CREDS_REMEMBER_IDLE_TTL", 30 * 86400)
# Re-issue the cookie at most this often, not on every single request.
CREDS_REFRESH_AFTER = _int_env("CREDS_REFRESH_AFTER", 60, minimum=0)
# Hard cap since the tokens were entered, however active the user is.
# 10 years by default — effectively "never" while still bounded.
CREDS_MAX_LIFETIME = _int_env("CREDS_MAX_LIFETIME", 10 * 365 * 86400)

# Browser-side Origin values accepted on POST/PUT/PATCH/DELETE, comma
# separated (e.g. "https://conductor.company.ru"). Empty: the request's own
# Host. Needed only behind a proxy that rewrites Host.
CONDUCTOR_ALLOWED_ORIGINS = [
    o.strip().rstrip("/") for o in os.environ.get("CONDUCTOR_ALLOWED_ORIGINS", "").split(",") if o.strip()
]

JOB_LOG_DIR = Path(os.environ.get("JOB_LOG_DIR", BASE_DIR / "job_logs"))
# Finished jobs and their log files are deleted after this many days.
JOB_RETENTION_DAYS = _int_env("JOB_RETENTION_DAYS", 5)
# The log panel shows this many last lines; the full log is downloadable.
LOG_TAIL_LINES = _int_env("LOG_TAIL_LINES", 200)
# Longer lines are shown in the browser by their last this-many characters;
# the log file keeps them whole.
LOG_LINE_MAX_CHARS = _int_env("LOG_LINE_MAX_CHARS", 5000)
