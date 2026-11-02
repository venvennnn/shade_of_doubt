import os
import tempfile

os.environ["ENVIRONMENT"] = "local"
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["LOCAL_STORAGE_DIR"] = tempfile.mkdtemp(prefix="sod-storage-")
os.environ["YOUCAM_API_KEY"] = "test-key"
os.environ["YOUCAM_UNIT_COST_PER_TASK"] = "12"
os.environ["YOU_CAM_MAX_CONCURRENCY"] = "2"
os.environ["YOUCAM_USER_DAILY_UNIT_CAP"] = "500"
os.environ["YOUCAM_GLOBAL_DAILY_UNIT_CAP"] = "5000"
os.environ["MIN_VALID_VARIANTS"] = "4"
os.environ["FRONTEND_ORIGIN"] = "http://localhost:3000"

from app.config import get_settings

get_settings.cache_clear()
