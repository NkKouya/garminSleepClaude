"""睡眠の中間表現を SQLite に蓄積・抽出する。

標準ライブラリ sqlite3 のみ使用（追加依存なし）。
- nights:   1夜1行の特徴量（intermediate.build_intermediate の features をフラット化）
- timeline: 5分粒度の時系列（1夜あたり約70行）

LLM 分析は行わない。データの整列・格納・抽出のみ。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "sleep.db")

_NIGHTS_COLUMNS = [
    "date", "sleep_score", "sleep_quality", "bed_time", "wake_time",
    "deep_min", "light_min", "rem_min", "awake_min", "cycles",
    "awakenings_count", "awakenings_times",
    "hr_onset", "hr_nadir", "hr_nadir_time", "hr_resting",
    "hrv_start", "hrv_end", "hrv_trend", "hrv_avg_overnight", "hrv_status",
    "spo2_avg", "spo2_lowest", "spo2_desat_count", "spo2_desat_total_min",
    "spo2_desat_lowest", "spo2_desat_events",
    "resp_avg", "resp_high", "resp_low", "resp_disruptions",
    "bb_start", "bb_end", "bb_change", "avg_stress", "restless_moments",
    "created_at",
]

_TIMELINE_COLUMNS = [
    "date", "bin_index", "t", "stage", "hr", "hrv", "spo2", "resp", "stress", "bb",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nights (
    date TEXT PRIMARY KEY,
    sleep_score INTEGER,
    sleep_quality TEXT,
    bed_time TEXT,
    wake_time TEXT,
    deep_min INTEGER,
    light_min INTEGER,
    rem_min INTEGER,
    awake_min INTEGER,
    cycles INTEGER,
    awakenings_count INTEGER,
    awakenings_times TEXT,
    hr_onset INTEGER,
    hr_nadir INTEGER,
    hr_nadir_time TEXT,
    hr_resting INTEGER,
    hrv_start REAL,
    hrv_end REAL,
    hrv_trend TEXT,
    hrv_avg_overnight REAL,
    hrv_status TEXT,
    spo2_avg REAL,
    spo2_lowest INTEGER,
    spo2_desat_count INTEGER,
    spo2_desat_total_min INTEGER,
    spo2_desat_lowest INTEGER,
    spo2_desat_events TEXT,
    resp_avg REAL,
    resp_high REAL,
    resp_low REAL,
    resp_disruptions INTEGER,
    bb_start INTEGER,
    bb_end INTEGER,
    bb_change INTEGER,
    avg_stress REAL,
    restless_moments INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS timeline (
    date TEXT,
    bin_index INTEGER,
    t TEXT,
    stage TEXT,
    hr REAL,
    hrv REAL,
    spo2 REAL,
    resp REAL,
    stress REAL,
    bb REAL,
    PRIMARY KEY (date, bin_index)
);

CREATE INDEX IF NOT EXISTS idx_timeline_date ON timeline(date);
"""


