"""JIRA API client — retrieves open QA bug tickets at runtime.

Bug data is never stored in config files. In example mode the client returns
a set of realistic hardcoded tickets so the page can be previewed without any
network connections or credentials.

If a live retrieval fails for a product the result carries error=True and the
renderer will show an exclamation mark badge instead of a count.
"""

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional


# ── Result type ──────────────────────────────────────────────────────────────

@dataclass
class JiraResult:
    """Outcome of a JIRA query for one product."""
    tickets: list       = field(default_factory=list)
    configured: bool    = True   # False when jira_project is not set
    error: bool         = False  # True when the API call failed


# ── Example data (used in --example / --dummy mode) ──────────────────────────

_EXAMPLE: dict[str, list] = {
    "ice_client_access": [],
    "ice_core": [
        {
            "key":      "EDPIPCO-234",
            "summary":  "[QA]: ICE Core provisioning fails when IPAM service is unavailable — timeout not handled gracefully",
            "status":   "In Progress",
            "assignee": "Anna Schmidt",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPCO-234",
        },
        {
            "key":      "EDPIPCO-198",
            "summary":  "[QA]: Internal API returns 500 on concurrent AZ creation requests under load",
            "status":   "Open",
            "assignee": "Marco Bianchi",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPCO-198",
        },
    ],
    "ice_flow": [
        {
            "key":      "EDPIPIF-445",
            "summary":  "[QA]: ICE Flow DNS zone workflow hangs indefinitely on InfraTestIntegration when upstream times out",
            "status":   "In Progress",
            "assignee": "Elena Kovač",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPIF-445",
        },
        {
            "key":      "EDPIPIF-423",
            "summary":  "[QA]: Create VM workflow does not clean up partially created resources on failure — resource leak",
            "status":   "Open",
            "assignee": "Thomas Weber",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPIF-423",
        },
        {
            "key":      "EDPIPIF-401",
            "summary":  "[QA]: L3 Zone Cisco template fails with malformed JSON response from Cisco APIC API",
            "status":   "In Review",
            "assignee": "Elena Kovač",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPIF-401",
        },
    ],
    "workspace_ice_fow": [
        {
            "key":      "EDPIPWS-88",
            "summary":  "[QA]: Workspace provisioning fails silently when base service is not responding",
            "status":   "Open",
            "assignee": "Unassigned",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPWS-88",
        },
    ],
    "ice_scape": [],
    "ipam": [
        {
            "key":      "EDPIPAM-112",
            "summary":  "[QA]: IPAM returns incorrect subnet mask for /29 allocations in secondary AZ",
            "status":   "In Progress",
            "assignee": "Piotr Nowak",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPAM-112",
        },
        {
            "key":      "EDPIPAM-108",
            "summary":  "[QA]: IPAM API does not respect X-Request-ID header for distributed tracing correlation",
            "status":   "Open",
            "assignee": "Piotr Nowak",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPAM-108",
        },
        {
            "key":      "EDPIPAM-103",
            "summary":  "[QA]: IP release does not propagate to secondary AZ within SLA window",
            "status":   "Open",
            "assignee": "Unassigned",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPAM-103",
        },
        {
            "key":      "EDPIPAM-97",
            "summary":  "[QA]: Bulk IP allocation fails silently when request exceeds 50 addresses",
            "status":   "In Progress",
            "assignee": "Sophie Müller",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPAM-97",
        },
        {
            "key":      "EDPIPAM-91",
            "summary":  "[QA]: IPAM health check returns HTTP 200 when database connection is unreachable",
            "status":   "Open",
            "assignee": "Unassigned",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPAM-91",
        },
        {
            "key":      "EDPIPAM-89",
            "summary":  "[QA]: IPAM allocation metrics not exported to Prometheus in production environments",
            "status":   "In Review",
            "assignee": "Sophie Müller",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPAM-89",
        },
    ],
    "object_storage": [
        {
            "key":      "EDPIPOS-67",
            "summary":  "[QA]: NetApp bucket creation fails with 409 Conflict when bucket name contains uppercase letters",
            "status":   "In Progress",
            "assignee": "Lars Jensen",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPOS-67",
        },
        {
            "key":      "EDPIPOS-63",
            "summary":  "[QA]: User quota not enforced for existing buckets after storage policy update",
            "status":   "Open",
            "assignee": "Lars Jensen",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPOS-63",
        },
        {
            "key":      "EDPIPOS-61",
            "summary":  "[QA]: Object storage API returns incorrect ETag header format — breaks S3-compatible clients",
            "status":   "Open",
            "assignee": "Unassigned",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPOS-61",
        },
        {
            "key":      "EDPIPOS-58",
            "summary":  "[QA]: Bucket deletion workflow leaves orphaned IAM policies in NetApp ONTAP",
            "status":   "In Review",
            "assignee": "Maria Santos",
            "url":      "https://jira.bare.pandrosion.org/browse/EDPIPOS-58",
        },
    ],
    "workspace_base_service": [],
}


