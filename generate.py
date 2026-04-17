#!/usr/bin/env python3
"""
ICE Infrastructure Version Dashboard Generator

Usage:
  python generate.py              # Use live APIs if tokens available, else dummy data
  python generate.py --dummy      # Force dummy data regardless of tokens

Environment variables:
  GITLAB_TOKEN   GitLab personal access token (needs read_api scope)
  JIRA_TOKEN     JIRA personal access token
  JIRA_USER      JIRA username / email address
"""

import json
import os
import re
import sys
import base64
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Any

BASE_DIR    = Path(__file__).parent
FORCE_DUMMY = "--dummy" in sys.argv


# ─── Loaders ─────────────────────────────────────────────────────────────────

def load_config() -> dict:
    return json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))


def load_versions(config: dict) -> dict:
    out: dict = {}
    for env in config["environments"]:
        p = BASE_DIR / "versions" / f"{env['name']}.json"
        out[env["name"]] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return out


# ─── HTTP helper ─────────────────────────────────────────────────────────────

def _get(url: str, headers: dict) -> Optional[Any]:
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} ← {url}")
    except Exception as e:
        print(f"  Error ← {url}: {e}")
    return None


# ─── CI Status Fetcher ────────────────────────────────────────────────────────

def fetch_ci_status(config: dict) -> dict:
    """Returns {item_key: {env_name: {passrate, pipeline_url}}}
    passrate is always read from ci_config (manually maintained in config.json).
    In live mode, pipeline_url is updated from the GitLab API.
    """
    # Base: passrate + fallback pipeline_url always come from config
    ci_cfg = config.get("ci_config", {})
    result: dict = {k: dict(v) for k, v in ci_cfg.items()}

    if FORCE_DUMMY or not os.environ.get("GITLAB_TOKEN"):
        if not FORCE_DUMMY:
            print("  GITLAB_TOKEN not set → using ci_config pipeline URLs")
        return result

    # Live mode: fetch live pipeline_url from GitLab, keep passrate from config
    token   = os.environ["GITLAB_TOKEN"]
    base    = config["gitlab_base_url"].rstrip("/")
    headers = {"PRIVATE-TOKEN": token}

    def _fetch_urls(project_id: Any, project_url: str, env_map: dict) -> dict:
        if not project_id or str(project_id) == "CONFIGURE_ME":
            return {}
        enc  = urllib.parse.quote(str(project_id), safe="")
        data = _get(f"{base}/api/v4/projects/{enc}/pipeline_schedules", headers)
        if not data:
            return {}
        out: dict = {}
        for sched in data:
            env_name = env_map.get(sched.get("description", ""))
            if not env_name:
                continue
            lp = sched.get("last_pipeline") or {}
            out[env_name] = lp.get("web_url", project_url + "/-/pipelines")
        return out

    for product in config["products"]:
        key  = product["key"]
        urls = _fetch_urls(
            product.get("ci_project_id"),
            product.get("ci_project_url", ""),
            product.get("pipeline_env_mapping", {}),
        )
        for env_name, url in urls.items():
            if key in result and env_name in result[key]:
                result[key][env_name]["pipeline_url"] = url
        for tpl in product.get("templates", []):
            tkey  = tpl["key"]
            turls = _fetch_urls(
                tpl.get("ci_project_id"),
                tpl.get("ci_project_url", ""),
                tpl.get("pipeline_env_mapping", {}),
            )
            for env_name, url in turls.items():
                if tkey in result and env_name in result[tkey]:
                    result[tkey][env_name]["pipeline_url"] = url

    return result


# ─── JIRA Bug Fetcher ────────────────────────────────────────────────────────

