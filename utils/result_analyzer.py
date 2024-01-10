import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta


def convert_elapsed_time_to_seconds(elapsed_time_str):
    time_unit_mapping = {
        "second": 1,
        "minute": 60,
        "hour": 3600,
        "day": 86400,
    }

    match = re.match(r"(?:(\d+) (\w+)|an? (\w+))", elapsed_time_str)
    if match:
        groups = match.groups()
        if groups[0] is not None:
            # Case: "2 minutes", "3 seconds", etc.
            value, unit = int(groups[0]), groups[1]
        else:
            # Case: "a minute", "an hour", etc.
            value, unit = 1, groups[2]

        # Convert to seconds using the mapping
        return value * time_unit_mapping.get(unit, 1)
    return 0


def process_json(json_data):
    dataset_counts = defaultdict(int)
    total_datasets = 0
    total_resources = 0
    successful_tasks = 0
    failed_tasks = 0

    start_times = []
    end_times = []

    for task_id, task_info in json_data.items():
        if isinstance(task_info, str) and task_info.upper() == "FAILURE":
            failed_tasks += 1
            continue

        successful_tasks += 1

        started_at = datetime.fromisoformat(task_info["started_at"])

        start_times.append(started_at)
        elapsed_time = timedelta(
            seconds=convert_elapsed_time_to_seconds(task_info["elapsed_time"])
        )
        ended_at = started_at + elapsed_time
        end_times.append(ended_at)
        datasets = task_info["datasets"]
        total_datasets += len(datasets)
        for dataset in datasets:
            for dataset_name, resources in dataset.items():
                total_resources += len(resources["resources"])
                dataset_counts[dataset_name] += len(resources["resources"])

    total_elapsed_time = max(end_times) - min(start_times)

    return {
        "total_tasks": len(json_data),
        "successful_tasks": successful_tasks,
        "failed_tasks": failed_tasks,
        "total_datasets": total_datasets,
        "total_resources": total_resources,
        "total_elapsed_time": str(total_elapsed_time),
        "dataset_counts": dict(dataset_counts),
    }


def analyze_json(file_path):
    try:
        with open(file_path, "r") as file:
            json_data = json.load(file)
    except FileNotFoundError:
        print(f"File not found: {file_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from file: {e}")
        sys.exit(1)
    return process_json(json_data)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python result_analyzer.py <file_path>")
        sys.exit(1)

    file_path = sys.argv[1]
    result = analyze_json(file_path)
    print(result)