# ── Client ───────────────────────────────────────────────────────────────────

class JiraClient:
    """Fetches open [QA]: bug tickets from JIRA at runtime.

    Returns a dict of {product_key: JiraResult}.  On network or auth failure
    the result has error=True; the renderer will display '!' instead of a count.
    """

    def __init__(self, config: dict, example: bool = False) -> None:
        self.config  = config
        self.example = example
        self.user    = os.environ.get("JIRA_USER", "")
        self.token   = os.environ.get("JIRA_TOKEN", "")

    # ── public ───────────────────────────────────────────────────────────────

    def fetch_bugs(self) -> dict[str, JiraResult]:
        """Return {product_key: JiraResult} for every product in config."""
        if self.example:
            return self._build_example()

        if not (self.user and self.token):
            print("  JIRA_TOKEN/JIRA_USER not set → using example JIRA data")
            return self._build_example()

        base    = self.config["jira_base_url"].rstrip("/")
        result: dict[str, JiraResult] = {}

        for product in self.config["products"]:
            key          = product["key"]
            jira_project = product.get("jira_project", "")

            if not jira_project or jira_project == "CONFIGURE_ME":
                result[key] = JiraResult(configured=False)
                continue

            print(f"  JIRA: {key} ({jira_project})")
            data = self._query(base, jira_project)
            if data is None:
                result[key] = JiraResult(error=True)
                continue

            tickets = [
                {
                    "key":      issue["key"],
                    "summary":  issue.get("fields", {}).get("summary", ""),
                    "status":   (issue.get("fields", {}).get("status") or {}).get("name", "Unknown"),
                    "assignee": ((issue.get("fields", {}).get("assignee")) or {}).get("displayName", "Unassigned"),
                    "url":      f"{base}/browse/{issue['key']}",
                }
                for issue in data.get("issues", [])
            ]
            result[key] = JiraResult(tickets=tickets)

        return result

    # ── private ──────────────────────────────────────────────────────────────

    def _get(self, url: str) -> Optional[Any]:
        creds   = base64.b64encode(f"{self.user}:{self.token}".encode()).decode()
        headers = {"Authorization": f"Basic {creds}", "Accept": "application/json"}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code} ← {url}")
        except Exception as e:
            print(f"  Error ← {url}: {e}")
        return None

    def _query(self, base: str, jira_project: str) -> Optional[Any]:
        jql = (
            f'project = "{jira_project}" AND issuetype = Bug '
            f'AND summary ~ "[QA]:" AND status NOT IN '
            f'(Closed, Done, Cancelled, Resolved)'
        )
        url = (
            f"{base}/rest/api/2/search"
            f"?jql={urllib.parse.quote(jql)}&maxResults=50&fields=summary,status,assignee"
        )
        return self._get(url)

    def _build_example(self) -> dict[str, JiraResult]:
        result: dict[str, JiraResult] = {}
        for product in self.config["products"]:
            key          = product["key"]
            jira_project = product.get("jira_project", "")
            if not jira_project or jira_project == "CONFIGURE_ME":
                result[key] = JiraResult(configured=False)
            else:
                result[key] = JiraResult(tickets=list(_EXAMPLE.get(key, [])))
        return result
