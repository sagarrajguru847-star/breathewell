"""BreatheWell: a small, local-first asthma tracking web app."""
from __future__ import annotations

import json
import os
import sqlite3
import csv
import io
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent
DB_PATH = ROOT / "breathewell.db"
STATIC = ROOT / "static"
PORT = int(os.environ.get("BREATHEWELL_PORT", "8001"))


def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_date TEXT NOT NULL,
        symptom_level INTEGER NOT NULL CHECK(symptom_level BETWEEN 0 AND 10),
        reliever_puffs INTEGER NOT NULL DEFAULT 0 CHECK(reliever_puffs BETWEEN 0 AND 50),
        peak_flow INTEGER,
        triggers TEXT NOT NULL DEFAULT '[]',
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )""")
    db.commit()
    return db


@contextmanager
def database():
    db = connect()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, payload, content_type="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else (json.dumps(payload).encode() if content_type.startswith("application/json") else payload.encode())
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/entries":
            with database() as db:
                rows = db.execute("SELECT * FROM entries ORDER BY entry_date DESC, id DESC LIMIT 500").fetchall()
            self.respond(200, [dict(r, triggers=json.loads(r["triggers"])) for r in rows])
        elif path == "/api/analytics":
            try:
                days = max(7, min(90, int(parse_qs(parsed.query).get("days", ["30"])[0])))
            except ValueError:
                days = 30
            end = date.today()
            start = end - timedelta(days=days - 1)
            with database() as db:
                rows = db.execute("SELECT * FROM entries WHERE entry_date BETWEEN ? AND ? ORDER BY entry_date, id", (start.isoformat(), end.isoformat())).fetchall()
            records = [dict(r, triggers=json.loads(r["triggers"])) for r in rows]
            grouped = {}
            for row in records:
                grouped.setdefault(row["entry_date"], []).append(row)
            daily = []
            for offset in range(days):
                day = (start + timedelta(days=offset)).isoformat()
                items = grouped.get(day, [])
                symptoms = [r["symptom_level"] for r in items]
                flows = [r["peak_flow"] for r in items if r["peak_flow"]]
                daily.append({
                    "date": day, "entry_count": len(items),
                    "symptom_avg": round(sum(symptoms) / len(symptoms), 1) if symptoms else None,
                    "symptom_max": max(symptoms) if symptoms else None,
                    "reliever_puffs": sum(r["reliever_puffs"] for r in items),
                    "peak_flow_avg": round(sum(flows) / len(flows)) if flows else None,
                    "triggers": sorted({t for r in items for t in r["triggers"]}),
                })
            logged = [item for item in daily if item["entry_count"]]
            symptoms = [r["symptom_level"] for r in records]
            flows = [r for r in records if r["peak_flow"]]
            trigger_days = {}
            for day, items in grouped.items():
                for trigger in {t for row in items for t in row["triggers"]}:
                    trigger_days.setdefault(trigger, []).append(day)
            patterns = [{"trigger": name, "days": len(set(dates))} for name, dates in trigger_days.items()]
            patterns.sort(key=lambda item: (-item["days"], item["trigger"].lower()))
            trend = None
            if len(logged) >= 6:
                split = len(logged) // 2
                first = [d["symptom_avg"] for d in logged[:split]]
                second = [d["symptom_avg"] for d in logged[split:]]
                delta = round(sum(second) / len(second) - sum(first) / len(first), 1)
                trend = {"change": delta, "first_half_avg": round(sum(first) / len(first), 1), "second_half_avg": round(sum(second) / len(second), 1)}
            self.respond(200, {
                "window_days": days, "start_date": start.isoformat(), "end_date": end.isoformat(),
                "logged_days": len(logged), "entry_count": len(records),
                "average_symptom": round(sum(symptoms) / len(symptoms), 1) if symptoms else None,
                "total_reliever_puffs": sum(r["reliever_puffs"] for r in records),
                "latest_peak_flow": flows[-1]["peak_flow"] if flows else None,
                "trend": trend, "trigger_days": patterns, "daily": daily,
                "entries": records[-90:],
            })
        elif path == "/api/export.csv":
            with database() as db:
                rows = db.execute("SELECT * FROM entries ORDER BY entry_date, id").fetchall()
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["date", "logged_at", "symptom_level_0_to_10", "reliever_puffs", "peak_flow_l_min", "triggers", "note"])
            for row in rows:
                writer.writerow([row["entry_date"], row["created_at"], row["symptom_level"], row["reliever_puffs"], row["peak_flow"] or "", ", ".join(json.loads(row["triggers"])), row["note"]])
            body = output.getvalue().encode("utf-8-sig")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=breathewell-checkins.csv")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/health":
            self.respond(200, {"ok": True, "service": "BreatheWell"})
        else:
            relative = "index.html" if path == "/" else path.lstrip("/")
            target = (STATIC / relative).resolve()
            if STATIC.resolve() not in target.parents and target != STATIC.resolve():
                self.respond(404, {"error": "Not found"}); return
            if not target.is_file():
                self.respond(404, {"error": "Not found"}); return
            mime = "text/html; charset=utf-8" if target.suffix == ".html" else "text/css; charset=utf-8" if target.suffix == ".css" else "text/javascript; charset=utf-8" if target.suffix == ".js" else "application/octet-stream"
            self.respond(200, target.read_bytes(), mime)

    def do_POST(self):
        if urlparse(self.path).path != "/api/entries":
            self.respond(404, {"error": "Not found"}); return
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            data = json.loads(raw)
            entry_date = date.fromisoformat(data.get("entry_date", "")).isoformat()
            symptom = int(data["symptom_level"])
            puffs = int(data.get("reliever_puffs", 0))
            peak = data.get("peak_flow")
            peak = int(peak) if peak not in (None, "") else None
            triggers = data.get("triggers", [])
            note = str(data.get("note", "")).strip()[:500]
            if not 0 <= symptom <= 10 or not 0 <= puffs <= 50 or (peak is not None and not 0 < peak < 2000):
                raise ValueError("Please check the values and try again.")
            if not isinstance(triggers, list) or len(triggers) > 12:
                raise ValueError("Please choose valid triggers.")
            with database() as db:
                cur = db.execute("INSERT INTO entries(entry_date,symptom_level,reliever_puffs,peak_flow,triggers,note,created_at) VALUES(?,?,?,?,?,?,?)",
                    (entry_date, symptom, puffs, peak, json.dumps([str(t)[:40] for t in triggers]), note, datetime.now().isoformat(timespec="seconds")))
                row = db.execute("SELECT * FROM entries WHERE id=?", (cur.lastrowid,)).fetchone()
            self.respond(201, dict(row, triggers=json.loads(row["triggers"])))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            self.respond(400, {"error": str(exc) or "Invalid entry."})

    def do_DELETE(self):
        parts = urlparse(self.path).path.rstrip("/").split("/")
        if len(parts) != 4 or parts[1:3] != ["api", "entries"]:
            self.respond(404, {"error": "Not found"}); return
        try:
            entry_id = int(parts[3])
            with database() as db:
                db.execute("DELETE FROM entries WHERE id=?", (entry_id,))
            self.respond(200, {"ok": True})
        except ValueError:
            self.respond(400, {"error": "Invalid entry id"})

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


if __name__ == "__main__":
    with database():
        pass
    print(f"BreatheWell is running at http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
