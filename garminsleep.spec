# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: app.py を1本の GUI exe（one-dir）に固める。

ビルド:
    pip install pyinstaller
    pyinstaller garminsleep.spec --noconfirm
出力:
    dist/GarminSleepReporter/GarminSleepReporter.exe （フォルダごと配布／Inno Setup で梱包）

方針:
- console=False（窓なしGUI）。無人実行(--run)は detailed_report が logs/task.log へ自動記録。
- garminconnect/garth/markdown/winotify は動的 import やデータ同梱が必要なため collect_all で取り込む。
- anthropic(claude_api) はサイズ削減のため除外（配布版は無料系 ollama/gemini/claude_cli が対象）。
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = []

# 動的 import / 付随データを持つパッケージをまとめて取り込む（未導入なら黙ってスキップ）。
for _pkg in ("garminconnect", "garth", "markdown", "winotify"):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass

# markdown の拡張（"extra" / "sane_lists"）はエントリポイント経由で読まれるため明示。
hiddenimports += collect_submodules("markdown.extensions")

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["anthropic"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GarminSleepReporter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GarminSleepReporter",
)
