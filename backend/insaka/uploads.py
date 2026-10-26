"""Statements the customer (through the secure link) or the RM uploads.

A file is accepted only if it parses as a statement of the requested kind and belongs to
the account on the application; anything else is refused with the reason. The customer
must give consent before anything is stored. Uploaded files and the consent record live
in data/uploads/ (never committed), and the case's audit log records both.
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .parsing import ParseError, parse_statement

UPLOADS_DIR = Path("data/uploads")
CONSENTS = {
    "share": "I agree to share these statements with Absa Bank Zambia for this loan assessment.",
    "retention": "I understand they are kept only for the assessment period.",
    "dpa": "I understand they are processed under the Data Protection Act No. 3 of 2021.",
}
MAX_BYTES = 10 * 1024 * 1024


class UploadRejected(ValueError):
    """The file or the request cannot be accepted; the message says why."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record_path(uploads_dir: Path, client_id: str) -> Path:
    return Path(uploads_dir) / f"{client_id}.json"


def load_record(client_id: str, uploads_dir: Path = UPLOADS_DIR) -> dict:
    path = _record_path(uploads_dir, client_id)
    return json.loads(path.read_text("utf-8")) if path.exists() else {"consent": None, "files": {}}


def _save_record(client_id: str, record: dict, uploads_dir: Path) -> None:
    Path(uploads_dir).mkdir(parents=True, exist_ok=True)
    _record_path(uploads_dir, client_id).write_text(json.dumps(record, indent=2), "utf-8")


def record_consent(client_id: str, given: dict, uploads_dir: Path = UPLOADS_DIR) -> dict:
    missing = [k for k in CONSENTS if not given.get(k)]
    if missing:
        raise UploadRejected("Please tick every consent box before uploading.")
    record = load_record(client_id, uploads_dir)
    record["consent"] = {"at": _now(), "statements": CONSENTS}
    _save_record(client_id, record, uploads_dir)
    return record["consent"]


def accept_statement(client: dict, channel: str, data: bytes, by: str,
                     uploads_dir: Path = UPLOADS_DIR) -> dict:
    """Parse, check and store one statement PDF; returns a short summary."""
    cid = client["client_id"]
    if channel not in client["channels"]:
        raise UploadRejected(f"The application lists no {channel} account.")
    if not data:
        raise UploadRejected("The file is empty.")
    if len(data) > MAX_BYTES:
        raise UploadRejected("The file is larger than 10 MB.")
    if not data.startswith(b"%PDF"):
        raise UploadRejected("Please upload the statement as a PDF.")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{cid}_{channel}.pdf"
        path.write_bytes(data)
        try:
            statement = parse_statement(path, f"{cid}-{channel.upper()}")
        except ParseError as e:
            raise UploadRejected(f"This file could not be read as a statement: {e}") from e
    if statement.channel != channel:
        raise UploadRejected(f"This is a {statement.channel} statement, not {channel}.")
    expected = client["channels"][channel]
    if statement.account != expected:
        raise UploadRejected(f"This statement is for account {statement.account}, not the "
                             f"account on the application ({expected}).")
    Path(uploads_dir).mkdir(parents=True, exist_ok=True)
    (Path(uploads_dir) / f"{cid}_{channel}.pdf").write_bytes(data)
    rows = statement.rows
    summary = {"channel": channel, "at": _now(), "by": by, "rows": len(rows),
               "from": rows[0].date if rows else None, "to": rows[-1].date if rows else None}
    record = load_record(cid, uploads_dir)
    record["files"][channel] = summary
    _save_record(cid, record, uploads_dir)
    return summary
