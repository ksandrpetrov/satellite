"""Build a portable plugin archive for an actual HTTPS calendar endpoint."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .settings import normalize_base_url


def package_plugin(base_url: str, output_dir: Path) -> Path:
    base_url = normalize_base_url(base_url, allow_local=False)
    template = Path(__file__).resolve().parents[2] / "plugins" / "mail-calendar"
    if output_dir.exists():
        raise FileExistsError("Choose a new output directory for this plugin version")
    shutil.copytree(template, output_dir)
    (output_dir / "mcp.json").write_text(
        json.dumps(
            {
                "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
                "mcpServers": {
                    "mail-calendar": {
                        "type": "streamable-http",
                        "url": base_url.rstrip("/") + "/mcp",
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    archive = output_dir.with_suffix(".zip")
    with ZipFile(archive, "x", ZIP_DEFLATED) as bundle:
        for file in sorted(output_dir.rglob("*")):
            if file.is_file():
                bundle.write(file, file.relative_to(output_dir))
    return archive
