"""SQLite persistence for saved client projects (ported from the desktop app's database.py).

Path resolution is the only change from the desktop version: DB_PATH must be
configured at startup via configure(), pointing at Kivy's user_data_dir, since
Android apps can't write next to their own installed package like a desktop app can.
"""

import sqlite3
import json
import math
import os
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
    design_inputs TEXT NOT NULL DEFAULT '{}',
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
    if "design_inputs" not in existing:
        conn.execute("ALTER TABLE projects ADD COLUMN design_inputs TEXT NOT NULL DEFAULT '{}'")


def create_project(fields: dict) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO projects
                (client_name, project_location, contact_number, email, project_date,
                 notes, monthly_kwh, daytime_ratio_pct, electricity_rate, country, quote_data, design_inputs)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["client_name"], fields["project_location"], fields["contact_number"],
                fields["email"], fields["project_date"], fields["notes"], fields["monthly_kwh"],
                fields["daytime_ratio_pct"], fields["electricity_rate"], fields.get("country", ""),
                fields.get("quote_data", "{}"),
                fields.get("design_inputs", "{}"),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_project(project_id: int, fields: dict) -> None:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE projects SET
                client_name = ?, project_location = ?, contact_number = ?, email = ?,
                project_date = ?, notes = ?, monthly_kwh = ?, daytime_ratio_pct = ?,
                electricity_rate = ?, country = ?, quote_data = ?, design_inputs = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                fields["client_name"], fields["project_location"], fields["contact_number"],
                fields["email"], fields["project_date"], fields["notes"], fields["monthly_kwh"],
                fields["daytime_ratio_pct"], fields["electricity_rate"], fields.get("country", ""),
                fields.get("quote_data", "{}"), fields.get("design_inputs", "{}"), project_id,
            ),
        )
        if cursor.rowcount != 1:
            raise LookupError(f"Project {project_id} no longer exists")
        conn.commit()
    finally:
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
    try:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
    finally:
        conn.close()


def duplicate_project(project_id: int) -> int:
    row = get_project(project_id)
    if row is None:
        raise LookupError(f"Project {project_id} no longer exists")
    fields = dict(row)
    fields["client_name"] = f"{fields['client_name']} (Copy)"
    del fields["id"]
    del fields["created_at"]
    del fields["updated_at"]
    return create_project(fields)


def set_setting(key: str, value: str | None) -> None:
    conn = get_connection()
    try:
        with conn:
            if value is None:
                conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
            else:
                conn.execute("INSERT INTO app_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    finally:
        conn.close()


def get_setting(key: str) -> str | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
    finally:
        conn.close()


def save_draft(data: dict | None) -> None:
    """Recover incomplete quotes without treating them as validated saved projects."""
    set_setting("quote_draft_v1", json.dumps(data, allow_nan=False) if data is not None else None)


def load_draft() -> dict | None:
    try:
        data = json.loads(get_setting("quote_draft_v1") or "null")
        return data if isinstance(data, dict) else None
    except (TypeError, ValueError):
        return None


def export_projects(path: str) -> None:
    """User-controlled backup contains projects only, never subscription tokens/settings."""
    data = {"format": "solarquote-projects", "version": 1,
            "projects": [dict(row) for row in list_projects()]}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def import_projects(path: str, max_new_projects: int | None = None) -> list[int]:
    """Validate the complete backup before appending projects in one transaction."""
    from logic.models import Project
    target = Path(path)
    if target.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Backup exceeds 20 MB.")
    data = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("format") != "solarquote-projects" or data.get("version") != 1:
        raise ValueError("This is not a supported SolarQuote project backup.")
    records = data.get("projects")
    if not isinstance(records, list) or len(records) > 10000:
        raise ValueError("Invalid project list.")
    if max_new_projects is not None and len(records) > max_new_projects:
        raise ValueError("This backup exceeds the available saved-project limit.")
    fields_list = []
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("Invalid project in backup.")
        try:
            _validate_backup_inputs(row)
            project = Project.from_row(row)
            if not project.client_name or not all(math.isfinite(float(v)) for v in (project.monthly_kwh, project.electricity_rate)):
                raise ValueError("Invalid project values.")
            if project.monthly_kwh <= 0 or project.electricity_rate < 0 or not 0 <= project.daytime_ratio_pct <= 100:
                raise ValueError("Invalid consumption or tariff.")
            if project.project_date:
                date.fromisoformat(project.project_date)
            quote = json.loads(row.get("quote_data", "{}"))
            if not isinstance(quote, dict):
                raise ValueError("Invalid quote state.")
            _validate_backup_quote(quote)
            fields = project.to_fields()
            fields["quote_data"] = json.dumps(quote, allow_nan=False)
            fields_list.append(fields)
        except (KeyError, TypeError, OverflowError) as exc:
            raise ValueError("Incomplete project in backup.") from exc
    conn = get_connection()
    ids = []
    try:
        with conn:
            if max_new_projects is not None and conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] + len(fields_list) > FREE_PROJECT_LIMIT:
                raise ValueError("Backup exceeds the free saved-project limit.")
            for fields in fields_list:
                columns = list(fields)
                sql = "INSERT INTO projects (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")"
                ids.append(conn.execute(sql, tuple(fields.values())).lastrowid)
    finally:
        conn.close()
    return ids


