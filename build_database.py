"""過去の睡眠履歴を中間表現に変換して SQLite に蓄積する（バックフィル）。

今日から1日ずつさかのぼり、各日の raw を取得 → 中間表現 → DB 格納。
LLM 分析は行わない。データ無しが一定日数連続したら停止する。

- ログインは1回だけ（garmin_client.get_client）。
- rawdata/ に raw を保存し、再実行時はキャッシュを使って API を叩かない。
- DBに既存の日付はスキップ（--force で再取得）。

使い方:
    python build_database.py                       # 自動検出でさかのぼり
    python build_database.py --since 2025-01-01    # 開始日を明示（そこで停止）
    python build_database.py --max-empty 30 --sleep 1.0
    python build_database.py --rebuild             # DBを作り直し
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time

import config
import database
import intermediate

RAW_DIR = os.path.join(config.base_dir(), "rawdata")

# 安全装置: これ以上は遡らない（今日からの最大日数）
HARD_FLOOR_DAYS = 3650


def _raw_path(date: str) -> str:
    return os.path.join(RAW_DIR, f"sleep_raw_{date}.json")


def _load_cached_raw(date: str):
    path = _raw_path(date)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_raw(date: str, raw: dict) -> None:
    os.makedirs(RAW_DIR, exist_ok=True)
    with open(_raw_path(date), "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)


def ingest_date(conn, date: str, *, client=None, use_cache: bool = True,
                sleep: float = 0.0):
    """指定日1日分を取得→中間表現→DB upsert する。

    raw は rawdata キャッシュ優先（use_cache=False で無視して必ずAPI取得）。
    戻り値は (inter, source, client)。
    - inter:  中間表現 dict（データ無し/未同期は None）
    - source: 'cache' | 'api' | None（取得元）
    - client: 遅延ログインで生成/再利用された Garmin クライアント（複数日で使い回す用）

    DB への upsert は inter が得られた場合のみ行う。
    """
    raw = _load_cached_raw(date) if use_cache else None
    source = "cache" if raw is not None else None
    if raw is None:
        if client is None:
            from garmin_client import get_client
            print("Garmin にログインします...")
            client = get_client()
        raw = client.get_sleep_data(date)
        source = "api"
        if raw:
            _save_raw(date, raw)
        if sleep:
            time.sleep(sleep)

    inter = intermediate.build_intermediate(raw) if raw else None
    if inter:
        database.upsert_night(conn, inter)
    return inter, source, client


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="睡眠履歴を中間表現でDB化する")
    p.add_argument("--since", help="開始日 YYYY-MM-DD（この日で停止）")
    p.add_argument("--max-empty", type=int, default=30,
                   help="データ無しがこの日数連続で停止（既定30）")
    p.add_argument("--sleep", type=float, default=1.0,
                   help="API取得ごとのスリープ秒（既定1.0、キャッシュ時は無し）")
    p.add_argument("--db", default=database.DEFAULT_DB, help="DBファイルパス")
    p.add_argument("--rebuild", action="store_true", help="DBを作り直す")
    p.add_argument("--force", action="store_true", help="既存日付も再取得して上書き")
    return p.parse_args(argv)


def run(args) -> int:
    conn = database.connect(args.db)
    if args.rebuild:
        database.drop_schema(conn)
        print("既存テーブルを削除しました（--rebuild）。")
    database.init_schema(conn)

    since = None
    if args.since:
        try:
            since = dt.date.fromisoformat(args.since)
        except ValueError:
            print(f"--since の形式が不正です: {args.since!r}")
            return 1

    today = dt.date.today()
    floor = since or (today - dt.timedelta(days=HARD_FLOOR_DAYS))

    print(f"バックフィル開始: {today} → {floor} 方向、max-empty={args.max_empty}")
    client = None  # 遅延ログイン（全てキャッシュ/DBならログイン不要）

    added = skipped = empty = 0
    empty_streak = 0
    date = today

    while date >= floor and empty_streak < args.max_empty:
        ds = date.isoformat()

        # 1) DBに既存ならスキップ（データありとみなす）
        if not args.force and database.has_date(conn, ds):
            skipped += 1
            empty_streak = 0
            date -= dt.timedelta(days=1)
            continue

        # 2) raw取得→中間表現→upsert（キャッシュ優先、無ければAPI）
        try:
            inter, source, client = ingest_date(
                conn, ds, client=client, sleep=args.sleep
            )
        except Exception as e:
            print(f"  {ds}: 取得エラー（スキップ）: {e}")
            date -= dt.timedelta(days=1)
            time.sleep(args.sleep)
            continue

        if not inter:
            empty += 1
            empty_streak += 1
            date -= dt.timedelta(days=1)
            continue

        added += 1
        empty_streak = 0
        score = (inter.get("features") or {}).get("sleep_score")
        print(f"  {ds}: 追加 (score={score}, {len(inter.get('timeline') or [])}行, {source})")
        date -= dt.timedelta(days=1)

    reason = "開始日に到達" if date < floor else f"データ無し{args.max_empty}日連続"
    print(f"\n停止理由: {reason}")
    print(f"結果: 追加 {added} / スキップ {skipped} / 空 {empty}")
    print("DB要約:", json.dumps(database.summary(conn), ensure_ascii=False))
    conn.close()
    return 0


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    sys.exit(main())