def fetch_jira_bugs(config: dict) -> dict:
    """Returns {product_key: [{key, summary, status, assignee, url}]}"""

    if FORCE_DUMMY or not (os.environ.get("JIRA_TOKEN") and os.environ.get("JIRA_USER")):
        if not FORCE_DUMMY:
            print("  JIRA_TOKEN/JIRA_USER not set → using dummy JIRA data")
        return config.get("dummy_jira_bugs", {})

    user    = os.environ["JIRA_USER"]
    token   = os.environ["JIRA_TOKEN"]
    base    = config["jira_base_url"].rstrip("/")
    creds   = base64.b64encode(f"{user}:{token}".encode()).decode()
    headers = {"Authorization": f"Basic {creds}", "Accept": "application/json"}
    result: dict = {}

    for product in config["products"]:
        key          = product["key"]
        jira_project = product.get("jira_project", "")
        if not jira_project or jira_project == "CONFIGURE_ME":
            result[key] = []
            continue

        print(f"  JIRA: {key} ({jira_project})")
        jql = (
            f'project = "{jira_project}" AND issuetype = Bug '
            f'AND summary ~ "[QA]:" AND status NOT IN '
            f'(Closed, Done, Cancelled, Resolved)'
        )
        url  = (
            f"{base}/rest/api/2/search"
            f"?jql={urllib.parse.quote(jql)}&maxResults=50&fields=summary,status,assignee"
        )
        data = _get(url, headers)
        if not data:
            result[key] = []
            continue

        tickets = []
        for issue in data.get("issues", []):
            f        = issue.get("fields", {})
            assignee = (f.get("assignee") or {}).get("displayName", "Unassigned")
            tickets.append({
                "key":      issue["key"],
                "summary":  f.get("summary", ""),
                "status":   f.get("status", {}).get("name", "Unknown"),
                "assignee": assignee,
                "url":      f"{base}/browse/{issue['key']}",
            })
        result[key] = tickets

    return result


# ─── Semver drift helpers ─────────────────────────────────────────────────────

def _extract_semver(v: str) -> tuple:
    """
    Extract the most significant dot-separated numeric triplet from a version
    string.  Handles plain semver ('1.7.6') and composite strings ('2.2-1.60.3').
    Returns a tuple of ints, e.g. (1, 60, 3), or () if unparseable.
    """
    if not v or v in ("ERROR", ""):
        return ()
    candidates = re.findall(r'\d+(?:\.\d+)+', v)
    if not candidates:
        return ()
    # Prefer the candidate with the most parts (most informative)
    best = max(candidates, key=lambda s: len(s.split(".")))
    return tuple(int(p) for p in best.split("."))


def semver_drift(current: str, previous: str) -> int:
    """
    Compare two version strings (right env vs left env).
    Returns drift level when current < previous (right env is behind):
      0 = same or unparseable
      1 = patch-level drift   →  ↓
      2 = minor-level drift   →  ↓↓
      3 = major-level drift   →  ↓↓↓
    Returns 0 (no indicator) when current >= previous.
    """
    cur = _extract_semver(current)
    prv = _extract_semver(previous)
    if not cur or not prv or cur >= prv:
        return 0
    # Pad to equal length with zeros
    n = max(len(cur), len(prv))
    cur += (0,) * (n - len(cur))
    prv += (0,) * (n - len(prv))
    for i, (c, p) in enumerate(zip(cur, prv)):
        if c != p:
            return 3 if i == 0 else (2 if i == 1 else 1)
    return 0


def _raw_version_str(version_data) -> str:
    """Extract plain version string from a version JSON value."""
    if isinstance(version_data, dict):
        v = version_data.get("version", "")
    else:
        v = str(version_data) if version_data else ""
    return "" if v == "ERROR" else v


# ─── HTML helpers ─────────────────────────────────────────────────────────────

def esc(s: Any) -> str:
    return (str(s)
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;")
            .replace("'", "&#39;"))


