"""HTML renderer for the Infrastructure Dashboard."""

import json
import re
from datetime import datetime, timezone
from typing import Any

from .jira_client import JiraResult


# ── Constants ────────────────────────────────────────────────────────────────

GROUP_CLASSES: dict[str, tuple[str, str]] = {
    "infratest": ("g-it", "e-it"),
    "ve": ("g-ve", "e-ve"),
    "appdev": ("g-ad", "e-ad"),
    "prod": ("g-pr", "e-pr"),
}

CSS = """
:root {
  --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --bg: #f1f5f9;
  --surface: #fff;
  --border: #e2e8f0;
  --text: #0f172a;
  --muted: #64748b;
  --bar-h: 52px;
  --footer-h: 32px;
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
.bar-ts.stale { color: #f97316; font-weight: 600; }
.bar-legend { display: flex; align-items: center; gap: 10px; margin-left: 12px; }
.leg { display: flex; align-items: center; gap: 4px; font-size: 10px; color: #64748b; }

/* ── table wrapper — this IS the scroll container for the table ── */
.wrap {
  overflow-x: auto;
  overflow-y: auto;
  height: calc(100vh - var(--bar-h) - var(--footer-h));
}
table { border-collapse: collapse; width: max-content; min-width: 100%; background: var(--surface); }

/* ── group-header row ── */
.gh { height: 26px; }
.gh th {
  position: sticky; top: 0; z-index: 90;
  padding: 0 8px; text-align: center;
  font-size: 9px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase;
  color: rgba(255,255,255,.65); white-space: nowrap;
}
.gh .lbl  { background: #1e293b; color: #334155; }
.gh .g-it { background: #1e3a8a; }   /* blue         — dev / test  */
.gh .g-ve { background: #0c4a6e; }   /* dark sky     — validation  */
.gh .g-ad { background: #134e4a; }   /* dark teal    — near-stable */
.gh .g-pr { background: #14532d; }   /* forest green — production  */

/* ── env-header row ── */
.eh th {
  position: sticky; top: 26px; z-index: 89;
  padding: 6px 8px; text-align: center;
  font-size: 11px; font-weight: 600; color: #e2e8f0;
  border-right: 1px solid rgba(255,255,255,.07);
  border-bottom: 3px solid #475569;
  width: 1px; white-space: nowrap;
}
.eh .lbl { background: #1e293b; text-align: left !important; color: #64748b; font-size: 10px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; white-space: nowrap; }
.eh .e-it { background: #1e3a8a; border-top: 2px solid #60a5fa; }
.eh .e-ve { background: #0c4a6e; border-top: 2px solid #38bdf8; }
.eh .e-ad { background: #134e4a; border-top: 2px solid #2dd4bf; }
.eh .e-pr { background: #14532d; border-top: 2px solid #4ade80; }
.env-name { display: block; }
.env-url  { display: block; font-size: 9px; font-weight: 400; color: rgba(255,255,255,.4); margin-top: 2px; white-space: nowrap; }

/* sticky label column in header */
.gh .sl1, .eh .sl1 {
  position: sticky !important; left: 0; z-index: 95 !important;
  background: #1e293b !important;
  border-left:  2px solid #0f172a !important;
  border-right: none !important;
  box-shadow: 3px 0 0 0 #0f172a;
}

/* ── tbody rows ── */
tbody tr { border-bottom: 1px solid var(--border); }
tbody tr:hover td { background: #f0f9ff !important; }

/* sticky label column */
td.lp {
  position: sticky; left: 0; z-index: 10;
  width: 1px;
  background: #f4f6f8; padding: 8px 10px; vertical-align: top;
  border-left:  2px solid #0f172a;
  border-right: none;
  box-shadow: 3px 0 0 0 #0f172a;
}

/* product row */
tr.pr { background: #fff; }
tr.pr td.lp { border-left: 3px solid #3b82f6; }
.pname { font-weight: 700; color: #0f172a; font-size: 13px; line-height: 1.3; white-space: nowrap; }
.phead { display: flex; align-items: flex-start; justify-content: space-between; gap: 6px; margin-bottom: 3px; }
.plinks { display: flex; flex-direction: column; gap: 1px; margin-top: 2px; }
.plink  { font-size: 10px; color: #64748b; text-decoration: none; overflow-wrap: break-word; word-break: break-word; }
.plink:hover { color: #2563eb; }
.jira-lnk { font-size: 10px; color: #0052cc; text-decoration: none; margin-top: 3px; display: inline-block; }
.jira-lnk:hover { text-decoration: underline; }

/* template row — indented inside the same label column */
tr.tr { background: #f8fafc; }
tr.tr td.lp { padding-left: 20px; }
.tname { display: block; color: #475569; font-size: 11px; overflow-wrap: break-word; word-break: break-all; }

/* update row */
tr.ur { background: #f8fafc; border-top: 2px solid var(--border); }
tr.ur td { font-size: 11px; color: var(--muted); padding: 6px 10px; font-style: italic; }
td.ur-label { padding: 6px 10px; font-size: 11px; color: var(--muted); font-style: italic; font-weight: 600; }
tr.ur td.stale { background: #fff7ed; color: #c2410c; font-style: normal; font-weight: 600; }

/* ── version cells ── */
td.vc { padding: 7px 8px; vertical-align: top; border-right: 1px solid var(--border); white-space: nowrap; width: 1px; background: #fff; }
.cell-v { margin-bottom: 2px; }
.version-link  { font-weight: 700; color: #0000EE; text-decoration: none; font-size: 15px; }
.version-link:hover { text-decoration: underline; }
.version-text  { font-weight: 500; color: #334155; }
.version-empty { color: #cbd5e1; user-select: none; }

/* drift indicators */
.drift   { font-size: 11px; font-weight: 800; margin-left: 3px;
           vertical-align: middle; letter-spacing: -2px; line-height: 1; }
.drift-1 { color: #f87171; }
.drift-2 { color: #dc2626; }
.drift-3 { color: #7f1d1d; }

.cell-links { display: flex; flex-direction: column; gap: 2px; margin-bottom: 3px; }
.sub-link { font-size: 10px; color: #0000EE; text-decoration: none; white-space: nowrap; }
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
.pr-green  { background: #16a34a; }
.pr-yellow { background: #d97706; }
.pr-red    { background: #dc2626; }
.pr-none   { background: #94a3b8; }

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
.bug-zero    { background: #94a3b8; }
.bug-nonzero { background: #0f172a; }
.bug-error   { background: #f97316; }

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

/* ── Footer ── */
footer {
  position: fixed; bottom: 0; left: 0; right: 0;
  padding: 6px 20px;
  background: #f8fafc; border-top: 1px solid #e2e8f0;
  font-size: 11px; color: #94a3b8;
  display: flex; gap: 20px; align-items: center; flex-wrap: wrap;
  z-index: 100;
}
footer a { color: #94a3b8; text-decoration: underline; }
footer a:hover { color: #475569; }
"""

