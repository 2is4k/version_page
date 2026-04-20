# ICE Infrastructure Dashboard

> **⚠ Internal & experimental.** This page is not intended for productive use or as an official reference for reports. Data may be incomplete, delayed, or based on dummy values. Use it as a quick orientation aid only.

A static HTML dashboard for tracking deployed versions, CI test passrates, and open QA bugs across all infrastructure products and environments. Used as a fast daily overview in management meetings across a 350-developer organisation.

---

## Part 1 — How to read the dashboard

### Layout

The table has one fixed label column on the left and one column per environment to the right. Environments are ordered left to right from least stable to most stable:

| Header colour | Group | Stage |
|---|---|---|
| Blue | InfraTest | Development & automated testing |
| Sky | VE | Validation |
| Teal | AppDev | Near-stable / application testing |
| Green | Production | Stable, customer-facing |

Each product occupies one row. Workflow templates belonging to a product appear below it, indented.

### Timestamps

- **Generated** (top-right of the bar) — when the page was last built.
- **Last Update** (first data row) — when each environment's version file was last written.

If either timestamp is from a previous day it turns **orange** as a staleness warning. Fresh data is shown without highlighting.

### Version cells

Each environment cell shows the version currently deployed in that environment. If a version is a hyperlink, clicking it opens the release or changelog page. Additional links (e.g. release notes) appear below the version number in smaller text.

**Semver drift arrows** — red `↓` symbols next to a version mean that environment is behind the one to its left:

| Arrows | Drift |
|---|---|
| `↓` | Patch version behind |
| `↓↓` | Minor version behind |
| `↓↓↓` | Major version behind |

No arrows means versions are equal or the environment is ahead.

### Footer

The page footer shows:

- **© Infra QA Team** — authoring team
- A reminder that the page is internal and experimental
- **How to read this document** — link to this README

### CI passrate badge

A small coloured pill in each version cell shows the percentage of CI test runs that passed for that product in that environment. Clicking it opens the corresponding TestRail test plan or run.

| Colour | Label | Meaning |
|---|---|---|
| Green | 90–100 | Healthy |
| Yellow | 61–89 | Degraded |
| Red | 0–60 | Failing |
| Gray `~` | — | Test plan found but no run matches the current version or environment — click to view the plan |
| Gray `?` | — | No matching test plan found in TestRail |
| Gray `-` | — | CI not configured for this environment, or no version deployed |

The `~` badge is a link — clicking it opens the test plan so you can inspect available runs manually.

If no version is deployed in an environment the badge always shows gray `-` regardless of any configured passrate value, since a passrate without a deployment is meaningless.

Workflow template rows do not show CI passrate badges.

### QA bug badge

A small pill on the product name shows the count of open JIRA bugs tagged `[QA]:` for that product. Hovering over a non-zero badge opens a popup listing each ticket with its key, summary, current status, and assignee.

| Colour | Value | Meaning |
|---|---|---|
| Black | 1 or more | Open QA bugs — hover for details |
| Gray `0` | 0 | No open bugs |
| Gray `-` | — | JIRA not configured for this product |

---

## Part 2 — Technical details

### How it works

`generate.py` reads configuration and version data, optionally queries live APIs, and writes `public/index.html`. No external Python dependencies are required.

```
generate.py  ──►  public/index.html
     │
     ├── config.json          (environments, products, CI config, dummy data)
     ├── versions/InfraTestDev.json
     ├── versions/VE.json
     └── ...                  (one file per environment)
```

**Data sources:**

1. **`config.json`** — environments, products, JIRA projects, TestRail config, and embedded fallback data
2. **`versions/*.json`** — one file per environment with currently deployed versions
3. **TestRail API** *(optional, live mode)* — fetches test plan and run results per product/environment
4. **JIRA API** *(optional, live mode)* — fetches open `[QA]:` bug tickets per product

### Example mode vs live mode

Without API credentials the script automatically falls back to the static `ci_config` block in `config.json` for passrates and hardcoded example tickets for JIRA. The page always builds successfully regardless.

| Mode | Trigger |
|---|---|
| Example | `TESTRAIL_PASSWORD` / `JIRA_TOKEN` not set, or `--example` / `--dummy` flag |
| Live | All credential env vars set |

```bash
python generate.py             # auto-detect
python generate.py --example   # force example data
python generate.py --dummy     # alias for --example
```

### Configuration

All configuration lives in `config.json`. Replace every `CONFIGURE_ME` placeholder before enabling live mode.

#### Environments

```json
{
  "name": "ProdBelgium",
  "url": ".nzero.be",
  "group": "prod",
  "group_label": "Production"
}
```

`group` controls the header colour band. Supported values: `infratest`, `ve`, `appdev`, `prod`.

#### Products

```json
{
  "key": "ice_client_access",
  "name": "EDP Client Access 1.5",
  "jira_project": "EDPIPPN",
  "jira_jql": "project = \"{{ jira_project }}\" AND issuetype = Bug AND summary ~ \"QA\" AND status NOT IN (Closed, Done, Cancelled, Resolved)",
  "testrail_plan": "Client Access",
  "testrail_run_consists_of": "{{ env }}",
  "expected_results_in": ["InfraTestDev", "InfraTestTest", "InfraTestIntegration", "VE"],
  "additional_urls": [
    { "name": "release notes", "url": "https://..." }
  ],
  "templates": [
    {
      "key": "create_rule_panorama",
      "name": "Create_Rule_Panorama",
      "expected_results_in": []
    }
  ]
}
```

- `testrail_plan` — name (or substring) of the TestRail test plan to look up. Supports `{{ version }}` template variable.
- `testrail_run_consists_of` — comma-separated Jinja2 template of terms that must all appear in the matched run name. Variables: `{{ env }}`, `{{ version }}`, `{{ now }}`.
- `expected_results_in` — list of environment names where TestRail results are expected. Other environments show gray `-`.
- `jira_jql` — per-product JQL override (Jinja2 template). If omitted, the top-level `jira_jql` is used.

#### CI passrate fallback (`ci_config`)

When running in example mode, passrates are read from the `ci_config` block in `config.json`. This block is also the source for embedded demo data shown without any API credentials.

```json
"ci_config": {
  "ice_client_access": {
    "InfraTestDev":  { "passrate": 97, "testplan_url": "https://..." },
    "ProdBelgium":   { "passrate": "-" }
  }
}
```

Set `"passrate": "-"` to mark an environment as not CI-covered. Omit the environment entirely to show nothing in that cell. In live mode this block is ignored; results come directly from TestRail.

#### Version files

One JSON file per environment in `versions/`. The key is the product or template `key`:

```json
{
  "ice_client_access": {
    "version": "1.5.3",
    "url": "https://release-page/1.5.3",
    "additional_urls": [
      { "name": "changelog", "url": "https://..." }
    ]
  },
  "update_time": "2026-04-19 08:00 UTC"
}
```

### Deployment

The page is deployed via GitLab Pages. On every push to `main` the CI pipeline runs `generate.py` and publishes `public/index.html`.

Set the following CI/CD variables in your GitLab project to enable live data:

| Variable | Description |
|---|---|
| `TESTRAIL_USER` | TestRail username / email |
| `TESTRAIL_PASSWORD` | TestRail password or API key |
| `JIRA_TOKEN` | JIRA personal access token (Bearer) |

### Local development

```bash
python generate.py --dummy
open public/index.html
```

Requires `requests` and `jinja2` (`pip install -r requirements.txt`).
