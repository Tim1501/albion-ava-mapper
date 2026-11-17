# Albion Ava Mapper (c) 2026 ChanaMasala. All rights reserved. Free for personal use only.
# Copying, redistributing, reusing in other projects, or using with AI to train on, copy or rebuild
# this code needs written permission from the creator (Discord: @ChanaMasala). See LICENSE.
"""
Build and publish Albion Ava Mapper.

    python app/release.py 1.0.1            build, commit, push, create GitHub release v1.0.1
    python app/release.py 1.0.1 --build    only build dist/Albion-Ava-Mapper-v1.0.1.zip (to test it)

First add the version at the top of CHANGELOG in app/server.py (shown on the app's Overview page
under "What's new"; it also becomes the release notes). Then this:
1. sets APP_VERSION in app/server.py
2. builds the app folder with PyInstaller (folder build: single-file exes get flagged by antivirus far more)
3. adds the current zone data, so it works right away without the first download
4. adds "Read me.txt" and zips the one folder as Albion-Ava-Mapper-v1.0.1.zip (+ a .sha256 file)
5. commits, pushes and creates the GitHub release with the zip

Everyone running an older copy then sees "Update to v1.0.1" in the header.
Needs: pip install -r requirements.txt pyinstaller, and the GitHub CLI (gh) signed in once.
"""
import ast
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
    """Bullet list for this version from CHANGELOG in app/server.py."""
    for node in ast.parse(open(SERVER, encoding="utf-8").read()).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "CHANGELOG":
            for v, _date, items in ast.literal_eval(node.value):
                if v == ver:
                    return "\n".join(f"- {it}" for it in items)
    return None


READ_ME = r"""Albion Ava Mapper
=================

Start it: double-click "Albion Ava Mapper.exe" in this folder.
The first start also adds "Albion Ava Mapper" to your Start menu and your desktop.

Everything the app uses stays in this one folder:
  Albion Ava Mapper.exe   the app
  _internal\              the app's own files (don't change these)
  data\                   your settings, saved zones, zone data and logs

Move the whole folder anywhere you like (then use Data > Make shortcuts in the app to fix the shortcuts).
To remove the app, delete this folder and the two shortcuts.

Updating: download the new zip and extract it over this folder. Your data\ stays.

Something not working? In the app, open "Report a bug", make a report and send the zip to
@ChanaMasala on Discord.

Windows may warn that the app is from an unknown publisher (it's free and not code-signed):
click "More info" > "Run anyway". The source code is public: {repo}

(c) 2026 ChanaMasala. Free for personal use. Sharing copies, reusing the code, or using it with AI
to train on, copy or rebuild the app needs written permission. See LICENSE.txt.
"""


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

    shutil.copyfile(os.path.join(ROOT, "LICENSE"), os.path.join(folder, "LICENSE.txt"))
    with open(os.path.join(folder, "Read me.txt"), "w", encoding="utf-8") as f:
        f.write(READ_ME.format(repo="https://github.com/Tim1501/albion-ava-mapper"))

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
        sys.exit(f"Add a CHANGELOG entry for {ver} at the top of CHANGELOG in app/server.py first.")
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
