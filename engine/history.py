"""Check history (local SQLite file next to the reports): past checks, revisions per shipment, finding status.

- A shipment is identified by its invoice no. Checking it again with changed files creates a new revision;
  checking the very same files again reuses the existing record.
- A finding's identity (sig) = rule + document type + message + current value (+ -2, -3 for repeats), so the same problem is
  recognised again in the next revision. Status marks are stored per shipment + sig and therefore carry over.
- Status: open (default) | fixed | not_error | waiting. A finding that disappears in a later revision is
  shown as resolved automatically.
"""
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path

STATUSES = ["open", "fixed", "not_error", "waiting"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
  id INTEGER PRIMARY KEY, ts TEXT, shipment TEXT, revision INTEGER, name TEXT, out_dir TEXT,
  files TEXT, fingerprint TEXT, version TEXT, n_error INTEGER, n_warning INTEGER, n_minor INTEGER, n_info INTEGER);
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY, check_id INTEGER REFERENCES checks(id), no INTEGER, sig TEXT, key TEXT, severity TEXT,
  doc TEXT, doc_kind TEXT, page INTEGER, current TEXT, suggested TEXT, msg_en TEXT, msg_vi TEXT);
CREATE TABLE IF NOT EXISTS marks (
  shipment TEXT, sig TEXT, status TEXT, note TEXT, ts TEXT, PRIMARY KEY (shipment, sig));