def passrate_badge(env_name: str, item_ci: dict) -> str:
    """Render a coloured pill showing the CI passrate % (0-100) from ci_config.
    passrate can be an int (0-100) or the string '-' meaning no CI for this env."""
    info = item_ci.get(env_name) if item_ci else None
    if not info or "passrate" not in info:
        return ""
    raw = info["passrate"]
    url = info.get("pipeline_url", "")
    if str(raw) == "-":
        return '<span class="pr-badge pr-none" title="CI not configured for this environment">-</span>'
    pct = int(raw)
    cls = "pr-green" if pct >= 90 else ("pr-yellow" if pct >= 61 else "pr-red")
    tip = f"CI passrate: {pct}%"
    if url:
        return (f'<a href="{esc(url)}" class="pr-badge {cls}" '
                f'title="{esc(tip)}" target="_blank">{pct}</a>')
    return f'<span class="pr-badge {cls}" title="{esc(tip)}">{pct}</span>'


def bug_badge(tickets: list, product_name: str) -> str:
    n       = len(tickets)
    cls     = "bug-zero" if n == 0 else "bug-nonzero"
    bugs_js = esc(json.dumps(tickets))
    title   = "No open QA bugs" if n == 0 else f"{n} open QA bug(s) — hover for details"
    return (
        f'<span class="bug-badge {cls}" data-bugs="{bugs_js}" '
        f'data-product="{esc(product_name)}" title="{title}">'
        f'{n}</span>'
    )


def version_cell(
    env_name: str, item_key: str, versions: dict,
    ci_status: dict, show_ci: bool = True, drift: int = 0,
) -> str:
    raw = versions.get(env_name, {}).get(item_key, "")

    if isinstance(raw, dict):
        version = raw.get("version", "")
        url     = raw.get("url")
        extras  = raw.get("additional_urls", [])
    else:
        version = str(raw) if raw else ""
        url     = None
        extras  = []

    if version == "ERROR":
        version = ""

    # Drift indicator: red down-arrows, 1–3 based on semver severity
    drift_titles = ["", "patch version behind", "minor version behind", "major version behind"]
    drift_html = (
        f'<span class="drift drift-{drift}" title="{drift_titles[drift]}">{"↓" * drift}</span>'
        if drift > 0 else ""
    )

    if version:
        if url:
            ver_html = (f'<a href="{esc(url)}" class="version-link" '
                        f'target="_blank">{esc(version)}</a>{drift_html}')
        else:
            ver_html = f'<span class="version-text">{esc(version)}</span>{drift_html}'
    else:
        ver_html = '<span class="version-empty">—</span>'

    links_html = "".join(
        f'<a href="{esc(a["url"])}" class="sub-link" target="_blank">{esc(a["name"])}</a>'
        for a in extras
    )

    item_ci = ci_status.get(item_key, {}) if show_ci else {}
    if show_ci and not version:
        # No version deployed → passrate is meaningless, force gray '-'
        ci_html = '<span class="pr-badge pr-none" title="No version deployed">-</span>'
    else:
        ci_html = passrate_badge(env_name, item_ci)

    return (
        f'<td class="vc">'
        f'<div class="cell-v">{ver_html}</div>'
        + (f'<div class="cell-links">{links_html}</div>' if links_html else "")
        + f'<div class="cell-meta">{ci_html}</div>'
        f'</td>'
    )


# ─── CSS ─────────────────────────────────────────────────────────────────────

