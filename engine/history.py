"""Check history (local SQLite file next to the reports): past checks, revisions per shipment, finding status.

- A shipment is identified by its invoice no. Checking it again with changed files creates a new revision;
  checking the very same files again reuses the existing record.
- A finding's identity (sig) = rule + document type + message + current value (+ -2, -3 for repeats), so the same problem is
  recognised again in the next revision. Status marks are stored per shipment + sig and therefore carry over.
- Status: open (default) | in_review | waiting | fixed | accepted | not_error. open, in_review and waiting still need
  work; fixed (resolved), accepted (real but no action required) and not_error (false alarm) are done.
  A finding that disappears in a later revision is shown as resolved automatically.
- Every change of status or note is appended to mark_log (who, when, from -> to, note): the reviewer's trail.
  The automated findings themselves are never changed.
"""
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path

STATUSES = ["open", "in_review", "waiting", "fixed", "accepted", "not_error"]
OPEN = ("open", "in_review", "waiting")          # still needs work
DONE = ("fixed", "accepted", "not_error")
_OPEN_SQL = "('open','in_review','waiting')"

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
  id INTEGER PRIMARY KEY, ts TEXT, shipment TEXT, revision INTEGER, name TEXT, out_dir TEXT,
  files TEXT, fingerprint TEXT, version TEXT, n_error INTEGER, n_warning INTEGER, n_minor INTEGER, n_info INTEGER);
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY, check_id INTEGER REFERENCES checks(id), no INTEGER, sig TEXT, key TEXT, severity TEXT,
  doc TEXT, doc_kind TEXT, page INTEGER, current TEXT, suggested TEXT, msg_en TEXT, msg_vi TEXT);
CREATE TABLE IF NOT EXISTS marks (
  shipment TEXT, sig TEXT, status TEXT, note TEXT, ts TEXT, PRIMARY KEY (shipment, sig));
CREATE TABLE IF NOT EXISTS mark_log (
  id INTEGER PRIMARY KEY, shipment TEXT, sig TEXT, ts TEXT, who TEXT, old_status TEXT, status TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS findings_check ON findings(check_id);
CREATE INDEX IF NOT EXISTS mark_log_sig ON mark_log(shipment, sig);
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

    def set_mark(self, shipment: str, sig: str, status: str, note: str = "", who: str = "") -> bool:
        """Record a reviewer decision. Returns False if nothing changed. Every change goes to mark_log."""
        assert status in STATUSES
        note = note or ""
        now = datetime.now().isoformat(timespec="seconds")
        with closing(self._db()) as db, db:
            old = db.execute("SELECT status, note FROM marks WHERE shipment=? AND sig=?", (shipment, sig)).fetchone()
            old_st, old_note = (old["status"], old["note"] or "") if old else ("open", "")
            if (old_st, old_note) == (status, note):
                return False
            if status == "open" and not note:
                db.execute("DELETE FROM marks WHERE shipment=? AND sig=?", (shipment, sig))
            else:
                db.execute("INSERT INTO marks (shipment, sig, status, note, ts) VALUES (?,?,?,?,?)"
                           " ON CONFLICT(shipment, sig) DO UPDATE SET status=excluded.status, note=excluded.note,"
                           " ts=excluded.ts", (shipment, sig, status, note, now))
            db.execute("INSERT INTO mark_log (shipment, sig, ts, who, old_status, status, note) VALUES (?,?,?,?,?,?,?)",
                       (shipment, sig, now, who, old_st, status, note if note != old_note else None))
            return True

    def log(self, shipment: str, sig: str) -> list[dict]:
        """The reviewer trail of one finding, newest first."""
        with closing(self._db()) as db:
            rows = db.execute("SELECT * FROM mark_log WHERE shipment=? AND sig=? ORDER BY id DESC", (shipment, sig))
            return [dict(r) for r in rows.fetchall()]

    # ------------------------------------------------------------------ read
    def marks(self, shipment: str) -> dict:
        """Reviewer decisions of a shipment: sig -> {status, note, ts}."""
        with closing(self._db()) as db:
            rows = db.execute("SELECT sig, status, note, ts FROM marks WHERE shipment=?", (shipment,)).fetchall()
            return {r["sig"]: dict(status=r["status"], note=r["note"] or "", ts=r["ts"]) for r in rows}

    def check(self, cid: int) -> dict | None:
        with closing(self._db()) as db:
            r = db.execute("SELECT * FROM checks WHERE id=?", (cid,)).fetchone()
            return dict(r) if r else None

    def checks(self, limit: int = 500) -> list[dict]:
        """Newest first, with the number of findings still open (not fixed / not an error)."""
        with closing(self._db()) as db:
            rows = db.execute(
                "SELECT c.*, (SELECT COUNT(*) FROM findings f LEFT JOIN marks m ON m.shipment=c.shipment AND m.sig=f.sig"
                f"  WHERE f.check_id=c.id AND f.severity!='INFO' AND COALESCE(m.status,'open') IN {_OPEN_SQL})"
                " AS n_open FROM checks c ORDER BY c.ts DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def findings(self, cid: int) -> list[dict]:
        with closing(self._db()) as db:
            rows = db.execute(
                "SELECT f.*, COALESCE(m.status,'open') AS status, COALESCE(m.note,'') AS note FROM findings f"
                " JOIN checks c ON c.id=f.check_id LEFT JOIN marks m ON m.shipment=c.shipment AND m.sig=f.sig"
                " WHERE f.check_id=? ORDER BY f.no", (cid,)).fetchall()
            return [dict(r) for r in rows]

    def all_findings(self, latest_only: bool = True, check_id: int | None = None) -> list[dict]:
        """Findings across reviews with check info and reviewer status. latest_only: newest revision of each shipment."""
        where, args = [], []
        if check_id:
            where.append("c.id=?")
            args.append(check_id)
        elif latest_only:
            where.append("c.revision=(SELECT MAX(revision) FROM checks c2 WHERE c2.shipment=c.shipment)")
        sql = ("SELECT f.*, c.id AS check_id, c.ts, c.shipment, c.revision, c.out_dir, COALESCE(m.status,'open') AS status,"
               " COALESCE(m.note,'') AS note, m.ts AS mark_ts FROM findings f JOIN checks c ON c.id=f.check_id"
               " LEFT JOIN marks m ON m.shipment=c.shipment AND m.sig=f.sig"
               + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY c.ts DESC, f.no")
        with closing(self._db()) as db:
            return [dict(r) for r in db.execute(sql, args).fetchall()]

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
