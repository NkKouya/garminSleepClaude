"""無料・手動モード: Garmin睡眠データを取得し、Claude Desktop 貼り付け用の
プロンプトを生成する。

API は使わない。生成したプロンプトを
  - ファイル保存（output/sleep_prompt_YYYY-MM-DD.txt）
  - クリップボードへコピー（Windows clip、best-effort）
  - コンソール表示
の3系統で出力する。あとは Claude Desktop に Ctrl+V するだけ。
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def _copy_to_clipboard(text: str) -> bool:
    """Windows の clip コマンドでクリップボードへコピー（成功で True）。"""
    try:
        # clip は UTF-16LE のテキストを受け取ると日本語が文字化けしない
        subprocess.run(
            ["clip"], input=text.encode("utf-16-le"), check=True, shell=True
        )
        return True
    except Exception:
        return False


def main() -> int:
    from garmin_client import get_sleep_summary
    from analyzer import build_prompt

    today = dt.date.today().isoformat()
    print(f"[{today}] Garmin から睡眠データを取得中...")

    summary = get_sleep_summary(today)
    if not summary:
        print(
            "睡眠データが取得できませんでした（未同期の可能性）。\n"
            "時計とGarmin Connectアプリの同期後に再実行してください。"
        )
        return 0

    score = summary.get("sleep_score")
    print(f"取得OK（睡眠スコア: {score}）")

    prompt = build_prompt(summary)

    # 1) ファイル保存
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"sleep_prompt_{today}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(prompt)

    # 2) クリップボードへコピー
    copied = _copy_to_clipboard(prompt)

    # 3) コンソール表示
    print("\n" + "=" * 60)
    print(prompt)
    print("=" * 60 + "\n")

    print(f"プロンプトをファイルに保存しました: {out_path}")
    if copied:
        print("クリップボードにコピーしました → Claude Desktop に Ctrl+V で貼り付けてください。")
    else:
        print(
            "クリップボードへのコピーに失敗しました。"
            "上記テキスト（またはファイル内容）を Claude Desktop に貼り付けてください。"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
