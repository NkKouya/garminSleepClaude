"""Garmin Connect の睡眠データを「生レスポンス（rawdata）」のまま保存する。

garmin_client.get_sleep_summary() は raw を加工して一部だけ返すため、
全フィールドを確認したいときはこのスクリプトを使う。

使い方:
    python fetch_rawdata.py            # 今日分
    python fetch_rawdata.py 2026-06-14 # 日付指定（YYYY-MM-DD）
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

from garmin_client import get_sleep_raw

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE_DIR, "rawdata")


def main() -> int:
    date = sys.argv[1] if len(sys.argv) > 1 else dt.date.today().isoformat()

    # 形式チェック（不正なら ValueError で終了）
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        print(f"日付の形式が不正です: {date!r}（YYYY-MM-DD で指定してください）")
        return 1

    raw = get_sleep_raw(date)
    if not raw:
        print(f"{date} の睡眠データが取得できませんでした（未同期の可能性）。")
        return 0

    os.makedirs(RAW_DIR, exist_ok=True)
    out = os.path.join(RAW_DIR, f"sleep_raw_{date}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)

    print(f"保存: {out}")
    print("トップレベルキー:", list(raw.keys()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
