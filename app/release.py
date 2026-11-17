"""
Build and publish Albion Ava Mapper.

    python app/release.py 1.0.1            build, commit, push, create GitHub release v1.0.1
    python app/release.py 1.0.1 --build    only build dist/Albion-Ava-Mapper-v1.0.1.zip (to test it)

First add a "## 1.0.1" section to CHANGELOG.md: it becomes the release notes. Then this:
1. sets APP_VERSION in app/server.py
2. builds the app folder with PyInstaller (folder build: single-file exes get flagged by antivirus far more)
3. adds the current zone data, so it works right away without the first download
4. zips it as Albion-Ava-Mapper-v1.0.1.zip (+ a .sha256 file)
5. commits, pushes and creates the GitHub release with the zip

Everyone running an older copy then sees "Update to v1.0.1" in the header.
Needs: pip install -r requirements.txt pyinstaller, and the GitHub CLI (gh) signed in once.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))     # app/
ROOT = os.path.dirname(HERE)                          # repository
SERVER = os.path.join(HERE, "server.py")
NAME = "Albion Ava Mapper"


def gh():
    return shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"


def run(*cmd, cwd=ROOT):
    print(">", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def notes_for(ver):
    text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    m = re.search(rf"^## {re.escape(ver)}\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else None


def build(ver):
    src = open(SERVER, encoding="utf-8").read()
    src, n = re.subn(r'^APP_VERSION = "[^"]*"', f'APP_VERSION = "{ver}"', src, flags=re.M)
    if n != 1:
        sys.exit("APP_VERSION line not found in app/server.py")
    with open(SERVER, "w", encoding="utf-8") as f:
        f.write(src)

    work = tempfile.mkdtemp(prefix="ava_build_")
    run(sys.executable, "make_icon.py", cwd=HERE)
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed", "--noupx",
        "--name", NAME, "--icon", os.path.join(HERE, "icon.ico"),
        "--add-data", f"{os.path.join(HERE, 'static')};static",
        "--collect-all", "winrt", "--hidden-import", "winocr", "--hidden-import", "pystray._win32",
        "--exclude-module", "cv2", "--exclude-module", "numpy",
        "--distpath", os.path.join(work, "dist"), "--workpath", os.path.join(work, "build"),
        "--specpath", work, "server.py", cwd=HERE)
    folder = os.path.join(work, "dist", NAME)

    # bundle the zone data, so the app works on the first start without downloading
    game = os.path.join(ROOT, "data", "game")
    if os.path.exists(os.path.join(game, "zones.json")):
        os.makedirs(os.path.join(folder, "data", "game"))
        for f in ("zones.json", "meta.json"):
            shutil.copyfile(os.path.join(game, f), os.path.join(folder, "data", "game", f))
    else:
        print("No data/game/zones.json: the release will download the zone data on first start")

    dist = os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    zpath = os.path.join(dist, f"Albion-Ava-Mapper-v{ver}.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for base, _, files in os.walk(folder):
            for f in files:
                p = os.path.join(base, f)
                z.write(p, os.path.join(NAME, os.path.relpath(p, folder)))
    digest = hashlib.sha256(open(zpath, "rb").read()).hexdigest()
    with open(zpath + ".sha256", "w") as f:
        f.write(f"{digest}  {os.path.basename(zpath)}\n")
    shutil.rmtree(work, ignore_errors=True)
    print(f"\nBuilt {zpath} ({os.path.getsize(zpath) / 1e6:.1f} MB)")
    return zpath


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1 or not re.fullmatch(r"\d+\.\d+\.\d+", args[0]):
        sys.exit(__doc__)
    ver = args[0]
    notes = notes_for(ver)
    if not notes:
        sys.exit(f'Add a "## {ver}" section to CHANGELOG.md first.')
    zpath = build(ver)
    if "--build" in sys.argv:
        return
    run("git", "add", "-A")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode:
        run("git", "commit", "-m", f"Release v{ver}\n\n{notes}")
    run("git", "push")
    run(gh(), "release", "create", f"v{ver}", zpath, zpath + ".sha256",
        "--title", f"{NAME} v{ver}", "--notes", notes)
    print(f"\nPublished v{ver}.")


if __name__ == "__main__":
    main()
