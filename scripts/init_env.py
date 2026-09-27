"""Create local credentials once; never overwrite an existing .env."""

import secrets
from pathlib import Path

path = Path(".env")
password = secrets.token_hex(24)
with path.open("x") as f:
    f.write(
        f"POSTGRES_PASSWORD={password}\nAPI_KEY={secrets.token_hex(32)}\n"
        f"DATABASE_URL=postgresql+psycopg://queuemaster:{password}@localhost:5432/queuemaster\n"
        "REDIS_URL=redis://localhost:6379/0\n"
    )
print("Created .env. Keep it private; use API_KEY as the X-API-Key header.")
