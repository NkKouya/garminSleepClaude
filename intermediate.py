"""raw 睡眠データ（garminconnect の get_sleep_data 生レスポンス）を、
LLM に渡しやすい「中間表現」に圧縮する。

raw 全体は1晩で約169KB（約4〜5万トークン）あり、その大半は
SpO2 / movement のエポック単位センサー配列の冗長フィールド。
ここでは以下に圧縮する:
- features: Python で算出した特徴量（サイクル・覚醒・SpO2低下イベント・回復効率 等）
- timeline: 5分粒度に集約した時系列（stage/HR/HRV/SpO2/respiration/stress/BodyBattery）

時刻の扱い（raw 内に2系統あるため正規化する）:
- ISO文字列(GMT): sleepLevels.startGMT, SpO2 epochTimestamp 等
- epoch ms(GMT):  hrvData/sleepHeartRate/sleepStress/sleepBodyBattery/respiration 等
いずれも UTC epoch ms に正規化し、表示時にローカルオフセット（DTOのGMT/Local差）を足す。
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

# sleepLevels / sleepMovement の activityLevel → ステージ名
# （各合計秒が dailySleepDTO の deep/light/rem/awake と一致することを実データで確認済み）
_STAGE_BY_LEVEL = {0.0: "deep", 1.0: "light", 2.0: "rem", 3.0: "awake"}

BIN_MINUTES = 5
_BIN_MS = BIN_MINUTES * 60 * 1000


def _stage_name(activity_level: Optional[float]) -> Optional[str]:
    if activity_level is None:
        return None
    return _STAGE_BY_LEVEL.get(float(activity_level))


def _to_epoch_ms(value) -> Optional[int]:
    """ISO文字列(GMT) または epoch ms を UTC epoch ms(int) に正規化する。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    # 例: "2026-06-14T15:46:55.0"（GMT、タイムゾーン表記なし）
    s = str(value)
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    # naive を UTC とみなして epoch ms 化
    return int(d.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def _local_offset_ms(raw: dict) -> int:
    """dailySleepDTO の Local - GMT タイムスタンプ差からローカルオフセット(ms)を得る。"""
    dto = raw.get("dailySleepDTO") or {}
    g = dto.get("sleepStartTimestampGMT")
    l = dto.get("sleepStartTimestampLocal")
    if isinstance(g, (int, float)) and isinstance(l, (int, float)):
        return int(l) - int(g)
    return 0


def _fmt_local(epoch_ms: Optional[int], offset_ms: int) -> Optional[str]:
    """UTC epoch ms にローカルオフセットを足して "HH:MM" を返す。"""
    if epoch_ms is None:
        return None
    # offset を足した値を UTC として読むと、ローカルの壁時計時刻になる
    return dt.datetime.fromtimestamp(
        (epoch_ms + offset_ms) / 1000, dt.timezone.utc
    ).strftime("%H:%M")


def _sec_to_min(seconds: Optional[int]) -> Optional[int]:
    if not seconds:
        return None
    return round(int(seconds) / 60)


def _points(raw: dict, key: str, value_key: str = "value", time_key: str = "startGMT"):
    """[{time_key:..., value_key:...}, ...] を (epoch_ms, value) のリストに正規化する。"""
    out = []
    for p in raw.get(key) or []:
        t = _to_epoch_ms(p.get(time_key))
        v = p.get(value_key)
        if t is not None and v is not None:
            out.append((t, v))
    out.sort(key=lambda x: x[0])
    return out


def _spo2_points(raw: dict):
    """SpO2 epoch を (epoch_ms, spo2) に圧縮（冗長フィールドを捨てる）。"""
    out = []
    for p in raw.get("wellnessEpochSPO2DataDTOList") or []:
        t = _to_epoch_ms(p.get("epochTimestamp"))
        v = p.get("spo2Reading")
        if t is not None and v is not None:
            out.append((t, v))
    out.sort(key=lambda x: x[0])
    return out


def _avg(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 1)


def _build_stage_lookup(raw: dict):
    """sleepLevels を (start_ms, end_ms, stage) の区間リストにする。"""
    segs = []
    for s in raw.get("sleepLevels") or []:
        start = _to_epoch_ms(s.get("startGMT"))
        end = _to_epoch_ms(s.get("endGMT"))
        stage = _stage_name(s.get("activityLevel"))
        if start is not None and end is not None:
            segs.append((start, end, stage))
    segs.sort(key=lambda x: x[0])
    return segs


def _stage_at(segs, t_ms: int) -> Optional[str]:
    for start, end, stage in segs:
        if start <= t_ms < end:
            return stage
    return None


def _build_timeline(raw: dict, offset_ms: int):
    """5分グリッドの時系列を組む。各ビンは各信号の平均。"""
    dto = raw.get("dailySleepDTO") or {}
    start = dto.get("sleepStartTimestampGMT")
    end = dto.get("sleepEndTimestampGMT")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return []
    start, end = int(start), int(end)

    segs = _build_stage_lookup(raw)
    series = {
        "hr": _points(raw, "sleepHeartRate"),
        "hrv": _points(raw, "hrvData"),
        "spo2": _spo2_points(raw),
        "resp": _points(raw, "wellnessEpochRespirationDataDTOList",
                        value_key="respirationValue", time_key="startTimeGMT"),
        "stress": _points(raw, "sleepStress"),
        "bb": _points(raw, "sleepBodyBattery"),
    }

    rows = []
    bin_start = start
    while bin_start < end:
        bin_end = bin_start + _BIN_MS
        row = {
            "t": _fmt_local(bin_start, offset_ms),
            "stage": _stage_at(segs, bin_start + _BIN_MS // 2),
        }
        for name, pts in series.items():
            vals = [v for (t, v) in pts if bin_start <= t < bin_end]
            avg = _avg(vals)
            # 呼吸の負値（-2 等＝計測なし）は除外
            if name == "resp" and avg is not None and avg < 0:
                avg = None
            row[name] = avg
        rows.append(row)
        bin_start = bin_end
    return rows


def _spo2_desat_events(spo2_points, offset_ms: int, threshold: int = 90):
    """SpO2 が threshold% 未満になる連続区間をイベント化する。"""
    events = []
    cur = None  # {"start_ms","end_ms","min"}
    for t, v in spo2_points:
        if v < threshold:
            if cur is None:
                cur = {"start_ms": t, "end_ms": t, "min": v}
            else:
                cur["end_ms"] = t
                cur["min"] = min(cur["min"], v)
        else:
            if cur is not None:
                events.append(cur)
                cur = None
    if cur is not None:
        events.append(cur)

    total_min = 0
    lowest = None
    out = []
    for e in events:
        # 各エポックは約60秒。区間長は (end-start)+1エポック分とみなす
        dur_min = round(((e["end_ms"] - e["start_ms"]) / 1000 + 60) / 60)
        total_min += dur_min
        lowest = e["min"] if lowest is None else min(lowest, e["min"])
        out.append({"time": _fmt_local(e["start_ms"], offset_ms),
                    "min": e["min"], "duration_min": dur_min})
    return {"count": len(out), "total_min": total_min, "lowest": lowest, "events": out}


def _build_features(raw: dict, timeline, offset_ms: int) -> dict:
    dto = raw.get("dailySleepDTO") or {}
    scores = dto.get("sleepScores") or {}
    overall = scores.get("overall") or {}

    # stages
    segs = _build_stage_lookup(raw)
    rem_periods = 0
    prev = None
    for _, _, stage in segs:
        if stage == "rem" and prev != "rem":
            rem_periods += 1
        prev = stage
    awakenings = [
        _fmt_local(start, offset_ms)
        for (start, _end, stage) in segs
        if stage == "awake"
    ]

    # HR
    hr_pts = _points(raw, "sleepHeartRate")
    hr_onset = hr_pts[0][1] if hr_pts else None
    hr_nadir = hr_nadir_t = None
    for t, v in hr_pts:
        if hr_nadir is None or v < hr_nadir:
            hr_nadir, hr_nadir_t = v, t

    # HRV（前半 vs 後半でトレンド判定）
    hrv_pts = _points(raw, "hrvData")
    hrv_start = hrv_pts[0][1] if hrv_pts else None
    hrv_end = hrv_pts[-1][1] if hrv_pts else None
    hrv_trend = None
    if len(hrv_pts) >= 4:
        half = len(hrv_pts) // 2
        first = _avg([v for _, v in hrv_pts[:half]])
        second = _avg([v for _, v in hrv_pts[half:]])
        if first is not None and second is not None:
            diff = second - first
            hrv_trend = "up" if diff > 2 else "down" if diff < -2 else "flat"

    # SpO2
    spo2_pts = _spo2_points(raw)
    spo2_summary = raw.get("wellnessSpO2SleepSummaryDTO") or {}
    desat = _spo2_desat_events(spo2_pts, offset_ms)

    # respiration
    resp_avgs = raw.get("wellnessEpochRespirationAveragesList") or []
    resp_highs = [r.get("respirationHighValue") for r in resp_avgs if r.get("respirationHighValue")]
    resp_lows = [r.get("respirationLowValue") for r in resp_avgs if r.get("respirationLowValue")]
    breathing_disruptions = sum(
        1 for d in (raw.get("breathingDisruptionData") or []) if (d.get("value") or 0) > 0
    )

    # recovery
    bb_pts = _points(raw, "sleepBodyBattery")
    bb_start = bb_pts[0][1] if bb_pts else None
    bb_end = bb_pts[-1][1] if bb_pts else None
    bb_delta = (bb_end - bb_start) if (bb_start is not None and bb_end is not None) else None
    stress_pts = _points(raw, "sleepStress")

    return {
        "sleep_score": overall.get("value"),
        "sleep_quality": overall.get("qualifierKey"),
        "bed_time": _fmt_local(dto.get("sleepStartTimestampGMT"), offset_ms),
        "wake_time": _fmt_local(dto.get("sleepEndTimestampGMT"), offset_ms),
        "stages": {
            "deep_min": _sec_to_min(dto.get("deepSleepSeconds")),
            "light_min": _sec_to_min(dto.get("lightSleepSeconds")),
            "rem_min": _sec_to_min(dto.get("remSleepSeconds")),
            "awake_min": _sec_to_min(dto.get("awakeSleepSeconds")),
            "cycles": rem_periods,
        },
        "awakenings": {"count": len(awakenings), "times": awakenings},
        "hr": {
            "onset": hr_onset,
            "nadir": hr_nadir,
            "nadir_time": _fmt_local(hr_nadir_t, offset_ms),
            "resting": raw.get("restingHeartRate") or dto.get("restingHeartRate"),
        },
        "hrv": {
            "start": hrv_start,
            "end": hrv_end,
            "trend": hrv_trend,
            "avg_overnight": raw.get("avgOvernightHrv"),
            "status": (raw.get("hrvStatus") or {}).get("status")
            if isinstance(raw.get("hrvStatus"), dict) else raw.get("hrvStatus"),
        },
        "spo2": {
            "avg": spo2_summary.get("averageSPO2") or dto.get("averageSpO2Value"),
            "lowest": spo2_summary.get("lowestSPO2"),
            "desaturation": desat,
        },
        "respiration": {
            "avg": dto.get("averageRespirationValue"),
            "high": max(resp_highs) if resp_highs else None,
            "low": min(resp_lows) if resp_lows else None,
            "disruptions": breathing_disruptions,
        },
        "recovery": {
            "body_battery_start": bb_start,
            "body_battery_end": bb_end,
            "body_battery_change": bb_delta,
            "avg_stress": _avg([v for _, v in stress_pts]),
            "restless_moments": raw.get("restlessMomentsCount"),
        },
    }


def build_intermediate(raw: dict) -> Optional[dict]:
    """raw 睡眠データを中間表現 {date, features, timeline} に変換する。

    総睡眠時間が取れない（未同期/データ無し）場合は None。
    """
    if not raw:
        return None
    dto = raw.get("dailySleepDTO") or {}
    if not dto.get("sleepTimeSeconds"):
        return None

    offset_ms = _local_offset_ms(raw)
    timeline = _build_timeline(raw, offset_ms)
    features = _build_features(raw, timeline, offset_ms)

    date = None
    cal = dto.get("calendarDate")
    if cal:
        date = str(cal)
    return {"date": date, "features": features, "timeline": timeline}


if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else None
    if path:
        raw = json.load(open(path, encoding="utf-8"))
    else:
        from garmin_client import get_sleep_raw

        raw = get_sleep_raw()
    inter = build_intermediate(raw)
    print(json.dumps(inter, ensure_ascii=False, indent=2))