CSS = """
:root {
  --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --bg: #f1f5f9;
  --surface: #fff;
  --border: #e2e8f0;
  --text: #0f172a;
  --muted: #64748b;
  --bar-h: 52px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: var(--font); font-size: 13px; background: var(--bg); color: var(--text); }

/* ── top bar ── */
.bar {
  position: sticky; top: 0; z-index: 200;
  height: var(--bar-h);
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
  display: flex; align-items: center; gap: 14px;
  padding: 0 20px;
  box-shadow: 0 2px 16px rgba(0,0,0,.4);
}
.bar-title { font-size: 15px; font-weight: 700; color: #f8fafc; letter-spacing: .02em; flex: 1; }
.bar-tag {
  font-size: 10px; font-weight: 700; background: #1e3a5f;
  color: #60a5fa; padding: 3px 9px; border-radius: 4px;
  letter-spacing: .08em; text-transform: uppercase;
}
.bar-ts { font-size: 11px; color: #475569; white-space: nowrap; }
.bar-legend { display: flex; align-items: center; gap: 10px; margin-left: 12px; }
.leg { display: flex; align-items: center; gap: 4px; font-size: 10px; color: #64748b; }

/* ── table wrapper — this IS the scroll container for the table ── */
.wrap {
  overflow-x: auto;
  overflow-y: auto;
  height: calc(100vh - var(--bar-h));  /* fill remaining viewport below the top bar */
}
table { border-collapse: collapse; width: max-content; min-width: 100%; background: var(--surface); }

/* ── group-header row ── */
.gh { height: 26px; }
.gh th {
  /* top: 0 — relative to .wrap, which is now the scroll container */
  position: sticky; top: 0; z-index: 90;
  padding: 0 8px; text-align: center;
  font-size: 9px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase;
  color: rgba(255,255,255,.65); white-space: nowrap;
}
.gh .lbl  { background: #1e293b; color: #334155; }
.gh .g-it { background: #1e3a8a; }
.gh .g-ve { background: #3730a3; }
.gh .g-ad { background: #0e7490; }
.gh .g-pr { background: #92400e; }

/* ── env-header row ── */
.eh th {
  /* top: 26px — exactly the height of .gh, relative to .wrap */
  position: sticky; top: 26px; z-index: 89;
  padding: 6px 8px; text-align: center;
  font-size: 11px; font-weight: 600; color: #e2e8f0;
  border-right: 1px solid rgba(255,255,255,.07);
  border-bottom: 3px solid #475569;  /* clear separator; reliable now that .wrap scrolls */
  width: 1px;           /* shrink to content; table-layout:auto does the rest */
  white-space: nowrap;
}
.eh .lbl { background: #1e293b; text-align: left !important; color: #64748b; font-size: 10px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; white-space: nowrap; }
.eh .e-it { background: #1e3a8a; border-top: 2px solid #60a5fa; }
.eh .e-ve { background: #312e81; border-top: 2px solid #818cf8; }
.eh .e-ad { background: #155e75; border-top: 2px solid #22d3ee; }
.eh .e-pr { background: #78350f; border-top: 2px solid #fbbf24; }
.env-name { display: block; }
.env-url  { display: block; font-size: 9px; font-weight: 400; color: rgba(255,255,255,.4); margin-top: 2px; white-space: nowrap; }

/* sticky first two cols in header — outer frame only, no divider between them */
.gh .sl1, .eh .sl1 {
  position: sticky !important; left: 0; z-index: 95 !important;
  background: #1e293b !important;
  border-left:  2px solid #0f172a !important;
  border-right: none !important;
}
.gh .sl2, .eh .sl2 {
  position: sticky !important; left: 0; z-index: 95 !important;  /* left set by JS */
  background: #1e293b !important;
  border-right: none !important;
  /* box-shadow travels with the sticky element, acting as a fixed right border */
  box-shadow: 3px 0 0 0 #0f172a;
}

/* ── tbody rows ── */
tbody tr { border-bottom: 1px solid var(--border); }
tbody tr:hover td { background: #f0f9ff !important; }

/* sticky label cells — outer frame only, no divider between them */
td.lp, td.lt {
  position: sticky; z-index: 10;
  background: #f4f6f8; padding: 8px 10px; vertical-align: top;
}
td.lp {
  left: 0; width: 1px;
  border-left:  2px solid #0f172a;
  border-right: none;
}
td.lt {
  left: 0; width: 1px;  /* left set by JS */
  border-left:  none;
  border-right: none;
  /* box-shadow travels with the sticky element — visible right border when scrolling */
  box-shadow: 3px 0 0 0 #0f172a;
}

/* product row */
tr.pr { background: #fff; }
tr.pr td.lp { border-left: 3px solid #3b82f6; }
.pname { font-weight: 700; color: #0f172a; font-size: 13px; line-height: 1.3; overflow-wrap: break-word; word-break: break-word; }
.phead { display: flex; align-items: flex-start; justify-content: space-between; gap: 6px; margin-bottom: 3px; }
.plinks { display: flex; flex-direction: column; gap: 1px; margin-top: 2px; }
.plink  { font-size: 10px; color: #64748b; text-decoration: none; overflow-wrap: break-word; word-break: break-word; }
.plink:hover { color: #2563eb; }
.jira-lnk { font-size: 10px; color: #0052cc; text-decoration: none; margin-top: 3px; display: inline-block; }
.jira-lnk:hover { text-decoration: underline; }

/* template row */
tr.tr { background: #f8fafc; }
tr.tr td.lt { padding-left: 16px; color: #475569; font-size: 11px; }
.tname { display: block; color: #475569; font-size: 11px; overflow-wrap: break-word; word-break: break-all; }

/* update row — last row of the table */
tr.ur { background: #f8fafc; border-top: 2px solid var(--border); }
tr.ur td { font-size: 11px; color: var(--muted); padding: 6px 10px; font-style: italic; }
td.ur-label { padding: 6px 10px; font-size: 11px; color: var(--muted); font-style: italic; font-weight: 600; }

/* ── version cells ── */
td.vc { padding: 7px 8px; vertical-align: top; border-right: 1px solid var(--border); white-space: nowrap; width: 1px; background: #fff; }

.cell-v { margin-bottom: 2px; }
.version-link  { font-weight: 700; color: #0000EE; text-decoration: none; font-size: 15px; }
.version-link:hover { text-decoration: underline; }
.version-text  { font-weight: 500; color: #334155; }
.version-empty { color: #cbd5e1; user-select: none; }

/* drift indicators — red down-arrows, severity by count */
.drift   { font-size: 11px; font-weight: 800; margin-left: 3px;
           vertical-align: middle; letter-spacing: -2px; line-height: 1; }
.drift-1 { color: #f87171; }   /* patch  — light red */
.drift-2 { color: #dc2626; }   /* minor  — red */
.drift-3 { color: #7f1d1d; }   /* major  — dark red */

.cell-links { display: flex; flex-direction: column; gap: 2px; margin-bottom: 3px; }
.sub-link {
  font-size: 10px; color: #0000EE; text-decoration: none;
  white-space: nowrap;
}
.sub-link:hover { text-decoration: underline; }

.cell-meta { display: flex; align-items: center; gap: 5px; margin-top: 5px; }

/* ── CI passrate badges ── */
.pr-badge {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 26px; height: 18px; border-radius: 9px;
  font-size: 10px; font-weight: 700; color: #fff; line-height: 1;
  padding: 0 4px; text-decoration: none; flex-shrink: 0;
  transition: transform .12s, opacity .12s;
}
a.pr-badge { cursor: pointer; }
a.pr-badge:hover { opacity: .8; transform: scale(1.1); }
.pr-green  { background: #16a34a; }   /* 90-100          */
.pr-yellow { background: #d97706; }   /* 61-89           */
.pr-red    { background: #dc2626; }   /* 0-60            */
.pr-none   { background: #94a3b8; color: #fff; }   /* not configured  */

/* ── Bug badges ── */
.bug-badge {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 20px; height: 18px; border-radius: 9px;
  font-size: 11px; font-weight: 700; color: #fff;
  padding: 0 5px; cursor: pointer; user-select: none;
  transition: transform .12s, opacity .12s;
  flex-shrink: 0;
}
.bug-badge:hover { opacity: .85; transform: scale(1.1); }
.bug-zero    { background: #94a3b8; }   /* gray — no open bugs */
.bug-nonzero { background: #0f172a; }   /* black — bugs present */

/* ── Bug popup ── */
#bug-popup {
  display: none; position: fixed; z-index: 9999;
  background: #1e293b; color: #e2e8f0;
  border-radius: 10px; padding: 14px 16px;
  box-shadow: 0 16px 48px rgba(0,0,0,.55), 0 0 0 1px rgba(255,255,255,.06);
  min-width: 500px; max-width: 680px;
  max-height: 440px; overflow-y: auto;
}
#bug-popup::-webkit-scrollbar { width: 5px; }
#bug-popup::-webkit-scrollbar-track { background: #0f172a; }
#bug-popup::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
#bug-popup h4 {
  font-size: 11px; font-weight: 700; color: #64748b;
  text-transform: uppercase; letter-spacing: .09em;
  margin-bottom: 10px; padding-bottom: 8px;
  border-bottom: 1px solid #334155;
}
.bp-header {
  display: grid; grid-template-columns: 95px 1fr 95px 140px;
  gap: 8px; font-size: 9px; font-weight: 700; color: #334155;
  text-transform: uppercase; letter-spacing: .07em;
  margin-bottom: 6px; padding-bottom: 4px;
}
.bt {
  display: grid; grid-template-columns: 95px 1fr 95px 140px;
  gap: 8px; padding: 6px 0; border-top: 1px solid #1e3a5f20;
  align-items: start;
}
.bt:first-of-type { border-top-color: #334155; }
.bt-key a  { color: #60a5fa; text-decoration: none; font-weight: 700; font-size: 11px; }
.bt-key a:hover { text-decoration: underline; color: #93c5fd; }
.bt-sum    { color: #cbd5e1; font-size: 11px; line-height: 1.4;
             overflow: hidden; display: -webkit-box;
             -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.bt-sta    { text-align: center; }
.s-pill    { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 10px; font-weight: 600; }
.s-open     { background: #0f172a; color: #64748b; border: 1px solid #334155; }
.s-progress { background: #1e3a8a; color: #93c5fd; }
.s-review   { background: #312e81; color: #a5b4fc; }
.bt-asgn   { color: #64748b; font-size: 10px; line-height: 1.4; }
"""


