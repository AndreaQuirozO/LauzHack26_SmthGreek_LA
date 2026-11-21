import json
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


BASELINE_VERSION = "2024.8.30"
TARGET_VERSION = "2026.11.20"
WHEEL_DIRECTORY = Path("/opt/update/wheels")


def run_checked(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, check=True, capture_output=True, text=True)


def installed_certifi_version(python: Path) -> str:
    result = run_checked(
        [
            str(python),
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('certifi'))",
        ]
    )
    return result.stdout.strip()


def install_certifi(python: Path, version: str, upgrade: bool = False) -> None:
    arguments = [
        str(python),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--no-cache-dir",
        "--no-deps",
        "--find-links",
        str(WHEEL_DIRECTORY),
    ]
    if upgrade:
        arguments.append("--upgrade")
    arguments.append(f"certifi=={version}")
    run_checked(arguments)


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="certifi-update-", dir="/tmp") as directory:
            environment = Path(directory) / "venv"
            venv.EnvBuilder(with_pip=True, clear=True, symlinks=True).create(environment)
            python = environment / "bin" / "python"
            install_certifi(python, BASELINE_VERSION)
            if installed_certifi_version(python) != BASELINE_VERSION:
                raise RuntimeError("The demo baseline version was not installed as expected.")
            install_certifi(python, TARGET_VERSION, upgrade=True)
            verified_version = installed_certifi_version(python)
            if verified_version != TARGET_VERSION:
                raise RuntimeError("The demo target version could not be verified.")

        print(
            json.dumps(
                {
                    "package": "certifi",
                    "baseline": BASELINE_VERSION,
                    "target": TARGET_VERSION,
                    "verified_version": verified_version,
                }
            )
        )
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError):
        print("The offline certifi update or version verification failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())