JS = r"""
(function () {
  'use strict';

  /* ── Freeze the sticky label column at its natural content width ── */
  function freezeStickyCol() {
    var first = document.querySelector('td.lp, th.sl1');
    if (!first) return;
    var w = first.offsetWidth;
    document.querySelectorAll('td.lp, th.sl1').forEach(function (el) {
      el.style.width    = w + 'px';
      el.style.minWidth = w + 'px';
      el.style.maxWidth = w + 'px';
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', freezeStickyCol);
  } else {
    freezeStickyCol();
  }

  /* ── Mark stale timestamps ── */
  function checkStale() {
    var now = new Date();

    /* Generated bar: stale if date differs from today */
    var yy = now.getFullYear();
    var mm = String(now.getMonth() + 1).padStart(2, '0');
    var dd = String(now.getDate()).padStart(2, '0');
    var todayIso = yy + '-' + mm + '-' + dd;
    document.querySelectorAll('[data-ts]').forEach(function (el) {
      if (el.dataset.ts && el.dataset.ts !== todayIso) {
        el.classList.add('stale');
      }
    });

    /* Last Update cells: stale if older than 24 hours */
    var cutoff = now.getTime() - 24 * 60 * 60 * 1000;
    document.querySelectorAll('[data-ts-full]').forEach(function (el) {
      var raw = el.dataset.tsFull;
      if (!raw) return;
      /* Normalise "2026-04-19 08:00 UTC" → parseable by Date() */
      var parsed = new Date(raw.replace(' UTC', 'Z').replace(' ', 'T'));
      if (!isNaN(parsed.getTime()) && parsed.getTime() < cutoff) {
        el.classList.add('stale');
      }
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', checkStale);
  } else {
    checkStale();
  }

  /* ── Bug popup ── */
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

    var W  = 580, H = Math.min(440, 90 + bugs.length * 46);
    var rc = badge.getBoundingClientRect();
    var left = rc.right + 12;
    var top  = rc.top - 4;

    if (left + W > window.innerWidth  - 8) { left = rc.left - W - 12; }
    if (top  + H > window.innerHeight - 8) { top  = window.innerHeight - H - 8; }
    if (left < 8) left = 8;
    if (top  < 52) top = 52;

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


# ── Renderer ─────────────────────────────────────────────────────────────────


class DashboardRenderer:
    """Renders the full dashboard HTML from collected data."""

    def __init__(
        self,
        config: dict,
        versions: dict,
        passrates: dict,
        jira_bugs: dict[str, JiraResult],
    ) -> None:
        self.config = config
        self.versions = versions
        self.passrates = passrates
        self.jira_bugs = jira_bugs
        self.jira_base = config.get("jira_base_url", "").rstrip("/")
        self.generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── public ───────────────────────────────────────────────────────────────

    def render(self) -> str:
        parts: list[str] = []
        parts += self._head()
        parts += self._bar()
        parts += self._table()
        parts.append(self._footer())
        parts.append(f"<script>{JS}</script>")
        parts.append("</body></html>")
        return "\n".join(parts)

    # ── private: page sections ────────────────────────────────────────────────

    def _head(self) -> list[str]:
        return [
            "<!DOCTYPE html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="UTF-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
            "<title>Infrastructure Dashboard</title>",
            f"<style>{CSS}</style>",
            "</head>",
            "<body>",
        ]

    def _bar(self) -> list[str]:
        ts = self.generated
        return [
            f'<div class="bar">'
            f'<span class="bar-title">Infrastructure Dashboard</span>'
            f'<div class="bar-legend">'
            f'<span class="leg"><span class="pr-badge pr-green"  style="pointer-events:none">95</span> ≥90% pass</span>'
            f'<span class="leg"><span class="pr-badge pr-yellow" style="pointer-events:none">75</span> 61-89%</span>'
            f'<span class="leg"><span class="pr-badge pr-red"    style="pointer-events:none">42</span> ≤60%</span>'
            f'<span class="leg"><span class="bug-badge bug-nonzero" style="pointer-events:none">3</span> QA bugs</span>'
            f'<span class="leg"><span class="bug-badge bug-zero"    style="pointer-events:none">0</span> none</span>'
            f'<span class="leg"><span class="bug-badge bug-error"   style="pointer-events:none">!</span> JIRA error</span>'
            f"</div>"
            f'<span class="bar-tag">EDP</span>'
            f'<span class="bar-ts" data-ts="{ts[:10]}">Generated {ts}</span>'
            f"</div>"
        ]

    def _footer(self) -> str:
        readme_url = (
            "https://gitlab.bare.pandrosion.org/edp/infrastructure/"
            "platform-development/core/ice-version-tracking/-/blob/main/README.md"
        )
        return (
            f"<footer>"
            f"<span>&#169; Infra QA Team</span>"
            f"<span>Internal &amp; experimental — not an official report</span>"
            f"<span>Self-contained page — can be distributed or embedded as-is</span>"
            f'<a href="{readme_url}" target="_blank">How to read this document</a>'
            f"</footer>"
        )

    def _table(self) -> list[str]:
        envs = self.config["environments"]
        groups = self._compute_groups(envs)

        p: list[str] = ['<div class="wrap"><table>', "<thead>"]

        # Group header
        p.append('<tr class="gh">')
        p.append('<th class="lbl sl1"></th>')
        for g in groups:
            p.append(
                f'<th class="{g["cls"]}" colspan="{g["span"]}">{_esc(g["label"])}</th>'
            )
        p.append("</tr>")

        # Env header
        p.append('<tr class="eh">')
        p.append('<th class="lbl sl1">Product / Template</th>')
        for env in envs:
            cls = GROUP_CLASSES.get(env.get("group", "infratest"), ("g-it", "e-it"))[1]
            p.append(
                f'<th class="{cls}">'
                f'<span class="env-name">{_esc(env["name"])}</span>'
                f'<span class="env-url">{_esc(env.get("url", ""))}</span>'
                f"</th>"
            )
        p.append("</tr>")
        p.append("</thead>")
        p.append("<tbody>")

        # Last Update row
        p.append('<tr class="ur"><td class="ur-label">Last Update</td>')
        for env in envs:
            val = self.versions.get(env["name"], {}).get("update_time", "")
            attr = f' data-ts-full="{_esc(val)}"' if val else ""
            p.append(f'<td class="vc"{attr}>{_esc(val)}</td>')
        p.append("</tr>")

        # Product rows
        for product in self.config["products"]:
            p += self._product_rows(product, envs)

        p += ["</tbody>", "</table></div>", '<div id="bug-popup"></div>']
        return p

    def _product_rows(self, product: dict, envs: list) -> list[str]:
        key = product["key"]
        name = product["name"]
        jproj = product.get("jira_project", "")
        add_urls = product.get("additional_urls", [])
        templates = product.get("templates", [])
        result = self.jira_bugs.get(key, JiraResult(configured=False))

        plinks = "".join(
            f'<a href="{_esc(a["url"])}" class="plink" target="_blank">{_esc(a["name"])}</a>'
            for a in add_urls
        )
        jira_link = (
            f'<a href="{_esc(self.jira_base)}/projects/{_esc(jproj)}" '
            f'class="jira-lnk" target="_blank">JIRA: {_esc(jproj)}</a>'
            if jproj and jproj != "CONFIGURE_ME"
            else ""
        )
        label_cell = (
            f'<td class="lp">'
            f'<div class="phead"><span class="pname">{_esc(name)}</span>'
            f"{self._bug_badge(result, name)}</div>"
            + (f'<div class="plinks">{plinks}</div>' if plinks else "")
            + jira_link
            + "</td>"
        )

        rows: list[str] = [f'<tr class="pr">{label_cell}']
        for i, env in enumerate(envs):
            prev_v = (
                _raw_ver(self.versions.get(envs[i - 1]["name"], {}).get(key, ""))
                if i > 0
                else ""
            )
            cur_v = _raw_ver(self.versions.get(env["name"], {}).get(key, ""))
            rows.append(
                self._version_cell(env["name"], key, drift=_semver_drift(cur_v, prev_v))
            )
        rows.append("</tr>")

        for tpl in templates:
            rows += self._template_rows(tpl, envs)

        return rows

    def _template_rows(self, tpl: dict, envs: list) -> list[str]:
        tkey = tpl["key"]
        tname = tpl["name"]
        tlinks = "".join(
            f'<a href="{_esc(a["url"])}" class="plink" target="_blank">{_esc(a["name"])}</a>'
            for a in tpl.get("additional_urls", [])
        )
        tlabel = (
            f'<td class="lp">'
            f'<span class="tname">{_esc(tname)}</span>'
            + (f'<div class="plinks">{tlinks}</div>' if tlinks else "")
            + "</td>"
        )
        rows = [f'<tr class="tr">{tlabel}']
        for i, env in enumerate(envs):
            prev_v = (
                _raw_ver(self.versions.get(envs[i - 1]["name"], {}).get(tkey, ""))
                if i > 0
                else ""
            )
            cur_v = _raw_ver(self.versions.get(env["name"], {}).get(tkey, ""))
            rows.append(
                self._version_cell(
                    env["name"],
                    tkey,
                    show_testrail=False,
                    drift=_semver_drift(cur_v, prev_v),
                )
            )
        rows.append("</tr>")
        return rows

    # ── private: cell renderers ───────────────────────────────────────────────

    def _version_cell(
        self,
        env_name: str,
        item_key: str,
        show_testrail: bool = True,
        drift: int = 0,
    ) -> str:
        raw = self.versions.get(env_name, {}).get(item_key, "")

        if isinstance(raw, dict):
            version = raw.get("version", "")
            url = raw.get("url")
            extras = raw.get("additional_urls", [])
        else:
            version = str(raw) if raw else ""
            url = None
            extras = []

        if version in ("ERROR", ""):
            version = ""

        drift_titles = [
            "",
            "patch version behind",
            "minor version behind",
            "major version behind",
        ]
        drift_html = (
            f'<span class="drift drift-{drift}" title="{drift_titles[drift]}">{"↓" * drift}</span>'
            if drift > 0
            else ""
        )

        if version:
            ver_html = (
                f'<a href="{_esc(url)}" class="version-link" target="_blank">'
                f"{_esc(version)}</a>{drift_html}"
                if url
                else f'<span class="version-text">{_esc(version)}</span>{drift_html}'
            )
        else:
            ver_html = '<span class="version-empty">—</span>'

        links_html = "".join(
            f'<a href="{_esc(a["url"])}" class="sub-link" target="_blank">{_esc(a["name"])}</a>'
            for a in extras
        )

        if show_testrail and not version:
            testrail_html = (
                '<span class="pr-badge pr-none" title="No version deployed">-</span>'
            )
        elif show_testrail:
            testrail_html = self._passrate_badge(
                env_name, self.passrates.get(item_key, {})
            )
        else:
            testrail_html = ""

        return (
            f'<td class="vc">'
            f'<div class="cell-v">{ver_html}</div>'
            + (f'<div class="cell-links">{links_html}</div>' if links_html else "")
            + f'<div class="cell-meta">{testrail_html}</div>'
            f"</td>"
        )

    @staticmethod
    def _passrate_badge(env_name: str, item_ci: dict) -> str:
        info = item_ci.get(env_name) if item_ci else None
        if not info or "passrate" not in info:
            return ""
        raw = info["passrate"]
        url = info.get("testplan_url", "")
        if str(raw) == "-":
            return '<span class="pr-badge pr-none" title="CI not configured for this environment">-</span>'
        if int(raw) == -1:
            if url:
                return (
                    f'<a href="{_esc(url)}" class="pr-badge pr-none" '
                    f'title="Test plan found but no run matches current version/environment — click to view" '
                    f'target="_blank">~</a>'
                )
            return '<span class="pr-badge pr-none" title="No matching test plan found in TestRail">?</span>'
        pct = int(raw)
        cls = "pr-green" if pct >= 90 else ("pr-yellow" if pct >= 61 else "pr-red")
        tip = f"CI passrate: {pct}%"
        if url:
            return f'<a href="{_esc(url)}" class="pr-badge {cls}" title="{_esc(tip)}" target="_blank">{pct}</a>'
        return f'<span class="pr-badge {cls}" title="{_esc(tip)}">{pct}</span>'

    @staticmethod
    def _bug_badge(result: JiraResult, product_name: str) -> str:
        if not result.configured:
            return '<span class="bug-badge bug-zero" title="JIRA not configured for this product">-</span>'
        if result.error:
            return '<span class="bug-badge bug-error" title="Failed to retrieve JIRA data">!</span>'
        n = len(result.tickets)
        cls = "bug-zero" if n == 0 else "bug-nonzero"
        bugs_js = _esc(json.dumps(result.tickets))
        title = (
            "No open QA bugs" if n == 0 else f"{n} open QA bug(s) — hover for details"
        )
        return (
            f'<span class="bug-badge {cls}" data-bugs="{bugs_js}" '
            f'data-product="{_esc(product_name)}" title="{title}">{n}</span>'
        )

    # ── private: helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _compute_groups(envs: list) -> list[dict]:
        groups: list[dict] = []
        for env in envs:
            g = env.get("group", "infratest")
            lbl = env.get("group_label", g.upper())
            cls = GROUP_CLASSES.get(g, ("g-it", "e-it"))[0]
            if groups and groups[-1]["label"] == lbl:
                groups[-1]["span"] += 1
            else:
                groups.append({"label": lbl, "cls": cls, "span": 1})
        return groups


# ── Module-level helpers ──────────────────────────────────────────────────────


def _esc(s: Any) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _raw_ver(version_data: Any) -> str:
    if isinstance(version_data, dict):
        v = version_data.get("version", "")
    else:
        v = str(version_data) if version_data else ""
    return "" if v == "ERROR" else v


def _extract_semver(v: str) -> tuple:
    if not v:
        return ()
    candidates = re.findall(r"\d+(?:\.\d+)+", v)
    if not candidates:
        return ()
    best = max(candidates, key=lambda s: len(s.split(".")))
    return tuple(int(p) for p in best.split("."))


def _semver_drift(current: str, previous: str) -> int:
    cur = _extract_semver(current)
    prv = _extract_semver(previous)
    if not cur or not prv or cur >= prv:
        return 0
    n = max(len(cur), len(prv))
    cur += (0,) * (n - len(cur))
    prv += (0,) * (n - len(prv))
    for i, (c, p) in enumerate(zip(cur, prv)):
        if c != p:
            return 3 if i == 0 else (2 if i == 1 else 1)
    return 0
