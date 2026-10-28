
import json
import threading
import time
from pathlib import Path

# Find the database file
DB = Path(__file__).parent / "data" / "db.json"

# Prevent simultaneous writes from interfering
_lock = threading.Lock()


# Read data from db.json
def load():
    return json.loads(DB.read_text(encoding="utf-8"))


# Save updated data into db.json
def save(db):
    with _lock:
        DB.write_text(
            json.dumps(db, indent=2),
            encoding="utf-8"
        )


# Record an activity in the audit log
def audit(db, who, event):
    db["audit"].insert(0, {
        "t": time.strftime("%H:%M:%S"),
        "who": who,
        "event": event
    })
