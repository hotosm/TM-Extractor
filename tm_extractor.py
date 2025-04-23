import argparse
import asyncio
import copy
import json
import logging
import os
from pathlib import Path
from typing import Dict

import aiohttp
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("tm-extractor")

sentry_dsn = os.environ.get("SENTRY_DSN")
if sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=0.1)


REQUIRED_ENV_VARS = {
    "RAWDATA_API_AUTH_TOKEN": "Authentication token for Raw Data API",
}

DEFAULT_ENV_VARS = {
    "CONFIG_JSON": "config.json",
    "RAW_DATA_API_BASE_URL": "https://api-prod.raw-data.hotosm.org/v1",
    "TM_API_BASE_URL": "https://tasking-manager-production-api.hotosm.org/api/v2",
    "API_MAX_RETRIES": "3",
    "API_TIMEOUT": "10",
    "RATE_LIMIT_WAIT": "61",
    "TM_API_TIMEOUT": "20",
    "API_BACKOFF_BASE": "2",
    "TASK_POLL_INTERVAL": "30",
}


class EnvVarError(Exception):
    """Raised when required environment variables are missing."""

    pass


class ApiError(Exception):
    """Raised when API requests fail."""

    pass


class ConfigError(Exception):
    """Raised when configuration is invalid."""

    pass


def validate_environment() -> Dict[str, str]:
    """
    Validate environment variables and return them in a dictionary.
    Raises EnvVarError if required variables are missing.
    """
    env_vars = {}
    missing_vars = []

    for var, description in REQUIRED_ENV_VARS.items():
        value = os.environ.get(var)
        if not value:
            missing_vars.append(f"{var} ({description})")
        else:
            env_vars[var] = value

    for var, default in DEFAULT_ENV_VARS.items():
        env_vars[var] = os.environ.get(var, default)

    if not os.environ.get("TASKING_MANAGER_API_KEY"):
        logger.warning(
            "TASKING_MANAGER_API_KEY not set. Private projects may not be accessible."
        )
    else:
        env_vars["TASKING_MANAGER_API_KEY"] = os.environ.get("TASKING_MANAGER_API_KEY")

    if missing_vars:
        raise EnvVarError(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )

    for var in [
        "API_MAX_RETRIES",
        "API_TIMEOUT",
        "RATE_LIMIT_WAIT",
        "TM_API_TIMEOUT",
        "API_BACKOFF_BASE",
        "TASK_POLL_INTERVAL",
    ]:
        try:
            env_vars[var] = int(env_vars[var])
        except ValueError:
            logger.warning(f"Invalid value for {var}, using default")
            env_vars[var] = int(DEFAULT_ENV_VARS[var])

    return env_vars


