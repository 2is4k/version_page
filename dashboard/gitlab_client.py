"""GitLab API client — fetches live pipeline URLs for CI passrate badges."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional


class GitLabClient:
    """Fetches pipeline URLs from the GitLab API.

    Passrate values are always read from ci_config in config.json (manually
    maintained). Only pipeline_url is updated from the live API.
    In example mode the client returns ci_config data as-is without any network
    calls.
    """

    def __init__(self, config: dict, example: bool = False) -> None:
        self.config  = config
        self.example = example
        self.token   = os.environ.get("GITLAB_TOKEN", "")

    # ── public ───────────────────────────────────────────────────────────────

    def fetch_ci_status(self) -> dict:
        """Return {item_key: {env_name: {passrate, pipeline_url}}}."""
        ci_cfg = self.config.get("ci_config", {})
        result: dict = {k: dict(v) for k, v in ci_cfg.items()}

        if self.example or not self.token:
            if not self.example:
                print("  GITLAB_TOKEN not set → using ci_config pipeline URLs")
            return result

        base = self.config["gitlab_base_url"].rstrip("/")
        for product in self.config["products"]:
            key  = product["key"]
            urls = self._fetch_pipeline_urls(
                base,
                product.get("ci_project_id"),
                product.get("ci_project_url", ""),
                product.get("pipeline_env_mapping", {}),
            )
            self._merge_urls(result, key, urls)

            for tpl in product.get("templates", []):
                tkey  = tpl["key"]
                turls = self._fetch_pipeline_urls(
                    base,
                    tpl.get("ci_project_id"),
                    tpl.get("ci_project_url", ""),
                    tpl.get("pipeline_env_mapping", {}),
                )
                self._merge_urls(result, tkey, turls)

        return result

    # ── private ──────────────────────────────────────────────────────────────

    def _get(self, url: str) -> Optional[Any]:
        try:
            req = urllib.request.Request(
                url, headers={"PRIVATE-TOKEN": self.token}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code} ← {url}")
        except Exception as e:
            print(f"  Error ← {url}: {e}")
        return None

    def _fetch_pipeline_urls(
        self,
        base: str,
        project_id: Any,
        project_url: str,
        env_map: dict,
    ) -> dict:
        if not project_id or str(project_id) == "CONFIGURE_ME":
            return {}
        enc  = urllib.parse.quote(str(project_id), safe="")
        data = self._get(f"{base}/api/v4/projects/{enc}/pipeline_schedules")
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

    @staticmethod
    def _merge_urls(result: dict, key: str, urls: dict) -> None:
        for env_name, url in urls.items():
            if key in result and env_name in result[key]:
                result[key][env_name]["pipeline_url"] = url
