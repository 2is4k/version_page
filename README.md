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

### CI passrate badge

A small coloured pill in each version cell shows the percentage of CI test runs that passed for that product in that environment. Clicking it opens the corresponding GitLab pipeline.

| Colour | Range | Meaning |
|---|---|---|
| Green | 90–100% | Healthy |
| Yellow | 61–89% | Degraded |
| Red | 0–60% | Failing |
| Gray `-` | — | CI not configured, or no version deployed |

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

1. **`config.json`** — environments, products, JIRA projects, CI passrate config, and embedded dummy data
2. **`versions/*.json`** — one file per environment with currently deployed versions
3. **GitLab API** *(optional, live mode)* — fetches latest pipeline URLs from scheduled pipelines
4. **JIRA API** *(optional, live mode)* — fetches open `[QA]:` bug tickets per product

### Dummy mode vs live mode

Without API tokens the script automatically falls back to dummy data embedded in `config.json`. The page always builds successfully regardless.

| Mode | Trigger |
|---|---|
| Dummy | `GITLAB_TOKEN` / `JIRA_TOKEN` / `JIRA_USER` not set, or `--dummy` flag |
| Live | All three env vars set |

```bash
python generate.py           # auto-detect
python generate.py --dummy   # force dummy data
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
  "ci_project_id": "123",
  "ci_project_url": "https://gitlab.example.com/project",
  "pipeline_env_mapping": {
    "Schedule: InfraTestDev": "InfraTestDev"
  },
  "additional_urls": [
    { "name": "release notes", "url": "https://..." }
  ],
  "templates": [
    {
      "key": "create_rule_panorama",
      "name": "Create_Rule_Panorama",
      "additional_urls": []
    }
  ]
}
```

`pipeline_env_mapping` maps the GitLab pipeline schedule description to an environment name. Only needed in live mode.

#### CI passrate (`ci_config`)

Passrate values are maintained manually in `config.json`. They represent the historical pass percentage for each product/environment combination. In live mode only the `pipeline_url` is overridden by the actual last pipeline URL from the GitLab API; the passrate itself always comes from config.

```json
"ci_config": {
  "ice_client_access": {
    "InfraTestDev":  { "passrate": 97, "pipeline_url": "https://..." },
    "ProdBelgium":   { "passrate": "-" }
  }
}
```

Set `"passrate": "-"` to explicitly mark an environment as not CI-covered. Omit the environment entirely to show nothing in that cell.

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
| `GITLAB_TOKEN` | Personal access token with `read_api` scope |
| `JIRA_TOKEN` | JIRA personal access token |
| `JIRA_USER` | JIRA username / email |

### Local development

```bash
python generate.py --dummy
open public/index.html
```

No dependencies beyond Python 3.11 standard library.