def connect(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def drop_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("DROP TABLE IF EXISTS nights; DROP TABLE IF EXISTS timeline;")
    conn.commit()


def has_date(conn: sqlite3.Connection, date: str) -> bool:
    cur = conn.execute("SELECT 1 FROM nights WHERE date = ?", (date,))
    return cur.fetchone() is not None


def flatten_features(inter: dict) -> dict:
    """中間表現のネストした features を nights の1行（フラットdict）に変換する。"""
    f = inter.get("features") or {}
    st = f.get("stages") or {}
    awk = f.get("awakenings") or {}
    hr = f.get("hr") or {}
    hrv = f.get("hrv") or {}
    spo2 = f.get("spo2") or {}
    desat = spo2.get("desaturation") or {}
    resp = f.get("respiration") or {}
    rec = f.get("recovery") or {}

    return {
        "date": inter.get("date"),
        "sleep_score": f.get("sleep_score"),
        "sleep_quality": f.get("sleep_quality"),
        "bed_time": f.get("bed_time"),
        "wake_time": f.get("wake_time"),
        "deep_min": st.get("deep_min"),
        "light_min": st.get("light_min"),
        "rem_min": st.get("rem_min"),
        "awake_min": st.get("awake_min"),
        "cycles": st.get("cycles"),
        "awakenings_count": awk.get("count"),
        "awakenings_times": json.dumps(awk.get("times") or [], ensure_ascii=False),
        "hr_onset": hr.get("onset"),
        "hr_nadir": hr.get("nadir"),
        "hr_nadir_time": hr.get("nadir_time"),
        "hr_resting": hr.get("resting"),
        "hrv_start": hrv.get("start"),
        "hrv_end": hrv.get("end"),
        "hrv_trend": hrv.get("trend"),
        "hrv_avg_overnight": hrv.get("avg_overnight"),
        "hrv_status": hrv.get("status"),
        "spo2_avg": spo2.get("avg"),
        "spo2_lowest": spo2.get("lowest"),
        "spo2_desat_count": desat.get("count"),
        "spo2_desat_total_min": desat.get("total_min"),
        "spo2_desat_lowest": desat.get("lowest"),
        "spo2_desat_events": json.dumps(desat.get("events") or [], ensure_ascii=False),
        "resp_avg": resp.get("avg"),
        "resp_high": resp.get("high"),
        "resp_low": resp.get("low"),
        "resp_disruptions": resp.get("disruptions"),
        "bb_start": rec.get("body_battery_start"),
        "bb_end": rec.get("body_battery_end"),
        "bb_change": rec.get("body_battery_change"),
        "avg_stress": rec.get("avg_stress"),
        "restless_moments": rec.get("restless_moments"),
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


def load_intermediate(conn: sqlite3.Connection, date: str) -> Optional[dict]:
    """DB（nights 1行 + timeline 該当日）から中間表現(inter)を復元する。

    flatten_features の逆変換。intermediate.build_intermediate と同じネスト構造
    （{date, features:{...}, timeline:[...]}）を返す。該当日が無ければ None。
    """
    night = conn.execute("SELECT * FROM nights WHERE date = ?", (date,)).fetchone()
    if night is None:
        return None

    def _loads(value):
        try:
            return json.loads(value) if value else []
        except (json.JSONDecodeError, TypeError):
            return []

    features = {
        "sleep_score": night["sleep_score"],
        "sleep_quality": night["sleep_quality"],
        "bed_time": night["bed_time"],
        "wake_time": night["wake_time"],
        "stages": {
            "deep_min": night["deep_min"],
            "light_min": night["light_min"],
            "rem_min": night["rem_min"],
            "awake_min": night["awake_min"],
            "cycles": night["cycles"],
        },
        "awakenings": {
            "count": night["awakenings_count"],
            "times": _loads(night["awakenings_times"]),
        },
        "hr": {
            "onset": night["hr_onset"],
            "nadir": night["hr_nadir"],
            "nadir_time": night["hr_nadir_time"],
            "resting": night["hr_resting"],
        },
        "hrv": {
            "start": night["hrv_start"],
            "end": night["hrv_end"],
            "trend": night["hrv_trend"],
            "avg_overnight": night["hrv_avg_overnight"],
            "status": night["hrv_status"],
        },
        "spo2": {
            "avg": night["spo2_avg"],
            "lowest": night["spo2_lowest"],
            "desaturation": {
                "count": night["spo2_desat_count"],
                "total_min": night["spo2_desat_total_min"],
                "lowest": night["spo2_desat_lowest"],
                "events": _loads(night["spo2_desat_events"]),
            },
        },
        "respiration": {
            "avg": night["resp_avg"],
            "high": night["resp_high"],
            "low": night["resp_low"],
            "disruptions": night["resp_disruptions"],
        },
        "recovery": {
            "body_battery_start": night["bb_start"],
            "body_battery_end": night["bb_end"],
            "body_battery_change": night["bb_change"],
            "avg_stress": night["avg_stress"],
            "restless_moments": night["restless_moments"],
        },
    }

    tl_rows = conn.execute(
        "SELECT t, stage, hr, hrv, spo2, resp, stress, bb "
        "FROM timeline WHERE date = ? ORDER BY bin_index",
        (date,),
    ).fetchall()
    timeline = [
        {
            "t": r["t"], "stage": r["stage"], "hr": r["hr"], "hrv": r["hrv"],
            "spo2": r["spo2"], "resp": r["resp"], "stress": r["stress"], "bb": r["bb"],
        }
        for r in tl_rows
    ]

    return {"date": night["date"], "features": features, "timeline": timeline}


def upsert_night(conn: sqlite3.Connection, inter: dict) -> None:
    """nights 1行 ＋ timeline の該当日を冪等に格納する（既存は置換）。"""
    date = inter.get("date")
    if not date:
        raise ValueError("inter['date'] が空です")

    row = flatten_features(inter)
    placeholders = ", ".join("?" for _ in _NIGHTS_COLUMNS)
    conn.execute(
        f"INSERT OR REPLACE INTO nights ({', '.join(_NIGHTS_COLUMNS)}) "
        f"VALUES ({placeholders})",
        [row.get(col) for col in _NIGHTS_COLUMNS],
    )

    # timeline は該当日を一旦削除して入れ直す（再実行で重複しない）
    conn.execute("DELETE FROM timeline WHERE date = ?", (date,))
    tl_rows = []
    for i, r in enumerate(inter.get("timeline") or []):
        tl_rows.append((
            date, i, r.get("t"), r.get("stage"),
            r.get("hr"), r.get("hrv"), r.get("spo2"),
            r.get("resp"), r.get("stress"), r.get("bb"),
        ))
    if tl_rows:
        conn.executemany(
            f"INSERT INTO timeline ({', '.join(_TIMELINE_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _TIMELINE_COLUMNS)})",
            tl_rows,
        )
    conn.commit()


def summary(conn: sqlite3.Connection) -> dict:
    night = conn.execute(
        "SELECT count(*) AS n, min(date) AS first, max(date) AS last, "
        "round(avg(sleep_score), 1) AS avg_score FROM nights"
    ).fetchone()
    tl = conn.execute("SELECT count(*) AS n FROM timeline").fetchone()
    return {
        "nights": night["n"],
        "first_date": night["first"],
        "last_date": night["last"],
        "avg_score": night["avg_score"],
        "timeline_rows": tl["n"],
    }


if __name__ == "__main__":
    # DBの中身を要約表示
    import sys

    db = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    conn = connect(db)
    init_schema(conn)
    print(json.dumps(summary(conn), ensure_ascii=False, indent=2))