CREATE INDEX IF NOT EXISTS findings_check ON findings(check_id);
CREATE INDEX IF NOT EXISTS checks_shipment ON checks(shipment);
"""


class History:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._db()) as db, db:
            db.executescript(SCHEMA)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    # ------------------------------------------------------------------ write
    @staticmethod
    def shipment_of(res) -> str:
        ci = next((d for d in res.docs if d.kind == "CI" and d.f.get("invoice_no")), None)
        return ci.f["invoice_no"].value if ci else res.name

    @staticmethod
    def sig(f) -> str:
        kind = f.docs[0].kind if f.docs else ""
        return hashlib.sha1(f"{f.key}|{kind}|{f.text('en')}|{f.current}".encode()).hexdigest()[:16]

    @classmethod
    def sigs(cls, findings) -> list[str]:
        """One unique id per finding. The same problem twice in one document (e.g. two identical address typos)
        gets -2, -3 ... in order, so ids stay unique within a check and stable across revisions."""
        seen, out = Counter(), []
        for f in findings:
            b = cls.sig(f)
            seen[b] += 1
            out.append(b if seen[b] == 1 else f"{b}-{seen[b]}")
        return out

    def record(self, res, version: str = "") -> int:
        """Save a check and return its id. The same files as the latest revision -> that revision's id."""
        ship = self.shipment_of(res)
        with closing(self._db()) as db, db:
            last = db.execute("SELECT id, fingerprint, revision FROM checks WHERE shipment=? ORDER BY revision DESC LIMIT 1",
                              (ship,)).fetchone()
            if last and res.fingerprint and last["fingerprint"] == res.fingerprint:
                db.execute("UPDATE checks SET ts=?, out_dir=? WHERE id=?",
                           (datetime.now().isoformat(timespec="seconds"), str(res.out_dir or ""), last["id"]))
                return last["id"]
            n = {s: sum(f.severity == s for f in res.findings) for s in ("ERROR", "WARNING", "MINOR", "INFO")}
            cur = db.execute(
                "INSERT INTO checks (ts, shipment, revision, name, out_dir, files, fingerprint, version,"
                " n_error, n_warning, n_minor, n_info) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), ship, (last["revision"] + 1) if last else 1, res.name,
                 str(res.out_dir or ""), json.dumps([d.name for d in res.docs], ensure_ascii=False), res.fingerprint,
                 version, n["ERROR"], n["WARNING"], n["MINOR"], n["INFO"]))
            cid = cur.lastrowid
            db.executemany(
                "INSERT INTO findings (check_id, no, sig, key, severity, doc, doc_kind, page, current, suggested,"
                " msg_en, msg_vi) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [(cid, i, sig, f.key, f.severity, f.doc_names[0] if f.docs else "",
                  f.docs[0].kind if f.docs else "", f.page, f.current, f.suggested, f.text("en"), f.text("vi"))
                 for i, (f, sig) in enumerate(zip(res.findings, self.sigs(res.findings)), 1)])
            return cid

    def set_mark(self, shipment: str, sig: str, status: str, note: str = ""):
        assert status in STATUSES
        with closing(self._db()) as db, db:
            if status == "open" and not note:
                db.execute("DELETE FROM marks WHERE shipment=? AND sig=?", (shipment, sig))
            else:
                db.execute("INSERT INTO marks (shipment, sig, status, note, ts) VALUES (?,?,?,?,?)"
                           " ON CONFLICT(shipment, sig) DO UPDATE SET status=excluded.status, note=excluded.note,"
                           " ts=excluded.ts", (shipment, sig, status, note, datetime.now().isoformat(timespec="seconds")))

    # ------------------------------------------------------------------ read
    def check(self, cid: int) -> dict | None:
        with closing(self._db()) as db:
            r = db.execute("SELECT * FROM checks WHERE id=?", (cid,)).fetchone()
            return dict(r) if r else None

    def checks(self, limit: int = 500) -> list[dict]:
        """Newest first, with the number of findings still open (not fixed / not an error)."""
        with closing(self._db()) as db:
            rows = db.execute(
                "SELECT c.*, (SELECT COUNT(*) FROM findings f LEFT JOIN marks m ON m.shipment=c.shipment AND m.sig=f.sig"
                "  WHERE f.check_id=c.id AND f.severity!='INFO' AND COALESCE(m.status,'open') IN ('open','waiting'))"
                " AS n_open FROM checks c ORDER BY c.ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def findings(self, cid: int) -> list[dict]:
        with closing(self._db()) as db:
            rows = db.execute(
                "SELECT f.*, COALESCE(m.status,'open') AS status, COALESCE(m.note,'') AS note FROM findings f"
                " JOIN checks c ON c.id=f.check_id LEFT JOIN marks m ON m.shipment=c.shipment AND m.sig=f.sig"
                " WHERE f.check_id=? ORDER BY f.no", (cid,)).fetchall()
            return [dict(r) for r in rows]

    def compare(self, cid: int) -> dict | None:
        """Against the previous revision of the same shipment: resolved / still there / new findings."""
        c = self.check(cid)
        if not c or c["revision"] <= 1:
            return None
        with closing(self._db()) as db:
            prev = db.execute("SELECT id, revision FROM checks WHERE shipment=? AND revision<? ORDER BY revision DESC"
                              " LIMIT 1", (c["shipment"], c["revision"])).fetchone()
        if not prev:
            return None
        now, before = self.findings(cid), self.findings(prev["id"])
        now_s, before_s = {f["sig"] for f in now}, {f["sig"] for f in before}
        return dict(prev_revision=prev["revision"],
                    resolved=[f for f in before if f["sig"] not in now_s],
                    still=[f for f in now if f["sig"] in before_s],
                    new=[f for f in now if f["sig"] not in before_s])

    def export(self, path: Path) -> Path:
        """Excel of every finding with its status and note (pilot feedback)."""
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        wb = Workbook()
        ws = wb.active
        ws.title = "Feedback"
        head = ["Checked", "Shipment", "Revision", "No", "Severity", "Rule", "Document", "Page", "Message (EN)",
                "Current", "Suggested", "Status", "Note"]
        ws.append(head)
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="34495E")
        with closing(self._db()) as db:
            rows = db.execute(
                "SELECT c.ts, c.shipment, c.revision, f.no, f.severity, f.key, f.doc, f.page, f.msg_en, f.current,"
                " f.suggested, COALESCE(m.status,'open'), COALESCE(m.note,'') FROM findings f JOIN checks c ON c.id=f.check_id"
                " LEFT JOIN marks m ON m.shipment=c.shipment AND m.sig=f.sig ORDER BY c.ts, f.no").fetchall()
        for r in rows:
            ws.append(list(r))
        for col, w in zip("ABCDEFGHIJKLM", (19, 16, 8, 5, 9, 18, 34, 6, 60, 22, 22, 11, 40)):
            ws.column_dimensions[col].width = w
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        wb.save(path)
        return path
