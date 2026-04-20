"""TestRail API client — fetches test run results URLs for passrate badges."""

import math
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
                result.setdefault(key, {})[env] = passrate_info
        return result

    def get_passrate_info(
        self, plans, product, version, testrail_run_consists_of
    ) -> dict:
        # https://testrail.bare.pandrosion.org/index.php?/api/v2/get_plan/32375
        # TODO improve
        if product["key"] == "ice_core":
            pass
        passrate_info = {"passrate": -1, "testplan_url": ""}
        for plan in plans["plans"]:
            if (
                product.get("testrail_plan")
                and Template(product["testrail_plan"]).render(version=version)
                in plan["name"]
            ):
                passrate_info["testplan_url"] = plan["url"]
                plan_details = self._get(
                    self.config["testrail_base_url"] + f"?/api/v2/get_plan/{plan['id']}"
                )
                for entry in plan_details["entries"]:
                    for run in entry["runs"]:
                        if all(
                            elem in run["name"] for elem in testrail_run_consists_of
                        ):
                            passrate_info["passrate"] = math.ceil(
                                100
                                * run["passed_count"]
                                / (run["passed_count"] + run["custom_status1_count"])
                            )
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
