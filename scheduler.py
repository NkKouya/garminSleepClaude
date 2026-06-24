"""毎朝の自動実行（Windows タスクスケジューラ）の登録/解除。

`schtasks` を使い、現在ユーザーの対話トークンで毎日決まった時刻に
`detailed_report.py` を無人実行するタスクを登録する。管理者昇格(UAC)は不要。

README に書いていた手作業の設定（スリープ復帰=WakeToRun／未実行時の再実行=
StartWhenAvailable／バッテリーでも実行）を XML に埋め込んで自動化する。
ただし OS 側の「スリープ解除タイマーの許可」だけは電源ポリシーのため
schtasks では設定できない（GUI/README で案内する）。

CLI でも使える:
    python scheduler.py --register 08:00
    python scheduler.py --status
    python scheduler.py --unregister
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import tempfile

import config

TASK_NAME = "GarminSleepReporter"
# frozen 時は exe フォルダ、ソース時はリポジトリ（scheduler.py の場所と一致）。
BASE_DIR = config.base_dir()

# schtasks の出力は日本語環境で cp932。デコードに使う。
_CONSOLE_ENC = "cp932" if sys.platform == "win32" else "utf-8"


def _runner() -> tuple[str, str]:
    """タスクが実行する (program, arguments) を返す。

    - frozen(exe): 自身を `--run` で無人実行（Phase 4 で実体化）。
    - source: pythonw.exe（コンソール窓を出さない）で detailed_report.py を実行。
      出力は detailed_report 側で logs/task.log に記録する。
    """
    if getattr(sys, "frozen", False):
        return sys.executable, "--run"

    exe_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(exe_dir, "pythonw.exe")
    program = pythonw if os.path.exists(pythonw) else sys.executable
    script = os.path.join(BASE_DIR, "detailed_report.py")
    return program, f'"{script}" --log'


def _validate_time(time_str: str) -> str:
    """"HH:MM" を検証して正規化する。不正なら ValueError。"""
    t = dt.datetime.strptime(time_str.strip(), "%H:%M")
    return t.strftime("%H:%M")


def _build_xml(time_str: str) -> str:
    """タスクスケジューラ登録用の XML を組み立てる。"""
    hhmm = _validate_time(time_str)
    program, arguments = _runner()
    # StartBoundary の日付は任意（毎日トリガなので時刻のみ意味を持つ）。
    today = dt.date.today().isoformat()
    start = f"{today}T{hhmm}:00"
    now = dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>{now}</Date>
    <Description>Garmin Sleep Reporter: 毎朝の睡眠レポート自動生成</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{program}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{BASE_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _run_schtasks(args: list[str]) -> subprocess.CompletedProcess:
    """schtasks を実行して CompletedProcess を返す（出力は文字列デコード済み）。"""
    return subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
        encoding=_CONSOLE_ENC,
        errors="replace",
    )


def register(time_str: str = "08:00") -> str:
    """毎日 time_str に実行するタスクを登録（既存があれば置換）。戻り値は案内文。"""
    xml = _build_xml(time_str)
    # schtasks /XML は UTF-16(LE+BOM) の XML を期待する。
    fd, path = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-16") as f:
            f.write(xml)
        proc = _run_schtasks(["/Create", "/TN", TASK_NAME, "/XML", path, "/F"])
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        if "アクセスが拒否" in msg or "Access is denied" in msg:
            raise RuntimeError(
                "タスク登録が拒否されました。まれにこの操作だけ管理者権限が必要な"
                "環境があります。一度だけ管理者として実行してから再試行してください。"
                f"\n（詳細: {msg}）"
            )
        raise RuntimeError(f"タスク登録に失敗しました: {msg}")
    return f"毎朝 {_validate_time(time_str)} に自動実行を登録しました（{TASK_NAME}）。"


def unregister() -> str:
    """登録済みタスクを削除する。未登録なら何もしない。"""
    if not is_registered():
        return "自動実行は登録されていません。"
    proc = _run_schtasks(["/Delete", "/TN", TASK_NAME, "/F"])
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"タスク削除に失敗しました: {msg}")
    return "自動実行を解除しました。"


def is_registered() -> bool:
    """タスクが登録済みか。"""
    proc = _run_schtasks(["/Query", "/TN", TASK_NAME])
    return proc.returncode == 0


def next_run() -> str | None:
    """次回実行予定時刻の文字列を返す（取得できなければ None）。"""
    proc = _run_schtasks(["/Query", "/TN", TASK_NAME, "/FO", "LIST"])
    if proc.returncode != 0:
        return None
    for line in (proc.stdout or "").splitlines():
        # 日本語/英語どちらの環境でも拾えるようにキーで判定。
        if "次回" in line or "Next Run Time" in line:
            value = line.split(":", 1)[1].strip() if ":" in line else ""
            return value or None
    return None


def status_text() -> str:
    """GUI 表示用の状態文字列。"""
    if not is_registered():
        return "自動実行: 未登録"
    nxt = next_run()
    return f"自動実行: 登録済み（次回: {nxt}）" if nxt else "自動実行: 登録済み"


def main(argv: list[str]) -> int:
    if "--register" in argv:
        i = argv.index("--register")
        time_str = argv[i + 1] if i + 1 < len(argv) else "08:00"
        print(register(time_str))
    elif "--unregister" in argv:
        print(unregister())
    elif "--status" in argv:
        print(status_text())
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:  # noqa: BLE001 - CLI トップレベルで読みやすく表示
        print(f"エラー: {e}")
        sys.exit(2)
