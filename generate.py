#!/usr/bin/env python3
"""
ICE Infrastructure Version Dashboard — entry point.

Usage:
  python generate.py                   # live APIs; falls back to example data if tokens absent
  python generate.py --example         # example data only, no network calls or credentials needed
  python generate.py --dummy           # alias for --example (backwards-compatible)

Environment variables (only needed for live mode):
  GITLAB_TOKEN   GitLab personal access token with read_api scope
  JIRA_TOKEN     JIRA personal access token
  JIRA_USER      JIRA username / email address
"""

import sys
from pathlib import Path

from dashboard.loader import load_config, load_versions
from dashboard.gitlab_client import GitLabClient
from dashboard.jira_client import JiraClient
from dashboard.renderer import DashboardRenderer

BASE_DIR = Path(__file__).parent
EXAMPLE  = "--example" in sys.argv or "--dummy" in sys.argv


def main() -> None:
    print("Loading config...")
    config = load_config(BASE_DIR / "config.json")

    print("Loading versions...")
    versions = load_versions(config, BASE_DIR / "versions")

    print("Fetching CI status...")
    ci_data = GitLabClient(config, example=EXAMPLE).fetch_ci_status()

    print("Fetching JIRA bugs...")
    jira_data = JiraClient(config, example=EXAMPLE).fetch_bugs()

    print("Generating HTML...")
    html = DashboardRenderer(config, versions, ci_data, jira_data).render()

    out = BASE_DIR / "public" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"  {out} written ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
