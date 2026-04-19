"""Config and version file loading."""

import json
from pathlib import Path


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_versions(config: dict, versions_dir: Path) -> dict:
    out: dict = {}
    for env in config["environments"]:
        p = versions_dir / f"{env['name']}.json"
        out[env["name"]] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return out