def _validate_backup_inputs(row: dict) -> None:
    for field in ("client_name", "project_location", "contact_number", "email", "project_date", "notes", "country"):
        value = row.get(field, "")
        if not isinstance(value, str) or len(value) > (65536 if field == "notes" else 4096):
            raise ValueError(f"Invalid {field.replace('_', ' ')} in backup.")
    for field, low, high in (("monthly_kwh", 0.01, 1e9), ("electricity_rate", 0, 1e6), ("daytime_ratio_pct", 0, 100)):
        value = row.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"Invalid {field.replace('_', ' ')} in backup.")
    inputs = json.loads(row.get("design_inputs", "{}"))
    if not isinstance(inputs, dict):
        raise ValueError("Invalid equipment inputs in backup.")
    if "storage_enabled" in inputs and not isinstance(inputs["storage_enabled"], bool):
        raise ValueError("Invalid storage choice in backup.")
    for field, low, high, optional in (
        ("peak_load_kw", 0.01, 10000, True), ("surge_load_kw", 0.01, 10000, True),
        ("site_latitude", -90, 90, True), ("site_longitude", -180, 180, True),
        ("site_tilt_deg", 0, 90, False), ("site_azimuth_deg", 0, 360, False), ("site_shading_pct", 0, 100, False),
    ):
        if field not in inputs or (optional and inputs[field] is None):
            continue
        value = inputs[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"Invalid {field.replace('_', ' ')} in backup.")
    if (inputs.get("site_latitude") is None) != (inputs.get("site_longitude") is None):
        raise ValueError("Backup coordinates must include latitude and longitude.")
    if inputs.get("peak_load_kw") and inputs.get("surge_load_kw") and inputs["surge_load_kw"] < inputs["peak_load_kw"]:
        raise ValueError("Backup starting demand is below peak demand.")


def _validate_backup_quote(quote: dict) -> None:
    """Legacy partial quotes are accepted; present steps must be safe to restore."""
    step_names = ("consumption", "solar", "battery", "system_design", "simulation", "roi", "report")
    if any(name in quote and not isinstance(quote[name], dict) for name in step_names):
        raise ValueError("Invalid quote step in backup.")
    from logic.quote_validation import validate_hourly_profile, validate_weather_mix, validate_quote_steps
    calculation_steps = ("consumption", "solar", "battery", "system_design", "simulation", "roi")
    if all(name in quote for name in calculation_steps):
        error = validate_quote_steps(quote)
        if error:
            raise ValueError(error)
    for step, field, validator in (
        ("consumption", "hourly_pct", validate_hourly_profile), ("roi", "weather_mix", validate_weather_mix),
    ):
        if field in quote.get(step, {}):
            error = validator(quote[step][field])
            if error:
                raise ValueError(error)
    solar = quote.get("solar", {})
    monthly = solar.get("monthly_peak_sun_hours", [])
    if not isinstance(monthly, list) or (monthly and (len(monthly) != 12 or any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 24 for v in monthly
    ))):
        raise ValueError("Invalid monthly solar resource in backup.")
    if not isinstance(solar.get("resource_metadata", {}), dict):
        raise ValueError("Invalid solar resource metadata in backup.")


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
