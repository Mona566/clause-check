"""Build a Lambda zip with Linux wheels. A Mac install of pydantic will not run on Lambda."""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package(root: Path = ROOT) -> Path:
    build = root / "build"
    archive = root / "clause-check.zip"
    if build.exists():
        shutil.rmtree(build)
    build.mkdir()
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(root / "requirements-lambda.txt"),
            "-t",
            str(build),
            "--platform",
            "manylinux2014_x86_64",
            "--implementation",
            "cp",
            "--python-version",
            "3.12",
            "--only-binary=:all:",
            "--upgrade",
        ],
        cwd=root,
    )
    for name in ("app", "corpus"):
        shutil.copytree(
            root / name,
            build / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "api", "main.py"),
        )
    # ignore_patterns applies to names in every directory, so app/api is omitted.
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for path in build.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                zipped.write(path, path.relative_to(build).as_posix())
    return archive


if __name__ == "__main__":
    print(package())
