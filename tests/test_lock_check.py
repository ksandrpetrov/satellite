"""Exercise the Make gate without network or modifying repository locks."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "failure", ["none", "compile-runtime", "compile-dev", "diff-runtime", "diff-dev"]
)
def test_lock_check_reports_every_failed_stage(tmp_path: Path, failure: str) -> None:
    (tmp_path / "Makefile").write_text((ROOT / "Makefile").read_text())
    for name in ("requirements.txt", "requirements-dev.txt"):
        (tmp_path / name).write_text("original\n")
    uv = tmp_path / "fake-uv"
    uv.write_text("""#!/usr/bin/env python3
import os
import sys
from pathlib import Path
if sys.argv[1:] == ["--version"]:
    print("uv 0.11.32")
    sys.exit(0)
kind = "dev" if sys.argv[3] == "requirements-dev.in" else "runtime"
failure = os.environ["LOCK_TEST_FAILURE"]
if failure == "compile-" + kind:
    sys.exit(17)
if failure == "diff-" + kind:
    Path(sys.argv[sys.argv.index("--output-file") + 1]).write_text("changed\\n")
""")
    uv.chmod(0o755)
    result = subprocess.run(
        ["make", "lock-check", f"UV={uv}"],
        cwd=tmp_path,
        env={**os.environ, "LOCK_TEST_FAILURE": failure},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (result.returncode == 0) == (failure == "none"), result.stdout + result.stderr
    assert (tmp_path / "requirements.txt").read_text() == "original\n"
    assert (tmp_path / "requirements-dev.txt").read_text() == "original\n"
