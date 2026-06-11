"""Garmin Connect から睡眠データを取得する。

トークンキャッシュを優先し、無ければ email/password でログインして
トークンを保存する。初回はMFA（2段階認証コード）の入力が必要な場合がある。
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Optional

from garminconnect import Garmin

import config


def _login() -> Garmin:
    """トークン優先でログインし、Garmin クライアントを返す。"""
    # 1) トークンキャッシュから復元を試みる（無効/不在なら例外）
    try:
        garmin = Garmin()
        garmin.login(config.TOKEN_STORE)
        return garmin
    except Exception:
        # 2) email/password でログインへフォールバック
        pass

    garmin = Garmin(
        email=config.GARMIN_EMAIL,
        password=config.GARMIN_PASSWORD,
        return_on_mfa=True,
    )
    result1, result2 = garmin.login()

    # 3) MFA が必要な場合（初回手動実行時のみ想定）
    if result1 == "needs_mfa":
        mfa_code = input("Garmin の2段階認証コードを入力してください: ").strip()
        garmin.resume_login(result2, mfa_code)

    # 4) トークンを保存（return_on_mfa / resume_login 経路では自動保存されない）
    os.makedirs(config.TOKEN_STORE, exist_ok=True)
    garmin.client.dump(config.TOKEN_STORE)
    return garmin


def _sec_to_hm(seconds: Optional[int]) -> Optional[str]:
    if not seconds:
        return None
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h}時間{m}分"


def _epoch_ms_to_local(ms: Optional[int]) -> Optional[str]:
    if not ms:
        return None
    return dt.datetime.fromtimestamp(int(ms) / 1000).strftime("%H:%M")


def get_sleep_summary(date: Optional[str] = None) -> Optional[dict]:
    """指定日（既定は今日）の睡眠サマリを辞書で返す。データ無しは None。

    date: "YYYY-MM-DD"。「今朝起きた睡眠」は今日の日付で取得する。
    """
    if date is None:
        date = dt.date.today().isoformat()

    garmin = _login()
    raw = garmin.get_sleep_data(date)

    if not raw:
        return None

    dto = raw.get("dailySleepDTO") or {}

    # 総睡眠時間が取れない＝当日分が未同期/データ無しと判断
    total_sec = dto.get("sleepTimeSeconds")
    if not total_sec:
        return None

    scores = dto.get("sleepScores") or {}
    overall = scores.get("overall") or {}

    def _stage_score(key: str) -> Optional[int]:
        node = scores.get(key) or {}
        return node.get("value")

    summary = {
        "date": date,
        "sleep_score": overall.get("value"),
        "sleep_quality": overall.get("qualifierKey"),  # 例: GOOD / FAIR / POOR
        "total_sleep": _sec_to_hm(total_sec),
        "deep_sleep": _sec_to_hm(dto.get("deepSleepSeconds")),
        "light_sleep": _sec_to_hm(dto.get("lightSleepSeconds")),
        "rem_sleep": _sec_to_hm(dto.get("remSleepSeconds")),
        "awake": _sec_to_hm(dto.get("awakeSleepSeconds")),
        "bed_time": _epoch_ms_to_local(dto.get("sleepStartTimestampLocal")),
        "wake_time": _epoch_ms_to_local(dto.get("sleepEndTimestampLocal")),
        "resting_hr": raw.get("restingHeartRate") or dto.get("restingHeartRate"),
        "avg_hrv": raw.get("avgOvernightHrv") or dto.get("avgOvernightHrv"),
        "avg_respiration": dto.get("averageRespirationValue"),
        "avg_spo2": dto.get("averageSpO2Value"),
        "avg_stress": dto.get("avgSleepStress"),
        # スコア内訳（取れる場合）
        "score_duration": _stage_score("duration"),
        "score_deep": _stage_score("deepPercentage"),
        "score_rem": _stage_score("remPercentage"),
        "score_restlessness": _stage_score("restlessness"),
    }
    return summary


if __name__ == "__main__":
    import json

    s = get_sleep_summary()
    print(json.dumps(s, ensure_ascii=False, indent=2))
