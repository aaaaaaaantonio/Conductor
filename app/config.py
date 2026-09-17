import os

JENKINS_BASE_URL = os.environ.get("JENKINS_BASE_URL", "http://localhost:8080")
JENKINS_POLL_INTERVAL_SECONDS = float(os.environ.get("JENKINS_POLL_INTERVAL_SECONDS", "5"))
JENKINS_JOB_NAMES = {
    "java": os.environ.get("JENKINS_JOB_NAME_JAVA", "java-tests"),
    "python": os.environ.get("JENKINS_JOB_NAME_PYTHON", "python-tests"),
}

JAVA_TEST_RUNNER_PATH = os.environ.get("JAVA_TEST_RUNNER_PATH", "./run-java-tests.sh")
PYTHON_TEST_RUNNER_PATH = os.environ.get("PYTHON_TEST_RUNNER_PATH", "./run-python-tests.sh")
