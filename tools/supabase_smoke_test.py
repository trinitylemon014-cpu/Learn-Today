import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "media").strip() or "media"

if not SUPABASE_URL or not (SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY):
    print("Supabase environment is not configured yet.")
    print("Please add these values to .env:")
    print("- SUPABASE_URL")
    print("- SUPABASE_ANON_KEY")
    print("- SUPABASE_SERVICE_ROLE_KEY (recommended for inserts)")
    sys.exit(1)

key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
client = create_client(SUPABASE_URL, key)

# 1) Upload a tiny text file to storage
storage_path = "smoke-tests/hello.txt"
content = b"Hello from Learn Together smoke test"
upload_response = client.storage.from_(BUCKET).upload(
    storage_path,
    content,
    file_options={"content-type": "text/plain"},
)
print("UPLOAD_OK", upload_response)

public_url = client.storage.from_(BUCKET).get_public_url(storage_path)
print("PUBLIC_URL", public_url)

# 2) Insert one row into the users table
email = f"smoke-test-{os.urandom(4).hex()}@example.com"
insert_response = client.table("users").insert({
    "name": "Smoke Test User",
    "email": email,
    "password": "smoke-test-password",
    "role": "student",
    "status": "approved",
}).execute()
print("INSERT_OK", insert_response.data)
