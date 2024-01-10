import argparse
import copy
import json
import logging
import os
import time

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProjectProcessor:
    MAPPING_TYPES = {
        "ROADS": "Roads",
        "BUILDINGS": "Buildings",
        "WATERWAYS": "Waterways",
        "LAND_USE": "Landuse",
    }

    def __init__(
        self,
        config_json=None,
    ):
        if config_json is None:
            raise ValueError("Config JSON couldn't be found")

        if isinstance(config_json, dict):
            self.config = config_json
        elif os.path.exists(config_json):
            with open(config_json) as f:
                self.config = json.load(f)
        else:
            raise ValueError("Invalid value for config_json")

        self.RAW_DATA_API_BASE_URL = os.environ.get(
            "RAW_DATA_API_BASE_URL", "https://api-prod.raw-data.hotosm.org/v1"
        )
        self.RAW_DATA_SNAPSHOT_URL = f"{self.RAW_DATA_API_BASE_URL}/custom/snapshot/"
        self.TM_API_BASE_URL = os.environ.get(
            "TM_API_BASE_URL",
            "https://tasking-manager-tm4-production-api.hotosm.org/api/v2",
        )
        self.RAWDATA_API_AUTH_TOKEN = os.environ.get("RAWDATA_API_AUTH_TOKEN")

    def get_mapping_list(self, input_value):
        if isinstance(input_value, int):
            input_value -= 1
            if 0 <= input_value < len(self.MAPPING_TYPES):
                return list(self.MAPPING_TYPES.values())[input_value]
            return None
        return self.MAPPING_TYPES.get(input_value.upper())

    def generate_filtered_config(self, project_id, mapping_types, geometry):
        config_temp = copy.deepcopy(self.config)
        config_temp["dataset"]["dataset_prefix"] = f"hotosm_project_{project_id}"
        config_temp["dataset"]["dataset_title"] = f"Tasking Manger Project {project_id}"

        categories_list = config_temp.get("categories", [])

        def extract_values(categories_list, key):
            return next(
                (category[key] for category in categories_list if key in category), None
            )

        extracted_values = {
            key: extract_values(categories_list, key) for key in set(mapping_types)
        }
        modified_categories = [
            {key: value} for key, value in extracted_values.items() if value
        ]

        config_temp.update({"categories": modified_categories, "geometry": geometry})

        return json.dumps(config_temp)

    def process_project(self, project):
        geometry = project["geometry"]
        project_id = project["properties"].get("project_id")

        mapping_types = []
        for item in project["properties"].get("mapping_types"):
            mapping_type_return = self.get_mapping_list(item)
            if mapping_type_return is not None:
                mapping_types.append(mapping_type_return)

        if len(mapping_types) > 0:
            request_config = self.generate_filtered_config(
                project_id=project_id, mapping_types=mapping_types, geometry=geometry
            )
            logging.info(
                "Sending Request to Rawdataapi for %s with %s",
                project_id,
                mapping_types,
            )
            response = self.retry_post_request(request_config)
            return response

        logging.info(
            "Skipped %s , Mapping type %s not supported yet",
            project_id,
            project["properties"].get("mapping_types"),
        )

    def retry_post_request(self, request_config):
        retry_strategy = Retry(
            total=2,  # Number of retries
            status_forcelist=[429, 502],
            allowed_methods=["POST"],
            backoff_factor=1,
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        with requests.Session() as req_session:
            req_session.mount("https://", adapter)
            req_session.mount("http://", adapter)

        try:
            HEADERS = {
                "Content-Type": "application/json",
                "Access-Token": self.RAWDATA_API_AUTH_TOKEN,
            }
            response = req_session.post(
                self.RAW_DATA_SNAPSHOT_URL,
                headers=HEADERS,
                data=request_config,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["task_id"]
        except requests.exceptions.RetryError as e:
            self.handle_rate_limit()
            return self.retry_post_request(request_config)

    def handle_rate_limit(self):
        logging.warning("Rate limit reached. Waiting for 1 minute before retrying.")
        time.sleep(61)

    def retry_get_request(self, url):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error("Error in GET request: %s", str(e))
            return {"status": "ERROR"}

    def track_tasks_status(self, task_ids):
        results = {}

        for task_id in task_ids:
            status_url = f"{self.RAW_DATA_API_BASE_URL}/tasks/status/{task_id}/"
            response = self.retry_get_request(status_url)

            if response["status"] == "SUCCESS":
                results[task_id] = response["result"]
            elif response["status"] in ["PENDING", "STARTED"]:
                while True:
                    response = self.retry_get_request(status_url)
                    if response["status"] in ["SUCCESS", "ERROR", "FAILURE"]:
                        results[task_id] = response["result"]
                        logging.info(
                            "Task %s is %s , Moving to fetch next one",
                            task_id,
                            response["status"],
                        )
                        break
                    logging.warning(
                        "Task %s is %s. Retrying in 30 seconds...",
                        task_id,
                        response["status"],
                    )
                    time.sleep(30)
            else:
                results[task_id] = "FAILURE"
        logging.info("%s tasks stats is fetched, Dumping result", len(results))
        with open("result.json", "w") as f:
            json.dump(results, f, indent=2)
        logging.info("Done ! Find result at result.json")

    def get_project_details(self, project_id):
        feature = {"type": "Feature", "properties": {}}
        project_api_url = f"{self.TM_API_BASE_URL}/projects/{project_id}/?as_file=false&abbreviated=false"

        max_retries = 3
        for retry in range(max_retries):
            try:
                response = requests.get(project_api_url, timeout=20)
                response.raise_for_status()
                result = response.json()

                feature["properties"]["mapping_types"] = result["mappingTypes"]
                feature["properties"]["project_id"] = project_id
                feature["geometry"] = result["areaOfInterest"]
                return feature
            except Exception as e:
                logging.warn(f"Request failed (attempt {retry + 1}/{max_retries}): {e}")
        raise Exception(
            f"Failed to retrieve project details after {max_retries} attempts"
        )

    def get_active_projects(self, time_interval):
        max_retries = 3
        for retry in range(max_retries):
            try:
                active_projects_api_url = f"{self.TM_API_BASE_URL}/projects/queries/active/?interval={time_interval}"
                response = requests.get(active_projects_api_url, timeout=10)
                response.raise_for_status()
                return response.json()["features"]
            except Exception as e:
                logging.warn(
                    f" : Request failed (attempt {retry + 1}/{max_retries}): {e}"
                )
        raise Exception(f"Failed to fetch active projects {max_retries} attempts")

    def init_call(self, projects=None, fetch_active_projects=None):
        all_project_details = []

        if projects:
            for project_id in projects:
                logger.info("Retrieving TM project %s", project_id)
                all_project_details.append(
                    self.get_project_details(project_id=project_id)
                )

        if fetch_active_projects:
            interval = fetch_active_projects
            logger.info(
                "Retrieving active projects with an interval of the last %s hr",
                interval,
            )
            all_project_details.extend(self.get_active_projects(interval))

        logger.info("Total %s projects fetched", len(all_project_details))
        task_ids = []
        for project in all_project_details:
            task_id = self.process_project(project)
            if task_id is not None:
                task_ids.append(task_id)
        logging.info(
            "Request : All request to Raw Data API has been sent, Logging %s task_ids",
            len(task_ids),
        )
        logging.info(task_ids)
        return task_ids


def lambda_handler(event, context):
    config_json = os.environ.get("CONFIG_JSON", None)
    if config_json is None:
        raise ValueError("Config JSON couldn't be found in env")
    if os.environ.get("RAWDATA_API_AUTH_TOKEN", None) is None:
        raise ValueError("RAWDATA_API_AUTH_TOKEN environment variable not found.")
    projects = event.get("projects", None)
    fetch_active_projects = event.get("fetch_active_projects", 24)

    project_processor = ProjectProcessor(config_json)
    project_processor.init_call(
        projects=projects, fetch_active_projects=fetch_active_projects
    )


def main():
    parser = argparse.ArgumentParser(
        description="Triggers extraction request for tasking manager projects"
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--projects",
        nargs="+",
        type=int,
        help="List of project IDs, add multiples by space",
    )
    group.add_argument(
        "--fetch-active-projects",
        nargs="?",
        const=24,
        type=int,
        metavar="interval",
        help="Fetch active projects with an optional interval (default is 24), unit is in hour",
    )
    parser.add_argument(
        "--track",
        action="store_true",
        default=False,
        help="Track the status of tasks and dumps result, Use it carefully as it waits for all tasks to complete",
    )
    args = parser.parse_args()

    config_json = os.environ.get("CONFIG_JSON", "config.json")
    if os.environ.get("RAWDATA_API_AUTH_TOKEN", None) is None:
        raise ValueError("RAWDATA_API_AUTH_TOKEN environment variable not found.")

    project_processor = ProjectProcessor(config_json)
    task_ids = project_processor.init_call(
        projects=args.projects, fetch_active_projects=args.fetch_active_projects
    )
    if args.track:
        project_processor.track_tasks_status(task_ids)


if __name__ == "__main__":
    main()
