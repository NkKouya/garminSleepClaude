"""1週間分の中間表現から週次集計（週平均・ばらつき・夜別の黄金90分指標）を作る。

LLM 分析は行わない（intermediate.py と同じ純データ変換層）。
入力は database.load_intermediate の戻り値（{date, features, timeline}）のリスト。
"""
from __future__ import annotations

import statistics

# タイムラインのビン幅（分）。intermediate.BIN_MINUTES と一致させる。
BIN_MINUTES = 5
# 黄金の90分 = 入眠後90分 = 18ビン（×5分）。
GOLDEN_WINDOW_BINS = 90 // BIN_MINUTES


def _to_minutes(hhmm: str | None) -> int | None:
    """'HH:MM' を 0時起点の分に変換する。就寝の日跨ぎ補正は呼び出し側で行う。"""
    if not hhmm or ":" not in hhmm:
        return None
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def _minutes_to_hhmm(total: float) -> str:
    """0時起点の分（24h超は丸める）を 'HH:MM' に戻す。"""
    t = int(round(total)) % (24 * 60)
    return f"{t // 60:02d}:{t % 60:02d}"


def _avg(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return round(statistics.fmean(vals), 1) if vals else None


def _std(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return round(statistics.pstdev(vals), 1) if len(vals) >= 2 else (0.0 if vals else None)


def golden90_deep_min(inter: dict) -> int | None:
    """入眠（最初の非 awake ビン）から90分窓内の深睡眠量（分）を返す。

    timeline 先頭は bed_time（intermediate と同じ並び）。先頭から最初の
    非 awake ビンを睡眠オンセットとし、そこから GOLDEN_WINDOW_BINS 本の
    deep ビン数 × BIN_MINUTES を返す。timeline が無ければ None。
    """
    timeline = inter.get("timeline") or []
    if not timeline:
        return None

    onset = 0
    for i, r in enumerate(timeline):
        if r.get("stage") != "awake":
            onset = i
            break

    window = timeline[onset:onset + GOLDEN_WINDOW_BINS]
    deep_bins = sum(1 for r in window if r.get("stage") == "deep")
    return deep_bins * BIN_MINUTES


def build_weekly(inters: list[dict]) -> dict:
    """期間内の各夜 inter から週次集計 dict を作る。

    入力は日付昇順を想定（呼び出し側でソート）。features のネスト構造は
    database.flatten_features と同じキーで参照する。
    """
    nights = []
    for inter in inters:
        f = inter.get("features") or {}
        st = f.get("stages") or {}
        nights.append({
            "date": inter.get("date"),
            "score": f.get("sleep_score"),
            "deep_min": st.get("deep_min"),
            "light_min": st.get("light_min"),
            "rem_min": st.get("rem_min"),
            "awake_min": st.get("awake_min"),
            "golden90_deep_min": golden90_deep_min(inter),
            # 集計用の生値
            "_bed": f.get("bed_time"),
            "_wake": f.get("wake_time"),
            "_hrv": (f.get("hrv") or {}).get("avg_overnight"),
            "_hr_resting": (f.get("hr") or {}).get("resting"),
            "_spo2": (f.get("spo2") or {}).get("avg"),
            "_resp": (f.get("respiration") or {}).get("avg"),
            "_bb_change": (f.get("recovery") or {}).get("body_battery_change"),
            "_stress": (f.get("recovery") or {}).get("avg_stress"),
            "_awakenings": (f.get("awakenings") or {}).get("count"),
        })

    scores = [n["score"] for n in nights if n["score"] is not None]

    # 就寝は日跨ぎ補正（12:00以前は翌日扱いで +24h）して平均・ばらつきを安定させる
    bed_min = []
    for n in nights:
        m = _to_minutes(n["_bed"])
        if m is not None:
            bed_min.append(m + 24 * 60 if m < 12 * 60 else m)
    wake_min = [m for m in (_to_minutes(n["_wake"]) for n in nights) if m is not None]

    total_sleep = [
        sum(v for v in (n["deep_min"], n["light_min"], n["rem_min"]) if v is not None)
        for n in nights
        if any(v is not None for v in (n["deep_min"], n["light_min"], n["rem_min"]))
    ]

    weekly = {
        "start_date": nights[0]["date"] if nights else None,
        "end_date": nights[-1]["date"] if nights else None,
        "days": len(nights),
        "score": {
            "avg": _avg(scores),
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
            "std": _std(scores),
        },
        "stages": {
            "deep_min": _avg([n["deep_min"] for n in nights]),
            "light_min": _avg([n["light_min"] for n in nights]),
            "rem_min": _avg([n["rem_min"] for n in nights]),
            "awake_min": _avg([n["awake_min"] for n in nights]),
            "total_sleep_min": _avg(total_sleep),
        },
        "bed_time": {
            "avg": _minutes_to_hhmm(statistics.fmean(bed_min)) if bed_min else None,
            "std_min": _std(bed_min),
        },
        "wake_time": {
            "avg": _minutes_to_hhmm(statistics.fmean(wake_min)) if wake_min else None,
            "std_min": _std(wake_min),
        },
        "hrv_avg": _avg([n["_hrv"] for n in nights]),
        "hr_resting_avg": _avg([n["_hr_resting"] for n in nights]),
        "spo2_avg": _avg([n["_spo2"] for n in nights]),
        "resp_avg": _avg([n["_resp"] for n in nights]),
        "bb_change_avg": _avg([n["_bb_change"] for n in nights]),
        "stress_avg": _avg([n["_stress"] for n in nights]),
        "awakenings_avg": _avg([n["_awakenings"] for n in nights]),
        "golden90_deep_avg": _avg([n["golden90_deep_min"] for n in nights]),
        "nights": [
            {
                "date": n["date"],
                "score": n["score"],
                "deep_min": n["deep_min"],
                "rem_min": n["rem_min"],
                "golden90_deep_min": n["golden90_deep_min"],
            }
            for n in nights
        ],
    }
    return weekly