# ─── JavaScript ───────────────────────────────────────────────────────────────

JS = r"""
(function () {
  'use strict';

  /* ── Fix left offset of second sticky column after layout ── */
  function fixStickyCol2() {
    var firstCell = document.querySelector('td.lp, th.sl1');
    if (!firstCell) return;
    var w = firstCell.offsetWidth + 'px';
    document.querySelectorAll('td.lt, th.sl2').forEach(function (el) {
      el.style.left = w;
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', fixStickyCol2);
  } else {
    fixStickyCol2();
  }

  var popup = document.getElementById('bug-popup');
  var hideTimer;

  function htmlEsc(s) {
    return String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function showPopup(badge) {
    clearTimeout(hideTimer);
    var bugs    = JSON.parse(badge.dataset.bugs);
    var product = badge.dataset.product || '';

    var h = '<h4>' + htmlEsc(product) + ' &mdash; Open QA Bugs (' + bugs.length + ')</h4>';
    h += '<div class="bp-header"><span>Ticket</span><span>Summary</span><span>Status</span><span>Assignee</span></div>';

    bugs.forEach(function (b) {
      var scls = /progress/i.test(b.status) ? 's-progress'
               : /review/i.test(b.status)   ? 's-review'
               : 's-open';
      h += '<div class="bt">'
         + '<div class="bt-key"><a href="' + htmlEsc(b.url) + '" target="_blank">' + htmlEsc(b.key) + '</a></div>'
         + '<div class="bt-sum">' + htmlEsc(b.summary) + '</div>'
         + '<div class="bt-sta"><span class="s-pill ' + scls + '">' + htmlEsc(b.status) + '</span></div>'
         + '<div class="bt-asgn">' + htmlEsc(b.assignee) + '</div>'
         + '</div>';
    });

    popup.innerHTML = h;

    /* smart positioning: try right of badge, fall back to left */
    var W  = 580, H = Math.min(440, 90 + bugs.length * 46);
    var rc = badge.getBoundingClientRect();
    var left = rc.right + 12;
    var top  = rc.top - 4;

    if (left + W > window.innerWidth  - 8) { left = rc.left - W - 12; }
    if (top  + H > window.innerHeight - 8) { top  = window.innerHeight - H - 8; }
    if (left < 8) left = 8;
    if (top  < 52) top = 52;   /* don't overlap top bar */

    popup.style.left    = left + 'px';
    popup.style.top     = top  + 'px';
    popup.style.display = 'block';
  }

  function hidePopup() {
    hideTimer = setTimeout(function () { popup.style.display = 'none'; }, 160);
  }

  document.querySelectorAll('.bug-badge.bug-nonzero').forEach(function (b) {
    b.addEventListener('mouseenter', function () { showPopup(b); });
    b.addEventListener('mouseleave', hidePopup);
  });
  popup.addEventListener('mouseenter', function () { clearTimeout(hideTimer); });
  popup.addEventListener('mouseleave', hidePopup);
})();
"""


