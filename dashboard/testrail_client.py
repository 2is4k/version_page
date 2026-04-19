"""TestRail API client — fetches test run results URLs for passrate badges."""

import json
import datetime
import os
import requests
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional
from jinja2 import Template


class TestRailClient:
    """Fetches test runs from the TestRail API."""

    def __init__(self, config: dict, versions: dict, example: bool = False) -> None:
        self.config = config
        self.versions = versions
        self.example = example
        self.user = os.environ.get("TESTRAIL_USER", "")
        self.password = os.environ.get("TESTRAIL_PASSWORD", "")
        self.session = requests.Session()
        self.session.auth = (self.user, self.password)
        self.session.verify = True

    # ── public ───────────────────────────────────────────────────────────────

    def fetch_passrates(self) -> dict:
        """Return {item_key: {env_name: {passrate, pipeline_url}}}."""
        ci_cfg = self.config.get("ci_config", {})
        result: dict = {k: dict(v) for k, v in ci_cfg.items()}

        if self.example or not self.password:
            if not self.example:
                print("  TESTRAIL_PASSWORD not set → using ci_config pipeline URLs")
            return result

        result: dict = {}
        url = (
            self.config["testrail_base_url"]
            + f"?/api/v2/get_plans/{self.config['testrail_project_id']}"
        )
        plans = self._get(url)
        for product in self.config["products"]:
            key = product["key"]
            for env in product.get("expected_results_in", []):
                version = self.versions[env].get(key, {}).get("version", "")
                testrail_run_consists_of = [
                    entry.strip()
                    for entry in Template(product.get("testrail_run_consists_of", ""))
                    .render(
                        env=env,
                        version=version,
                        now=datetime.datetime.fromisoformat(
                            self.versions[env].get("update_time", "2000-01-01 01:01:59")
                        ),
                    )
                    .split(",")
                ]
                passrate_info = self.get_passrate_info(
                    plans, product, version, testrail_run_consists_of
                )
                result.setdefault(key, {env: passrate_info})
        return result

    def get_passrate_info(
        self, plans, product, version, testrail_run_consists_of
    ) -> dict:
        # https://testrail.bare.pandrosion.org/index.php?/api/v2/get_plan/32375
        # TODO improve
        passrate_info = {"passrate": -1, "up_to_date": False}
        for plan in plans["plans"]:
            if (
                product.get("testrail_plan")
                and Template(product["testrail_plan"]).render(version=version)
                in plan["name"]
            ):
                plan_details = self._get(
                    self.config["testrail_base_url"] + f"?/api/v2/get_plan/{plan['id']}"
                )
                for entry in plan_details["entries"]:
                    for run in entry["runs"]:
                        if all(
                            elem in run["name"] for elem in testrail_run_consists_of
                        ):
                            passrate_info["passrate"] = 100 * (run["passed_count"] / (
                                run["passed_count"] + run["custom_status1_count"]
                            ))
                            passrate_info["testplan_url"] = run["url"]
                            return passrate_info
        return passrate_info

    # ── private ──────────────────────────────────────────────────────────────

    def _get(self, url: str) -> Optional[Any]:
        try:
            response = self.session.get(url)
            return json.loads(response.content)
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
        enc = urllib.parse.quote(str(project_id), safe="")
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
