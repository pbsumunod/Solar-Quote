"""SQLite persistence for saved client projects (ported from the desktop app's database.py).

Path resolution is the only change from the desktop version: DB_PATH must be
configured at startup via configure(), pointing at Kivy's user_data_dir, since
Android apps can't write next to their own installed package like a desktop app can.
"""

import sqlite3
from pathlib import Path

DB_PATH: Path | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name TEXT NOT NULL DEFAULT '',
    project_location TEXT NOT NULL DEFAULT '',
    contact_number TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    project_date TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    monthly_kwh REAL NOT NULL DEFAULT 0,
    daytime_ratio_pct INTEGER NOT NULL DEFAULT 70,
    electricity_rate REAL NOT NULL DEFAULT 14.50,
    country TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def configure(base_dir: str) -> None:
    global DB_PATH
    DB_PATH = Path(base_dir) / "solar_client_finder.db"


def get_connection() -> sqlite3.Connection:
    if DB_PATH is None:
        raise RuntimeError("database.configure(base_dir) must be called before use")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.execute(SCHEMA)
    _migrate_add_missing_columns(conn)
    conn.commit()
    conn.close()


def _migrate_add_missing_columns(conn: sqlite3.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS is a no-op on an already-existing table, so a column
    added after the app was first installed needs an explicit ALTER TABLE here."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(projects)")}
    if "country" not in existing:
        conn.execute("ALTER TABLE projects ADD COLUMN country TEXT NOT NULL DEFAULT ''")


def create_project(fields: dict) -> int:
    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT INTO projects
            (client_name, project_location, contact_number, email, project_date,
             notes, monthly_kwh, daytime_ratio_pct, electricity_rate, country)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fields["client_name"], fields["project_location"], fields["contact_number"],
            fields["email"], fields["project_date"], fields["notes"], fields["monthly_kwh"],
            fields["daytime_ratio_pct"], fields["electricity_rate"], fields.get("country", ""),
        ),
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


def update_project(project_id: int, fields: dict) -> None:
    conn = get_connection()
    conn.execute(
        """
        UPDATE projects SET
            client_name = ?, project_location = ?, contact_number = ?, email = ?,
            project_date = ?, notes = ?, monthly_kwh = ?, daytime_ratio_pct = ?,
            electricity_rate = ?, country = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            fields["client_name"], fields["project_location"], fields["contact_number"],
            fields["email"], fields["project_date"], fields["notes"], fields["monthly_kwh"],
            fields["daytime_ratio_pct"], fields["electricity_rate"], fields.get("country", ""), project_id,
        ),
    )
    conn.commit()
    conn.close()


def get_project(project_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return row


def list_projects() -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    conn.close()
    return rows


def delete_project(project_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()


def duplicate_project(project_id: int) -> int:
    row = get_project(project_id)
    fields = dict(row)
    fields["client_name"] = f"{fields['client_name']} (Copy)"
    del fields["id"]
    del fields["created_at"]
    del fields["updated_at"]
    return create_project(fields)
