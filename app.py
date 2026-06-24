"""Garmin Sleep Reporter の統合エントリポイント（PyInstaller でこの1本を固める）。

引数なし           → 設定GUI（setup_gui）を起動。
--run              → 無人実行（取得→分析→配信）。スケジュールタスクが呼ぶ。
--register [HH:MM] → 毎朝の自動実行を登録（既定 08:00）。
--unregister       → 自動実行を解除。
--status           → 自動実行の登録状態を表示。

frozen(exe) では scheduler が登録するタスクのコマンドが `<exe> --run` になる
（scheduler._runner 参照）。そのためこの分岐が無人実行の入口になる。
"""
from __future__ import annotations

import sys


def _run_unattended() -> int:
    """無人実行: 当日分の取得→分析→配信。

    --log は強制しない。窓なし実行（タスクスケジューラ）では stdout が None になり
    detailed_report 側が自動で logs/task.log へ転送する。GUIから stdout=PIPE で
    起動された場合は転送されず、親GUIが進捗を取得できる。
    """
    import detailed_report

    sys.argv = [sys.argv[0]]
    return detailed_report.main()


def _launch_gui() -> int:
    import setup_gui

    return setup_gui.main()


def main(argv: list[str]) -> int:
    if "--run" in argv:
        return _run_unattended()
    if "--register" in argv:
        import scheduler

        i = argv.index("--register")
        time_str = argv[i + 1] if i + 1 < len(argv) else "08:00"
        print(scheduler.register(time_str))
        return 0
    if "--unregister" in argv:
        import scheduler

        print(scheduler.unregister())
        return 0
    if "--status" in argv:
        import scheduler

        print(scheduler.status_text())
        return 0
    return _launch_gui()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
