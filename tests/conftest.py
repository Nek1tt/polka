"""Keep test data out of the application's runtime directory."""
import os
import uuid
from pathlib import Path
os.environ['DATA_DIR'] = str(Path(__file__).resolve().parents[1] / 'test-runtime' / uuid.uuid4().hex)
# A developer's .env must not change test origins or enable real external calls.
os.environ['ALLOWED_ORIGINS'] = 'http://localhost:8000,http://127.0.0.1:8000'
os.environ['LLM_API_KEY'] = ''
os.environ['GOOGLE_VISION_API_KEY'] = ''
os.environ['TTL_SECONDS'] = '86400'
