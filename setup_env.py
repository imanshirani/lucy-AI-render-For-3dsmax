"""
Finds 3ds Max built-in Python 3.10, creates venv310, installs WebRTC deps.
Can be run standalone or from Max's Script Editor via python.ExecuteFile.
"""
import subprocess
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
VENV = ROOT / "venv310"

MAX_PYTHON_CANDIDATES = [
    r"C:\Program Files\Autodesk\3ds Max 2025\Python\python.exe",
    r"C:\Program Files\Autodesk\3ds Max 2026\Python\python.exe",
    r"C:\Program Files\Autodesk\3ds Max 2027\Python\python.exe",
]

PACKAGES = [
    "fal-client==0.14.1",
    "aiortc==1.15.0",
    "av==16.1.0",
    "Pillow==12.3.0",
]


def find_max_python():
    for path in MAX_PYTHON_CANDIDATES:
        if pathlib.Path(path).is_file():
            return path
    return None


def run(*cmd):
    print(">>", " ".join(str(c) for c in cmd))
    subprocess.run(list(cmd), check=True)


def main():
    py = find_max_python()
    if not py:
        print("ERROR: 3ds Max Python not found in default locations.")
        print("Checked: 2025 / 2026 / 2027")
        sys.exit(1)

    print(f"Using Max Python: {py}")

    if not VENV.exists():
        run(py, "-m", "venv", str(VENV))

    pip = VENV / "Scripts" / "pip.exe"
    run(str(pip), "install", "--upgrade", "pip", "--quiet")
    run(str(pip), "install", *PACKAGES)

    (VENV / ".lucy_live_ready").write_text("ok")
    print(f"\nDone!  venv at: {VENV}")


if __name__ == "__main__":
    main()
