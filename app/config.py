import os

JENKINS_BASE_URL = os.environ.get("JENKINS_BASE_URL", "http://localhost:8080")
JENKINS_JOB_NAMES = {
    "java": os.environ.get("JENKINS_JOB_NAME_JAVA", "java-tests"),
    "python": os.environ.get("JENKINS_JOB_NAME_PYTHON", "python-tests"),
}

JAVA_TEST_RUNNER_PATH = os.environ.get("JAVA_TEST_RUNNER_PATH", "./run-java-tests.sh")
PYTHON_TEST_RUNNER_PATH = os.environ.get("PYTHON_TEST_RUNNER_PATH", "./run-python-tests.sh")

ALLURE_BASE_URL = os.environ.get("ALLURE_BASE_URL", "")

# Personal Jenkins/Allure tokens live in an encrypted HttpOnly cookie
# (app/credentials.py). Any string works as the key; changing it signs
# everyone out. Empty means a random per-process key (tokens are lost on
# restart) — fine for development only.
CONDUCTOR_SECRET_KEY = os.environ.get("CONDUCTOR_SECRET_KEY", "")
# Set to true once Conductor is served over HTTPS.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
# Sliding idle windows, in seconds: every request re-issues the cookie, so
# tokens expire only after this long without using Conductor.
CREDS_SESSION_IDLE_TTL = int(os.environ.get("CREDS_SESSION_IDLE_TTL", 12 * 3600))
CREDS_REMEMBER_IDLE_TTL = int(os.environ.get("CREDS_REMEMBER_IDLE_TTL", 30 * 86400))
# Re-issue the cookie at most this often, not on every single request.
CREDS_REFRESH_AFTER = int(os.environ.get("CREDS_REFRESH_AFTER", 60))
# Hard cap since the tokens were entered, however active the user is.
# 10 years by default — effectively "never" while still bounded.
CREDS_MAX_LIFETIME = int(os.environ.get("CREDS_MAX_LIFETIME", 10 * 365 * 86400))

JOB_LOG_DIR = os.environ.get("JOB_LOG_DIR", "job_logs")
# Finished jobs and their log files are deleted after this many days.
JOB_RETENTION_DAYS = int(os.environ.get("JOB_RETENTION_DAYS", 5))
