"""Keep pytest entirely separate from the user's live detection database."""

import os

# Test modules import configuration and ``backend.app.db`` during collection.
# Set every mutable runtime path before those imports so pytest never writes
# into the API/Worker's live database, logs, APK store, evidence or exports.
_TEST_ROOT = "data/test-runtime"
os.environ["PRIVACY_DB_PATH"] = f"{_TEST_ROOT}/app.db"
os.environ["PRIVACY_APK_DIR"] = f"{_TEST_ROOT}/apks"
os.environ["PRIVACY_EVIDENCE_DIR"] = f"{_TEST_ROOT}/evidence"
os.environ["PRIVACY_EXPORT_DIR"] = f"{_TEST_ROOT}/exports"
os.environ["PRIVACY_LOG_DIR"] = f"{_TEST_ROOT}/logs"
os.environ["PRIVACY_FERNET_KEY_FILE"] = f"{_TEST_ROOT}/fernet.key"
