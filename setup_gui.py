"""Garmin Sleep Reporter 設定＆実行 GUI（非技術者向け・単一ウィンドウ）。

ターミナルや .env 編集なしで、Garmin ログイン・分析エンジン・配信方法を設定し、
ログインテスト／分析テスト／今すぐ実行 までを行える。設定は settings.json に保存。

依存は標準ライブラリ(tkinter)のみ。`python setup_gui.py` で起動。
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog, ttk

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BACKEND_LABELS = [
    ("claude_cli", "Claude サブスク（claude-cli）"),
    ("ollama", "ローカル無料・データ非送信（ollama）★おすすめ"),
    ("gemini", "無料API（gemini）"),
    ("claude_api", "Claude API（従量課金）"),
]
DELIVERY_LABELS = [
    ("browser", "ブラウザで開く（おすすめ・Gmail不要）"),
    ("mail", "メールで送る（Gmail設定が必要）"),
    ("none", "保存のみ"),
]


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Garmin Sleep Reporter 設定")
        root.geometry("680x720")

        self.v = {
            "GARMIN_EMAIL": tk.StringVar(value=config.GARMIN_EMAIL or ""),
            "GARMIN_PASSWORD": tk.StringVar(value=config.GARMIN_PASSWORD or ""),
            "BACKEND": tk.StringVar(value=config.BACKEND or "claude_cli"),
            "GEMINI_API_KEY": tk.StringVar(value=config.GEMINI_API_KEY or ""),
            "GEMINI_MODEL": tk.StringVar(value=config.GEMINI_MODEL or "gemini-2.0-flash"),
            "OLLAMA_MODEL": tk.StringVar(value=config.OLLAMA_MODEL or "qwen2.5:7b"),
            "OLLAMA_HOST": tk.StringVar(value=config.OLLAMA_HOST or "http://localhost:11434"),
            "ANTHROPIC_API_KEY": tk.StringVar(value=config.ANTHROPIC_API_KEY or ""),
            "DELIVERY": tk.StringVar(value=config.effective_delivery()),
            "GMAIL_ADDRESS": tk.StringVar(value=config.GMAIL_ADDRESS or ""),
            "GMAIL_APP_PASSWORD": tk.StringVar(value=config.GMAIL_APP_PASSWORD or ""),
            "MAIL_TO": tk.StringVar(value=config.MAIL_TO or ""),
            "SCHEDULE_TIME": tk.StringVar(value=config.SCHEDULE_TIME or "08:00"),
            "NOTIFY_TOAST": tk.StringVar(value="1" if config.NOTIFY_TOAST else "0"),
        }

        self._build()
        self._toggle_backend()
        self._toggle_delivery()
        self._refresh_schedule_status()

    # ---- レイアウト ----
    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        # Garmin
        g = ttk.LabelFrame(main, text="1. Garmin Connect ログイン", padding=8)
        g.pack(fill="x", **pad)
        self._row(g, "メールアドレス", self.v["GARMIN_EMAIL"], 0)
        self._row(g, "パスワード", self.v["GARMIN_PASSWORD"], 1, secret=True)

        # 分析エンジン
        b = ttk.LabelFrame(main, text="2. 分析エンジン", padding=8)
        b.pack(fill="x", **pad)
        for i, (val, label) in enumerate(BACKEND_LABELS):
            ttk.Radiobutton(
                b, text=label, value=val, variable=self.v["BACKEND"],
                command=self._toggle_backend,
            ).grid(row=i, column=0, columnspan=2, sticky="w")
        self.backend_frames = {}
        gem = ttk.Frame(b)
        self._row(gem, "GEMINI_API_KEY", self.v["GEMINI_API_KEY"], 0, secret=True)
        self._row(gem, "モデル", self.v["GEMINI_MODEL"], 1)
        ttk.Label(gem, text="429/limit:0 なら gemini-2.5-flash を試すか ollama へ",
                  foreground="#888").grid(row=2, column=1, sticky="w")
        self.backend_frames["gemini"] = gem
        oll = ttk.Frame(b)
        self._row(oll, "モデル", self.v["OLLAMA_MODEL"], 0)
        self._row(oll, "ホスト", self.v["OLLAMA_HOST"], 1)
        ttk.Label(oll, text="要 Ollama 起動＋ ollama pull <モデル>（データはPC外に出ません）",
                  foreground="#888").grid(row=2, column=1, sticky="w")
        self.backend_frames["ollama"] = oll
        api = ttk.Frame(b)
        self._row(api, "ANTHROPIC_API_KEY", self.v["ANTHROPIC_API_KEY"], 0, secret=True)
        self.backend_frames["claude_api"] = api
        for fr in self.backend_frames.values():
            fr.grid(row=len(BACKEND_LABELS), column=0, columnspan=2, sticky="ew")
            fr.grid_remove()

        # 配信
        d = ttk.LabelFrame(main, text="3. レポートの受け取り方", padding=8)
        d.pack(fill="x", **pad)
        for i, (val, label) in enumerate(DELIVERY_LABELS):
            ttk.Radiobutton(
                d, text=label, value=val, variable=self.v["DELIVERY"],
                command=self._toggle_delivery,
            ).grid(row=i, column=0, columnspan=2, sticky="w")
        self.mail_frame = ttk.Frame(d)
        self._row(self.mail_frame, "Gmail アドレス", self.v["GMAIL_ADDRESS"], 0)
        self._row(self.mail_frame, "アプリパスワード", self.v["GMAIL_APP_PASSWORD"], 1, secret=True)
        self._row(self.mail_frame, "送信先(任意)", self.v["MAIL_TO"], 2)
        self.mail_frame.grid(row=len(DELIVERY_LABELS), column=0, columnspan=2, sticky="ew")
        self.mail_frame.grid_remove()

        # 毎朝の自動実行
        s = ttk.LabelFrame(main, text="4. 毎朝の自動実行（任意）", padding=8)
        s.pack(fill="x", **pad)
        ttk.Label(s, text="実行時刻 (HH:MM)", width=18).grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(s, textvariable=self.v["SCHEDULE_TIME"], width=10).grid(
            row=0, column=1, sticky="w", pady=2)
        ttk.Checkbutton(
            s, text="完了をデスクトップ通知（トースト）で知らせる",
            variable=self.v["NOTIFY_TOAST"], onvalue="1", offvalue="0",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=2)
        sbtns = ttk.Frame(s)
        sbtns.grid(row=2, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Button(sbtns, text="毎朝自動実行を登録", command=self.on_schedule_register).pack(side="left", padx=4)
        ttk.Button(sbtns, text="自動実行を解除", command=self.on_schedule_unregister).pack(side="left", padx=4)
        self.sched_status = ttk.Label(s, text="", foreground="#555")
        self.sched_status.grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Label(
            s,
            text="※ スリープ中も動かすには Windows の電源設定で"
                 "「スリープ解除タイマーの許可」を有効にしてください。",
            foreground="#888", wraplength=620, justify="left",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=2)

        # ボタン
        btns = ttk.Frame(main)
        btns.pack(fill="x", **pad)
        ttk.Button(btns, text="保存", command=self.on_save).pack(side="left", padx=4)
        ttk.Button(btns, text="ログインテスト", command=self.on_login_test).pack(side="left", padx=4)
        ttk.Button(btns, text="分析テスト", command=self.on_analysis_test).pack(side="left", padx=4)
        ttk.Button(btns, text="今すぐ実行", command=self.on_run_now).pack(side="left", padx=4)
        ttk.Button(btns, text="前回の結果を開く", command=self.on_open_latest).pack(side="left", padx=4)

        # ステータス＋ログ
        self.status = ttk.Label(main, text="設定を入力して『保存』してください。", foreground="#1a7f5a")
        self.status.pack(fill="x", **pad)
        self.log = scrolledtext.ScrolledText(main, height=12, font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, **pad)

        ttk.Label(
            main,
            text="※ 設定は settings.json に平文保存されます（このPC内）。",
            foreground="#888",
        ).pack(fill="x", **pad)

    def _row(self, parent, label, var, row, secret=False):
        ttk.Label(parent, text=label, width=18).grid(row=row, column=0, sticky="w", pady=2)
        e = ttk.Entry(parent, textvariable=var, width=46, show="*" if secret else "")
        e.grid(row=row, column=1, sticky="ew", pady=2)
        parent.columnconfigure(1, weight=1)

    # ---- 表示切替 ----
    def _toggle_backend(self) -> None:
        sel = self.v["BACKEND"].get()
        for name, fr in self.backend_frames.items():
            (fr.grid if name == sel else fr.grid_remove)()

    def _toggle_delivery(self) -> None:
        (self.mail_frame.grid if self.v["DELIVERY"].get() == "mail"
         else self.mail_frame.grid_remove)()

    # ---- ユーティリティ ----
    def _set_status(self, text: str, ok: bool = True) -> None:
        self.root.after(0, lambda: self.status.config(
            text=text, foreground="#1a7f5a" if ok else "#c0392b"))

    def _append_log(self, text: str) -> None:
        def _do():
            self.log.insert("end", text + "\n")
            self.log.see("end")
        self.root.after(0, _do)

    def _collect(self) -> dict:
        return {k: var.get().strip() for k, var in self.v.items()}

    def _save_settings(self) -> None:
        path = config.save_settings(self._collect())
        self._append_log(f"設定を保存: {path}")

    def _run_bg(self, fn) -> None:
        threading.Thread(target=fn, daemon=True).start()

    def _gui_mfa(self) -> str:
        """ワーカースレッドから安全にMFAダイアログを出す。"""
        holder: dict = {}
        ev = threading.Event()

        def ask():
            holder["code"] = simpledialog.askstring(
                "Garmin 2段階認証",
                "メール/SMSの認証コードを入力してください:",
                parent=self.root,
            ) or ""
            ev.set()

        self.root.after(0, ask)
        ev.wait()
        return holder["code"].strip()

    # ---- ボタン動作 ----
    def on_save(self) -> None:
        try:
            self._save_settings()
            self._set_status("保存しました。")
        except Exception as e:
            self._set_status(f"保存に失敗: {e}", ok=False)

    def on_login_test(self) -> None:
        self._set_status("ログインを試しています…")

        def work():
            try:
                self._save_settings()
                import garmin_client
                garmin_client.verify_login(mfa_provider=self._gui_mfa)
                self._set_status("ログイン成功（トークンを保存しました）。")
                self._append_log("Garmin ログイン: OK")
            except Exception as e:
                self._set_status("ログイン失敗", ok=False)
                self._append_log(f"Garmin ログイン失敗: {e}")
        self._run_bg(work)

    def on_analysis_test(self) -> None:
        self._set_status("分析エンジンに接続を試しています…")

        def work():
            try:
                self._save_settings()
                import backends
                out = backends.run(
                    "あなたはテスト応答器です。",
                    "『接続OK』とだけ短く返してください。",
                )
                self._set_status("分析エンジン: 接続OK")
                self._append_log(f"分析テスト応答: {out[:200]}")
            except Exception as e:
                self._set_status("分析エンジンの接続に失敗", ok=False)
                self._append_log(f"分析テスト失敗: {e}")
        self._run_bg(work)

    def on_run_now(self) -> None:
        self._set_status("レポートを生成中…（数十秒かかることがあります）")

        def work():
            try:
                self._save_settings()
                script = os.path.join(BASE_DIR, "detailed_report.py")
                proc = subprocess.Popen(
                    [sys.executable, script],
                    cwd=BASE_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                for line in proc.stdout:  # type: ignore[union-attr]
                    self._append_log(line.rstrip())
                proc.wait()
                if proc.returncode == 0:
                    self._set_status("レポート生成・配信が完了しました。")
                else:
                    self._set_status(f"実行が異常終了しました (code={proc.returncode})", ok=False)
            except Exception as e:
                self._set_status("実行に失敗", ok=False)
                self._append_log(f"実行失敗: {e}")
        self._run_bg(work)

    def on_open_latest(self) -> None:
        try:
            import notify
            path = notify.open_latest()
            if path:
                self._set_status(f"前回の結果を開きました: {os.path.basename(path)}")
            else:
                self._set_status("まだ結果がありません。『今すぐ実行』してください。", ok=False)
        except Exception as e:
            self._set_status(f"結果を開けませんでした: {e}", ok=False)

    def _refresh_schedule_status(self) -> None:
        def work():
            try:
                import scheduler
                text = scheduler.status_text()
            except Exception as e:  # noqa: BLE001
                text = f"自動実行: 状態取得に失敗 ({e})"
            self.root.after(0, lambda: self.sched_status.config(text=text))
        self._run_bg(work)

    def on_schedule_register(self) -> None:
        self._set_status("自動実行を登録しています…")

        def work():
            try:
                self._save_settings()
                import scheduler
                time_str = self.v["SCHEDULE_TIME"].get().strip() or "08:00"
                msg = scheduler.register(time_str)
                self._set_status(msg)
                self._append_log(msg)
            except Exception as e:
                self._set_status("自動実行の登録に失敗", ok=False)
                self._append_log(f"自動実行の登録失敗: {e}")
            finally:
                self._refresh_schedule_status()
        self._run_bg(work)

    def on_schedule_unregister(self) -> None:
        def work():
            try:
                import scheduler
                msg = scheduler.unregister()
                self._set_status(msg)
                self._append_log(msg)
            except Exception as e:
                self._set_status("自動実行の解除に失敗", ok=False)
                self._append_log(f"自動実行の解除失敗: {e}")
            finally:
                self._refresh_schedule_status()
        self._run_bg(work)


def main() -> int:
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
