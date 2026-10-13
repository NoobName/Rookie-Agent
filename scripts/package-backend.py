import os
import site
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
# Conda's Python extensions require its matching OpenSSL, not a MinGW DLL
# with the same basename discovered later on PATH by PyInstaller hooks.
conda_bin = Path(sys.prefix) / "Library/bin"
if conda_bin.is_dir():
    os.environ["PATH"] = str(conda_bin) + os.pathsep + os.environ.get("PATH", "")
site.addsitedir(str(root / ".runtime/python"))
sys.path.insert(0, str(root / ".runtime/python"))
os.environ["PYTHONPATH"] = str(root / ".runtime/python") + os.pathsep + str(root)
sys.path.insert(0, str(root))
import PyInstaller.__main__

PyInstaller.__main__.run(
    [
        str(root / "scripts/run_backend.py"),
        "--name",
        "local-agent-backend",
        "--onedir",
        "--noconfirm",
        "--distpath",
        str(root / "dist/backend-build"),
        "--workpath",
        str(root / ".runtime/pyinstaller"),
        "--specpath",
        str(root / ".runtime"),
        "--paths",
        str(root),
        "--paths",
        str(root / ".runtime/python"),
        "--add-data",
        str(root / "services/agent/migration.sql") + ";services/agent",
        "--add-data",
        str(root / "examples/skills") + ";examples/skills",
        "--collect-all",
        "uvicorn",
        "--collect-all",
        "keyring",
        "--collect-all",
        "mcp",
        "--collect-all",
        "docx",
        "--collect-all",
        "openpyxl",
        "--collect-all",
        "pypdf",
        "--collect-all",
        "reportlab",
        "--collect-all",
        "playwright",
        "--collect-all",
        "tzdata",
        "--hidden-import",
        "pywinauto",
        "--hidden-import",
        "win32timezone",
    ]
)
if conda_bin.is_dir():
    import shutil

    for name in ("libssl-3-x64.dll", "libcrypto-3-x64.dll"):
        source = conda_bin / name
        if source.exists():
            shutil.copy2(source, root / "dist/backend-build/local-agent-backend/_internal" / name)
