"""Local campaign snapshots + append-only transition ledger using client transactions."""

import fcntl
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from failure_client.storage.repository import ClientRepository
from llm_afs.behavior import digest


class ResearchStore(ClientRepository):
    def __init__(self, root: Path):
        self.root = root.resolve()
        super().__init__(self.root / "campaign.sqlite3")
        with self.transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS research_state "
                "(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER, payload TEXT, sha256 TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS research_ledger "
                "(revision INTEGER PRIMARY KEY, utc TEXT, event TEXT, "
                "detail TEXT, state_sha256 TEXT)"
            )

    @contextmanager
    def exclusive(self):
        # OS-owned lock releases on process exit; the file is never removed/recreated.
        with (self.root / ".campaign.lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("another process owns this campaign") from None
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def load(self):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM research_state WHERE id=1").fetchone()
        if row is None:
            raise ValueError("campaign is not initialized")
        state = json.loads(row["payload"])
        if digest(state) != row["sha256"]:
            raise ValueError("campaign checkpoint digest mismatch")
        return state, row["revision"]

    def save(self, state, revision, event, detail=None):
        serialized = json.dumps(state, sort_keys=True, allow_nan=False)
        sha = digest(state)
        with self.transaction() as db:
            if revision == -1:
                db.execute("INSERT INTO research_state VALUES (1,0,?,?)", (serialized, sha))
            else:
                cursor = db.execute(
                    "UPDATE research_state SET revision=?,payload=?,sha256=? "
                    "WHERE id=1 AND revision=?",
                    (revision + 1, serialized, sha, revision),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("stale campaign checkpoint")
            db.execute(
                "INSERT INTO research_ledger VALUES (?,?,?,?,?)",
                (
                    revision + 1,
                    datetime.now(UTC).isoformat(),
                    event,
                    json.dumps(detail or {}, allow_nan=False),
                    sha,
                ),
            )
        return revision + 1

    def ledger(self):
        with self.transaction() as db:
            return [dict(r) for r in db.execute("SELECT * FROM research_ledger ORDER BY revision")]
