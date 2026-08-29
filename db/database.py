"""SQLite persistence for saved client projects (ported from the desktop app's database.py).

Path resolution is the only change from the desktop version: DB_PATH must be
configured at startup via configure(), pointing at Kivy's user_data_dir, since
Android apps can't write next to their own installed package like a desktop app can.
"""

import sqlite3
from datetime import date
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
    quote_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
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
    conn.executescript(SCHEMA)
    _migrate_add_missing_columns(conn)
    conn.commit()
    conn.close()


def consume_first_launch() -> bool:
    """Return whether this is the first launch for the installed app.

    The flag is stored alongside the app database in Kivy's ``user_data_dir``.
    That directory is removed on uninstall, so a new installation naturally sees
    onboarding again.  Recording it before the UI is shown also makes onboarding
    a true first-launch screen if the app is closed before tapping Get Started.
    """
    conn = get_connection()
    try:
        seen = conn.execute(
            "SELECT 1 FROM app_settings WHERE key = 'onboarding_seen'"
        ).fetchone()
        if seen is not None:
            return False

        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES ('onboarding_seen', '1')"
        )
        conn.commit()
        return True
    finally:
        conn.close()


def _migrate_add_missing_columns(conn: sqlite3.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS is a no-op on an already-existing table, so a column
    added after the app was first installed needs an explicit ALTER TABLE here."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(projects)")}
    if "country" not in existing:
        conn.execute("ALTER TABLE projects ADD COLUMN country TEXT NOT NULL DEFAULT ''")
    if "quote_data" not in existing:
        conn.execute("ALTER TABLE projects ADD COLUMN quote_data TEXT NOT NULL DEFAULT '{}'")


def create_project(fields: dict) -> int:
    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT INTO projects
            (client_name, project_location, contact_number, email, project_date,
             notes, monthly_kwh, daytime_ratio_pct, electricity_rate, country, quote_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fields["client_name"], fields["project_location"], fields["contact_number"],
            fields["email"], fields["project_date"], fields["notes"], fields["monthly_kwh"],
            fields["daytime_ratio_pct"], fields["electricity_rate"], fields.get("country", ""),
            fields.get("quote_data", "{}"),
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
            electricity_rate = ?, country = ?, quote_data = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            fields["client_name"], fields["project_location"], fields["contact_number"],
            fields["email"], fields["project_date"], fields["notes"], fields["monthly_kwh"],
            fields["daytime_ratio_pct"], fields["electricity_rate"], fields.get("country", ""),
            fields.get("quote_data", "{}"), project_id,
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


# --- Tier / subscription helpers ------------------------------------------------

FREE_PROJECT_LIMIT = 3

_DATE_WATERMARK_KEY = "date_watermark"
# ~2.7 years. A jump bigger than this in one reading is far more likely to be a
# bad API response or a fat-fingered device clock than real elapsed time, so
# it's treated as noise rather than ratcheted in -- see _trusted_today().
_MAX_TRUSTED_FORWARD_JUMP_DAYS = 1000


def count_projects() -> int:
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    conn.close()
    return count


def _trusted_today(conn: sqlite3.Connection) -> date:
    """Tamper-resistant "today", reusing an already-open connection.

    internet_time.today() is the best single estimate available (network-
    verified when a fetch has succeeded, the device clock otherwise) but is
    not trustworthy on its own: on a device that's offline for the trial's
    whole 7 days -- an ordinary case for a field solar installer -- it's just
    the device clock, and a user can wind that backward at any time to keep
    re-entering an unexpired trial window.

    Instead, persist the latest date ever computed here and never let the
    effective "today" go backward from it, regardless of what the clock says
    on a later call. A backward-set device clock is simply outrun by the
    watermark and has no effect; a forward-set one only ever pulls today
    forward (which can't extend anyone's access). The one failure mode this
    doesn't cover is a device that is rolled back *before* its very first use
    of the app -- there's no prior watermark yet to compare against, so that
    first reading has to be trusted as-is.
    """
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (_DATE_WATERMARK_KEY,)).fetchone()
    watermark = None
    if row:
        try:
            watermark = date.fromisoformat(row["value"])
        except ValueError:
            watermark = None

    import internet_time
    candidate = internet_time.today()

    if watermark is None:
        best = candidate
    elif candidate <= watermark:
        best = watermark
    elif (candidate - watermark).days > _MAX_TRUSTED_FORWARD_JUMP_DAYS:
        best = watermark  # implausible jump -- likely bad data, don't trust it
    else:
        best = candidate

    if best != watermark:
        conn.execute("DELETE FROM app_settings WHERE key = ?", (_DATE_WATERMARK_KEY,))
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)", (_DATE_WATERMARK_KEY, best.isoformat()),
        )
        conn.commit()
    return best


def get_trusted_today() -> date:
    """Tamper-resistant "today" for any trial/subscription date comparison --
    use this instead of internet_time.today() or datetime.date.today() for
    anything that gates a paid feature. See _trusted_today() for why."""
    conn = get_connection()
    try:
        return _trusted_today(conn)
    finally:
        conn.close()


def get_tier() -> str:
    conn = get_connection()
    row = conn.execute("SELECT value FROM app_settings WHERE key = 'tier'").fetchone()
    tier = row["value"] if row else "free"
    downgrade = False
    if tier == "pro":
        source_row = conn.execute("SELECT value FROM app_settings WHERE key = 'pro_source'").fetchone()
        source = source_row["value"] if source_row else None
        # Only a trial expires on a date check. A Play Store purchase's
        # validity is decided by billing.py re-querying Google Play, not by
        # comparing dates here -- otherwise a leftover trial_end from before
        # someone subscribed for real would downgrade a paying subscriber
        # back to Free the moment that old trial date passed.
        if source == "trial":
            trial_row = conn.execute("SELECT value FROM app_settings WHERE key = 'trial_end'").fetchone()
            trial_end = trial_row["value"] if trial_row else None
            if trial_end:
                try:
                    if _trusted_today(conn) > date.fromisoformat(trial_end):
                        downgrade = True
                except ValueError:
                    pass
    conn.close()
    if downgrade:
        set_tier("free")
        return "free"
    return tier


def set_tier(tier: str) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM app_settings WHERE key = 'tier'")
    conn.execute("INSERT INTO app_settings (key, value) VALUES ('tier', ?)", (tier,))
    conn.commit()
    conn.close()


def get_pro_source() -> str | None:
    """'trial' or 'purchase' -- which one 'pro' currently means, so get_tier()
    knows whether a trial_end date should ever expire it."""
    conn = get_connection()
    row = conn.execute("SELECT value FROM app_settings WHERE key = 'pro_source'").fetchone()
    conn.close()
    return row["value"] if row else None


def set_pro_source(source: str | None) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM app_settings WHERE key = 'pro_source'")
    if source is not None:
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('pro_source', ?)", (source,))
    conn.commit()
    conn.close()


def get_trial_end() -> str | None:
    conn = get_connection()
    row = conn.execute("SELECT value FROM app_settings WHERE key = 'trial_end'").fetchone()
    conn.close()
    return row["value"] if row else None


def set_trial_end(date_str: str | None) -> None:
    """Pass None to clear it (done once a real purchase supersedes a trial)."""
    conn = get_connection()
    conn.execute("DELETE FROM app_settings WHERE key = 'trial_end'")
    if date_str is not None:
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('trial_end', ?)", (date_str,))
    conn.commit()
    conn.close()