class ProjectProcessor:
    MAPPING_TYPES = {
        "ROADS": "Roads",
        "BUILDINGS": "Buildings",
        "WATERWAYS": "Waterways",
        "LAND_USE": "Landuse",
    }

    def __init__(self, config_json=None):
        if config_json is None:
            raise ValueError("Config JSON couldn't be found")

        self.env = validate_environment()

        if isinstance(config_json, dict):
            self.config = config_json
        elif os.path.exists(config_json):
            try:
                with open(config_json) as f:
                    self.config = json.load(f)
            except json.JSONDecodeError:
                raise ValueError(f"Invalid JSON format in {config_json}")
            except IOError as e:
                raise ValueError(f"Error reading config file: {e}")
        else:
            raise ValueError("Invalid value for config_json")

        self.RAW_DATA_API_BASE_URL = self.env["RAW_DATA_API_BASE_URL"]
        self.RAW_DATA_SNAPSHOT_URL = f"{self.RAW_DATA_API_BASE_URL}/custom/snapshot/"
        self.TM_API_BASE_URL = self.env["TM_API_BASE_URL"]

        self.RAWDATA_API_AUTH_TOKEN = self.env["RAWDATA_API_AUTH_TOKEN"]
        self.TASKING_MANAGER_API_KEY = self.env.get("TASKING_MANAGER_API_KEY")

        self.max_retries = self.env["API_MAX_RETRIES"]
        self.api_timeout = self.env["API_TIMEOUT"]
        self.rate_limit_wait = self.env["RATE_LIMIT_WAIT"]
        self.tm_api_timeout = self.env["TM_API_TIMEOUT"]
        self.backoff_base = self.env["API_BACKOFF_BASE"]
        self.task_poll_interval = self.env["TASK_POLL_INTERVAL"]

    def get_mapping_list(self, input_value):
        """Convert input mapping type to standardized format."""
        if isinstance(input_value, int):
            input_value -= 1
            if 0 <= input_value < len(self.MAPPING_TYPES):
                return list(self.MAPPING_TYPES.values())[input_value]
            return None
        elif isinstance(input_value, str):
            return self.MAPPING_TYPES.get(input_value.upper())
        return None

    def generate_filtered_config(self, project_id, mapping_types, geometry):
        """Generate filtered configuration for the API request."""
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

    async def process_project(self, project):
        """Process a project and submit it to the Raw Data API."""
        try:
            geometry = project["geometry"]
            project_id = project["properties"].get("project_id")
            mapping_types = []
            mapping_types_raw = project["properties"].get("mapping_types")

            if mapping_types_raw:
                for item in mapping_types_raw:
                    mapping_type_return = self.get_mapping_list(item)
                    if mapping_type_return is not None:
                        mapping_types.append(mapping_type_return)
                if len(mapping_types) > 0:
                    request_config = self.generate_filtered_config(
                        project_id=project_id,
                        mapping_types=mapping_types,
                        geometry=geometry,
                    )
                    # logger.info(
                    #     "Sending Request to Raw Data API for %s with %s",
                    #     project_id,
                    #     mapping_types,
                    # )
                    response = await self.retry_post_request(request_config)
                    return response

            logger.info(
                "Skipped %s, Mapping type %s not supported yet",
                project_id,
                project["properties"].get("mapping_types"),
            )
            return None
        except Exception as e:
            logger.error(f"Error processing project: {e}")
            return None

    async def retry_post_request(self, request_config, max_retries=3):
        """Make POST request to Raw Data API with retry logic."""
        for attempt in range(max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    headers = {
                        "Content-Type": "application/json",
                        "Access-Token": self.RAWDATA_API_AUTH_TOKEN,
                    }
                    async with session.post(
                        self.RAW_DATA_SNAPSHOT_URL,
                        headers=headers,
                        data=request_config,
                        timeout=self.api_timeout,
                    ) as response:
                        response.raise_for_status()
                        result = await response.json()
                        if "task_id" not in result:
                            logger.error(f"Invalid API response: {result}")
                            return None
                        return result["task_id"]
            except aiohttp.ClientResponseError as e:
                if e.status in [429, 502] and attempt < max_retries:
                    await self.handle_rate_limit()
                else:
                    if attempt == max_retries:
                        logger.error(f"Failed after {max_retries} retries: {e}")
                        return None
            except Exception as e:
                logger.error(f"Request error: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(self.backoff_base**attempt)
                else:
                    return None

    async def handle_rate_limit(self):
        """Handle rate limiting with wait."""
        logger.warning("Rate limit reached. Waiting for 1 minute before retrying.")
        await asyncio.sleep(self.rate_limit_wait)

    async def retry_get_request(self, url):
        """Make GET request with retry logic."""
        for attempt in range(self.max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    headers = {}
                    if (
                        url.startswith(self.TM_API_BASE_URL)
                        and self.TASKING_MANAGER_API_KEY
                    ):
                        headers["Authorization"] = self.TASKING_MANAGER_API_KEY

                    async with session.get(
                        url, headers=headers, timeout=self.api_timeout
                    ) as response:
                        response.raise_for_status()
                        return await response.json()
            except Exception as e:
                logger.warning(
                    f"GET request failed (attempt {attempt + 1}/{self.max_retries}): {e}"
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(self.backoff_base**attempt)
                else:
                    return {"status": "ERROR", "message": str(e)}

    async def track_tasks_status(self, task_ids):
        """Track the status of submitted tasks with progress bar."""
        if not task_ids:
            logger.warning("No tasks to track")
            return

        results = {}
        completed_tasks = 0
        total_tasks = len(task_ids)

        with tqdm(total=total_tasks, desc="Tracking tasks") as pbar:
            for task_id in task_ids:
                status_url = f"{self.RAW_DATA_API_BASE_URL}/tasks/status/{task_id}/"
                response = await self.retry_get_request(status_url)

                if response.get("status") == "SUCCESS":
                    results[task_id] = response.get("result")
                    pbar.update(1)
                    completed_tasks += 1
                    logger.info(
                        f"Task {task_id} completed successfully ({completed_tasks}/{total_tasks})"
                    )

                elif response.get("status") in ["PENDING", "STARTED"]:
                    logger.info(
                        f"Task {task_id} is {response.get('status')}. Waiting for completion..."
                    )

                    waiting_count = 0
                    while True:
                        await asyncio.sleep(self.task_poll_interval)
                        waiting_count += 1

                        if waiting_count % 5 == 0:
                            logger.info(
                                f"Still waiting for task {task_id} (waited {waiting_count * self.task_poll_interval}s)"
                            )

                        response = await self.retry_get_request(status_url)
                        if response.get("status") in ["SUCCESS", "ERROR", "FAILURE"]:
                            results[task_id] = response.get(
                                "result", "No result available"
                            )
                            pbar.update(1)
                            completed_tasks += 1
                            logger.info(
                                f"Task {task_id} is {response.get('status')}, moving to next one "
                                f"({completed_tasks}/{total_tasks})"
                            )
                            break
                else:
                    results[task_id] = (
                        f"FAILURE: {response.get('message', 'Unknown error')}"
                    )
                    pbar.update(1)
                    completed_tasks += 1
                    logger.warning(
                        f"Task {task_id} failed ({completed_tasks}/{total_tasks})"
                    )

        try:
            output_file = Path("result.json")
            with output_file.open("w") as f:
                json.dump(results, f, indent=2)
            logger.info(f"Results saved to {output_file.absolute()}")
        except IOError as e:
            logger.error(f"Failed to write results: {e}")

    async def get_project_details(self, project_id):
        """Get project details from Tasking Manager API."""
        feature = {"type": "Feature", "properties": {}}
        project_api_url = f"{self.TM_API_BASE_URL}/projects/{project_id}/?as_file=false&abbreviated=false"

        for retry in range(self.max_retries):
            try:
                headers = {"accept": "application/json"}
                if self.TASKING_MANAGER_API_KEY:
                    headers["Authorization"] = self.TASKING_MANAGER_API_KEY

                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        project_api_url, headers=headers, timeout=self.tm_api_timeout
                    ) as response:
                        response.raise_for_status()
                        result = await response.json()

                        if not all(
                            key in result for key in ["mappingTypes", "areaOfInterest"]
                        ):
                            logger.warning(
                                f"Missing required fields in project {project_id} response"
                            )
                            continue

                        feature["properties"]["mapping_types"] = result["mappingTypes"]
                        feature["properties"]["project_id"] = project_id
                        feature["geometry"] = result["areaOfInterest"]
                        return feature
            except aiohttp.ClientResponseError as e:
                logger.warning(f"API error for project {project_id}: {e.status}")
                if e.status == 404:
                    break
            except Exception as e:
                logger.warning(f"Error fetching project {project_id}: {e}")

            await asyncio.sleep(self.backoff_base**retry)

        logger.error(
            f"Failed to fetch project details {project_id} after {self.max_retries} retries"
        )
        return None

    async def get_active_projects(self, time_interval):
        """Get active projects from Tasking Manager API."""
        for retry in range(self.max_retries):
            try:
                active_projects_api_url = f"{self.TM_API_BASE_URL}/projects/queries/active/?interval={time_interval}"
                headers = {"accept": "application/json"}
                if self.TASKING_MANAGER_API_KEY:
                    headers["Authorization"] = self.TASKING_MANAGER_API_KEY

                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        active_projects_api_url,
                        headers=headers,
                        timeout=self.api_timeout,
                    ) as response:
                        response.raise_for_status()
                        data = await response.json()

                        if "features" not in data:
                            logger.warning(
                                "Missing 'features' in active projects response"
                            )
                            continue

                        return data["features"]
            except Exception as e:
                logger.warning(
                    f"Request failed (attempt {retry + 1}/{self.max_retries}): {e}"
                )

            await asyncio.sleep(self.backoff_base**retry)

        logger.error(
            f"Failed to fetch active projects after {self.max_retries} retries"
        )
        return None

    async def init_call(self, projects=None, fetch_active_projects=None):
        """Initialize processing of projects."""
        all_project_details = []

        if projects:
            logger.info("%s Tasking manager projects supplied", len(projects))
            for project_id in tqdm(projects, desc="Retrieving project details"):
                project_details = await self.get_project_details(project_id=project_id)
                if project_details:
                    all_project_details.append(project_details)

        if fetch_active_projects is not None:
            interval = fetch_active_projects
            logger.info(f"Retrieving active projects from last {interval} hours")
            active_project_details = await self.get_active_projects(interval)

            if active_project_details:
                logger.info("%s active projects fetched", len(active_project_details))
                all_project_details.extend(active_project_details)
            else:
                logger.warning("No active projects found")

        if not all_project_details:
            logger.warning("No projects to process")
            return []

        logger.info("Started processing %s projects in total", len(all_project_details))
        task_ids = []

        for project in tqdm(all_project_details, desc="Processing projects"):
            task_id = await self.process_project(project)
            if task_id:
                task_ids.append(task_id)

        logger.info(
            "Request: %s requests to Raw Data API have been sent",
            len(task_ids),
        )
        return task_ids


def lambda_handler(event, context):
    """AWS Lambda handler function wrapper (non-async)."""
    return asyncio.run(async_lambda_handler(event, context))


async def async_lambda_handler(event, context):
    """AWS Lambda handler function (async implementation)."""
    try:
        env = validate_environment()
        config_json = env["CONFIG_JSON"]
        projects = event.get("projects")
        fetch_active_projects = event.get("fetch_active_projects", 24)

        project_processor = ProjectProcessor(config_json)
        task_ids = await project_processor.init_call(
            projects=projects, fetch_active_projects=fetch_active_projects
        )

        return {
            "statusCode": 200,
            "body": {
                "message": "Processing complete",
                "tasks_submitted": len(task_ids),
                "task_ids": task_ids,
            },
        }
    except EnvVarError as e:
        logger.error(str(e))
        return {"statusCode": 500, "body": {"error": str(e)}}
    except Exception as e:
        logger.error(f"Error in lambda handler: {e}")
        return {"statusCode": 500, "body": {"error": str(e)}}


def parse_arguments():
    """Parse command-line arguments with improved help text."""
    parser = argparse.ArgumentParser(
        description="Triggers extraction requests for Tasking Manager projects",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--projects",
        "-p",
        nargs="+",
        type=int,
        help="List of project IDs to process (space-separated)",
    )
    group.add_argument(
        "--fetch-active-projects",
        "-a",
        nargs="?",
        const=24,
        type=int,
        metavar="HOURS",
        help="Fetch and process active projects from the last N hours (default: 24)",
    )

    parser.add_argument(
        "--track",
        "-t",
        action="store_true",
        help="Track task status until completion and save results (may take a long time)",
    )

    parser.add_argument(
        "--config",
        "-c",
        default=os.environ.get("CONFIG_JSON", "config.json"),
        help="Path to configuration JSON file",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug logging",
    )

    return parser.parse_args()


def main():
    """Main function to run the script from command line."""
    args = parse_arguments()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")

    if args.config:
        os.environ["CONFIG_JSON"] = args.config

    try:
        validate_environment()
        project_processor = ProjectProcessor(os.environ.get("CONFIG_JSON"))

        task_ids = asyncio.run(
            project_processor.init_call(
                projects=args.projects, fetch_active_projects=args.fetch_active_projects
            )
        )

        if not task_ids:
            logger.warning("No tasks were submitted")
            return

        logger.info(f"Successfully submitted {len(task_ids)} tasks")

        if args.track:
            logger.info("Tracking task status...")
            asyncio.run(project_processor.track_tasks_status(task_ids))

    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    except EnvVarError as e:
        logger.error(str(e))
    except Exception as e:
        logger.error(f"Error: {e}")


if __name__ == "__main__":
    main()
