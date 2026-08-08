#!/usr/bin/env python3
"""
================================================================================
VECTOR RESEARCH // HISTORICAL TELEMETRY DATABASE & AEROSPACE EVENT ENGINE
DOCUMENT REF: VR-MOBILE-DB-2026-V1
Ingests rolling NOAA SWPC telemetry into a local SQLite database, builds an
indexed historical archive, and flags active aerospace events for mobile alerts.
================================================================================
"""

import os
import json
import sqlite3
import urllib.request
from datetime import datetime, timezone, timedelta

DB_FILE = "vector_telemetry_archive.db"
MOBILE_PAYLOAD_FILE = "mobile_telemetry_feed.json"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/json'
}

# ------------------------------------------------------------------------------
# 1. DATABASE INIT & SCHEMA
# ------------------------------------------------------------------------------
def init_db():
    """Initializes SQLite historical archive table with indexed UTC timestamps."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS telemetry_archive (
            timestamp_utc TEXT PRIMARY KEY,
            solar_wind_vx REAL,
            imf_bz REAL,
            kp_index REAL,
            event_flag TEXT,
            event_severity TEXT,
            created_at TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON telemetry_archive(timestamp_utc)")
    conn.commit()
    conn.close()

# ------------------------------------------------------------------------------
# 2. AEROSPACE EVENT DETECTION ENGINE
# ------------------------------------------------------------------------------
def evaluate_aerospace_event(vx: float, bz: float, kp: float) -> tuple:
    """
    Evaluates telemetry against aerospace event thresholds:
    - Storm Level: Kp >= 4.5 (G1+ Storm)
    - Southward IMF: Bz <= -5.0 nT (Reconnection Driver)
    - High-Speed Stream: Vx >= 500 km/s (CME / HSS Impact)
    """
    tags = []
    severity = "QUIET"

    if kp >= 6.0 or bz <= -12.0 or vx >= 650.0:
        severity = "SEVERE_STORM_ALERT"
    elif kp >= 4.5 or bz <= -6.0 or vx >= 500.0:
        severity = "NOTICEABLE_AEROSPACE_EVENT"
    elif kp >= 3.0 or bz <= -3.0:
        severity = "UNSETTLED"

    if kp >= 4.5:
        tags.append(f"GEOMAGNETIC_STORM_KP_{kp:.1f}")
    if bz <= -5.0:
        tags.append(f"SOUTHWARD_BZ_{bz:.1f}nT")
    if vx >= 500.0:
        tags.append(f"HIGH_SPEED_STREAM_{vx:.0f}KMS")

    event_flag = "|".join(tags) if tags else "NOMINAL_BACKGROUND"
    return event_flag, severity

# ------------------------------------------------------------------------------
# 3. TELEMETRY INGESTION & PERSISTENT UPSERT
# ------------------------------------------------------------------------------
def fetch_and_archive_telemetry():
    """Fetches rolling NOAA feeds and upserts clean records into SQLite."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now_utc_str = datetime.now(timezone.utc).isoformat()

    # Ingest Solar Wind (Vx and Bz)
    sw_records = {}
    try:
        url_sw = "https://services.swpc.noaa.gov/products/geospace/propagated-solar-wind.json"
        req = urllib.request.Request(url_sw, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
            if len(data) > 1:
                headers = [str(h).lower() for h in data[0]]
                time_idx = headers.index("time_tag") if "time_tag" in headers else 0
                speed_idx = headers.index("speed") if "speed" in headers else 1
                bz_idx = headers.index("bz") if "bz" in headers else 6

                for row in data[1:]:
                    if len(row) > max(time_idx, speed_idx, bz_idx):
                        ts = row[time_idx]
                        try:
                            vx = float(row[speed_idx]) if row[speed_idx] is not None else None
                            bz = float(row[bz_idx]) if row[bz_idx] is not None else None
                            if vx and 200.0 <= vx <= 1200.0 and bz and -100.0 <= bz <= 100.0:
                                sw_records[ts] = (vx, bz)
                        except (ValueError, TypeError):
                            continue
    except Exception as e:
        print(f"[WARN // INGEST] Solar wind fetch warning: {e}")

    # Ingest Kp Index
    kp_records = {}
    try:
        url_kp = "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"
        req_k = urllib.request.Request(url_kp, headers=HEADERS)
        with urllib.request.urlopen(req_k, timeout=10) as resp:
            data_k = json.loads(resp.read().decode())
            if isinstance(data_k, list):
                for entry in data_k:
                    ts = entry.get("time_tag")
                    kp_val = entry.get("kp_index")
                    if ts and kp_val is not None:
                        try:
                            val = float(kp_val)
                            if 0.0 <= val <= 9.0:
                                kp_records[ts] = val
                        except (ValueError, TypeError):
                            continue
    except Exception as e:
        print(f"[WARN // INGEST] Kp index fetch warning: {e}")

    # Upsert clean combined records into SQLite
    records_inserted = 0
    for ts, (vx, bz) in sw_records.items():
        # Match nearest Kp or default to 1.0
        kp = kp_records.get(ts, 1.0)
        event_flag, severity = evaluate_aerospace_event(vx, bz, kp)

        cursor.execute("""
            INSERT INTO telemetry_archive (timestamp_utc, solar_wind_vx, imf_bz, kp_index, event_flag, event_severity, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(timestamp_utc) DO UPDATE SET
                solar_wind_vx=excluded.solar_wind_vx,
                imf_bz=excluded.imf_bz,
                kp_index=excluded.kp_index,
                event_flag=excluded.event_flag,
                event_severity=excluded.event_severity
        """, (ts, vx, bz, kp, event_flag, severity, now_utc_str))
        records_inserted += 1

    conn.commit()
    conn.close()
    print(f"[SUCCESS // DB] Processed and archived {records_inserted} telemetry records.")

# ------------------------------------------------------------------------------
# 4. MOBILE APP EXPORT & ALERT PAYLOAD GENERATOR
# ------------------------------------------------------------------------------
def generate_mobile_payload():
    """Generates a lightweight, queryable JSON payload for mobile apps."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Query last 72 hours of data
    cursor.execute("""
        SELECT timestamp_utc, solar_wind_vx, imf_bz, kp_index, event_flag, event_severity
        FROM telemetry_archive
        ORDER BY timestamp_utc DESC
        LIMIT 288
    """)
    rows = cursor.fetchall()

    # Query active aerospace events
    cursor.execute("""
        SELECT timestamp_utc, solar_wind_vx, imf_bz, kp_index, event_flag, event_severity
        FROM telemetry_archive
        WHERE event_severity IN ('NOTICEABLE_AEROSPACE_EVENT', 'SEVERE_STORM_ALERT')
        ORDER BY timestamp_utc DESC
        LIMIT 20
    """)
    event_rows = cursor.fetchall()
    conn.close()

    history = []
    for r in rows:
        history.append({
            "timestamp_utc": r[0],
            "vx_kms": r[1],
            "bz_nt": r[2],
            "kp": r[3],
            "event_tag": r[4],
            "severity": r[5]
        })

    active_events = []
    for er in event_rows:
        active_events.append({
            "timestamp_utc": er[0],
            "vx_kms": er[1],
            "bz_nt": er[2],
            "kp": er[3],
            "event_tag": er[4],
            "severity": er[5]
        })

    # Mobile notification state
    has_active_event = len(active_events) > 0
    latest_severity = active_events[0]["severity"] if has_active_event else "QUIET"

    mobile_data = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "mobile_alert_trigger": {
            "has_noticeable_event": has_active_event,
            "current_severity": latest_severity,
            "push_notification_text": (
                f"⚠️ AEROSPACE EVENT ALERT: {active_events[0]['event_tag']} detected!" 
                if has_active_event else "Geospace conditions nominal (Quiet)."
            )
        },
        "recent_events": active_events,
        "telemetry_history_72h": history
    }

    with open(MOBILE_PAYLOAD_FILE, "w") as f:
        json.dump(mobile_data, f, indent=2)

    print(f"[SUCCESS // MOBILE] Exported mobile payload with {len(active_events)} active event records.")

# ------------------------------------------------------------------------------
# 5. EXECUTION PIPELINE
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 80)
    print("VECTOR RESEARCH // TELEMETRY ARCHIVE & MOBILE EVENT ENGINE")
    print("=" * 80)
    init_db()
    fetch_and_archive_telemetry()
    generate_mobile_payload()
    print("=" * 80)