# ─── Page assembly ────────────────────────────────────────────────────────────

GROUP_CLASSES = {
    "infratest": ("g-it", "e-it"),
    "ve":        ("g-ve", "e-ve"),
    "appdev":    ("g-ad", "e-ad"),
    "prod":      ("g-pr", "e-pr"),
}


def generate_html(config: dict, versions: dict, ci_status: dict, jira_bugs: dict) -> str:
    envs      = config["environments"]
    products  = config["products"]
    jira_base = config.get("jira_base_url", "").rstrip("/")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Compute group column spans for the header
    groups: list[dict] = []
    for env in envs:
        g   = env.get("group", "infratest")
        lbl = env.get("group_label", g.upper())
        cls = GROUP_CLASSES.get(g, ("g-it", "e-it"))[0]
        if groups and groups[-1]["label"] == lbl:
            groups[-1]["span"] += 1
        else:
            groups.append({"label": lbl, "cls": cls, "span": 1})

    p: list[str] = []
    p.append('<!DOCTYPE html>')
    p.append('<html lang="en">')
    p.append('<head>')
    p.append('<meta charset="UTF-8">')
    p.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    p.append('<title>ICE Infrastructure Dashboard</title>')
    p.append(f'<style>{CSS}</style>')
    p.append('</head>')
    p.append('<body>')

    # ── Top bar ────────────────────────────────────────────────────────────
    p.append(
        f'<div class="bar">'
        f'<span class="bar-title">ICE Infrastructure Dashboard</span>'
        f'<div class="bar-legend">'
        f'<span class="leg"><span class="pr-badge pr-green" style="pointer-events:none">95</span> ≥90% pass</span>'
        f'<span class="leg"><span class="pr-badge pr-yellow" style="pointer-events:none">75</span> 61-89%</span>'
        f'<span class="leg"><span class="pr-badge pr-red" style="pointer-events:none">42</span> ≤60%</span>'
        f'<span class="leg"><span class="bug-badge bug-nonzero" style="pointer-events:none">3</span> QA bugs</span>'
        f'<span class="leg"><span class="bug-badge bug-zero" style="pointer-events:none">0</span> none</span>'
        f'</div>'
        f'<span class="bar-tag">EDP</span>'
        f'<span class="bar-ts">Generated {generated}</span>'
        f'</div>'
    )

    p.append('<div class="wrap"><table>')
    p.append('<thead>')

    # ── Group header row ───────────────────────────────────────────────────
    p.append('<tr class="gh">')
    p.append('<th class="lbl sl1"></th><th class="lbl sl2"></th>')
    for g in groups:
        p.append(f'<th class="{g["cls"]}" colspan="{g["span"]}">{esc(g["label"])}</th>')
    p.append('</tr>')

    # ── Env detail header row ──────────────────────────────────────────────
    p.append('<tr class="eh">')
    p.append('<th class="lbl sl1">Product</th>')
    p.append('<th class="lbl sl2">Workflow Template</th>')
    for env in envs:
        g   = env.get("group", "infratest")
        cls = GROUP_CLASSES.get(g, ("g-it", "e-it"))[1]
        p.append(
            f'<th class="{cls}">'
            f'<span class="env-name">{esc(env["name"])}</span>'
            f'<span class="env-url">{esc(env.get("url", ""))}</span>'
            f'</th>'
        )
    p.append('</tr>')
    p.append('</thead>')

    # ── Table body ─────────────────────────────────────────────────────────
    p.append('<tbody>')

    # Last-update row — first row of the table
    p.append('<tr class="ur"><td class="ur-label">Last Update</td><td></td>')
    for env in envs:
        val = versions.get(env["name"], {}).get("update_time", "")
        p.append(f'<td class="vc">{esc(val)}</td>')
    p.append('</tr>')

    # Product rows
    for product in products:
        key       = product["key"]
        name      = product["name"]
        jproj     = product.get("jira_project", "")
        add_urls  = product.get("additional_urls", [])
        templates = product.get("templates", [])
        tickets   = jira_bugs.get(key, [])

        # Build product label cell
        plinks_html = "".join(
            f'<a href="{esc(a["url"])}" class="plink" target="_blank">{esc(a["name"])}</a>'
            for a in add_urls
        )
        jira_html = ""
        if jproj and jproj != "CONFIGURE_ME":
            jira_html = (
                f'<a href="{esc(jira_base)}/projects/{esc(jproj)}" '
                f'class="jira-lnk" target="_blank">JIRA: {esc(jproj)}</a>'
            )
        badge_html = bug_badge(tickets, name)

        label_cell = (
            f'<td class="lp">'
            f'<div class="phead"><span class="pname">{esc(name)}</span>{badge_html}</div>'
            + (f'<div class="plinks">{plinks_html}</div>' if plinks_html else "")
            + jira_html
            + f'</td>'
        )

        p.append(f'<tr class="pr">{label_cell}<td class="lt"></td>')
        for i, env in enumerate(envs):
            prev_v = _raw_version_str(versions.get(envs[i-1]["name"], {}).get(key, "")) if i > 0 else ""
            cur_v  = _raw_version_str(versions.get(env["name"], {}).get(key, ""))
            d      = semver_drift(cur_v, prev_v)
            p.append(version_cell(env["name"], key, versions, ci_status, drift=d))
        p.append('</tr>')

        # Template rows
        for tpl in templates:
            tkey   = tpl["key"]
            tname  = tpl["name"]
            tlinks = "".join(
                f'<a href="{esc(a["url"])}" class="plink" target="_blank">{esc(a["name"])}</a>'
                for a in tpl.get("additional_urls", [])
            )
            tlabel = (
                f'<td class="lt">'
                f'<span class="tname">{esc(tname)}</span>'
                + (f'<div class="plinks">{tlinks}</div>' if tlinks else "")
                + f'</td>'
            )
            p.append(f'<tr class="tr"><td class="lp"></td>{tlabel}')
            for i, env in enumerate(envs):
                prev_v = _raw_version_str(versions.get(envs[i-1]["name"], {}).get(tkey, "")) if i > 0 else ""
                cur_v  = _raw_version_str(versions.get(env["name"], {}).get(tkey, ""))
                d      = semver_drift(cur_v, prev_v)
                p.append(version_cell(env["name"], tkey, versions, ci_status, show_ci=False, drift=d))
            p.append('</tr>')

    p.append('</tbody>')
    p.append('</table></div>')

    # Bug popup container (populated by JS on hover)
    p.append('<div id="bug-popup"></div>')
    p.append(f'<script>{JS}</script>')
    p.append('</body></html>')

    return "\n".join(p)


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Loading config...")
    config = load_config()
    print("Loading versions...")
    versions = load_versions(config)
    print("Fetching CI status...")
    ci_data = fetch_ci_status(config)
    print("Fetching JIRA bugs...")
    jira_data = fetch_jira_bugs(config)
    print("Generating HTML...")
    html = generate_html(config, versions, ci_data, jira_data)
    Path("public").mkdir(exist_ok=True)
    out = Path("public/index.html")
    out.write_text(html, encoding="utf-8")
    size_kb = out.stat().st_size // 1024
    print(f"  public/index.html written ({size_kb} KB)")


if __name__ == "__main__":
    main()
