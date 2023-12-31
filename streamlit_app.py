import json
import os
import webbrowser

import requests
import streamlit as st

from tm_extractor import ProjectProcessor


def generate_auth_token(raw_data_api_base_url):
    auth_login_url = f"{raw_data_api_base_url}/auth/login"
    response = requests.get(auth_login_url)
    response.raise_for_status()
    login_url = response.json().get("login_url")

    if login_url:
        st.success(
            f"Login link generated [here]({login_url}). Please Log in & Copy Your Token"
        )
        webbrowser.open_new_tab(login_url)
    else:
        st.error(
            "Failed to generate login link. Please check the raw data API base URL."
        )


def main():
    st.title("TM Extractor App")

    default_config_path = "config.json"
    default_config_data = None
    if os.path.exists(default_config_path):
        with open(default_config_path, "r") as f:
            try:
                default_config_data = json.load(f)
            except json.JSONDecodeError:
                st.error(
                    "Error loading default config.json. Please provide a valid JSON configuration or URL."
                )
                return

    raw_data_api_base_url = st.text_input(
        "Enter RAW_DATA_API_BASE_URL (default is https://api-prod.raw-data.hotosm.org/v1):",
        "https://api-prod.raw-data.hotosm.org/v1",
    )
    tm_api_base_url = st.text_input(
        "Enter TM_API_BASE_URL (default is https://tasking-manager-tm4-production-api.hotosm.org/api/v2):",
        "https://tasking-manager-tm4-production-api.hotosm.org/api/v2",
    )
    rawdata_api_auth_token = st.text_input(
        "Enter RAWDATA_API_AUTH_TOKEN:", type="password"
    )
    rawdata_auth_link = st.button("Generate Raw Data API Auth Token")
    if rawdata_auth_link:
        generate_auth_token(raw_data_api_base_url)

    config_json_input = st.text_area(
        "Enter JSON configuration or URL:",
        value=json.dumps(default_config_data, indent=2) if default_config_data else "",
    )

    try:
        config_data = json.loads(config_json_input)
    except json.JSONDecodeError:
        try:
            response = requests.get(config_json_input)
            response.raise_for_status()
            config_data = response.json()
        except requests.RequestException:
            st.error(
                "Invalid JSON or URL. Please provide a valid JSON configuration or URL."
            )
            return

    show_config_button = st.button("Show Configuration JSON")
    if show_config_button:
        st.json(config_data)

    project_ids = st.text_input("Enter project IDs (comma-separated):")

    fetch_active_projects = st.checkbox("Fetch active projects")
    interval = None
    if fetch_active_projects:
        interval = st.number_input(
            "Enter interval for fetching active projects (default is 24):", value=24
        )

    track = st.checkbox("Track task status")

    extraction_in_progress = False

    if not extraction_in_progress:
        if st.button("Run Extraction"):
            extraction_in_progress = True
            project_processor = ProjectProcessor(config_data)

            project_processor.RAW_DATA_API_BASE_URL = raw_data_api_base_url
            project_processor.TM_API_BASE_URL = tm_api_base_url
            project_processor.RAWDATA_API_AUTH_TOKEN = rawdata_api_auth_token

            projects_list = None
            if project_ids:
                projects_list = [
                    int(project_id.strip())
                    for project_id in project_ids.split(",")
                    if project_id.strip()
                ]

            task_ids = project_processor.init_call(
                projects=projects_list, fetch_active_projects=interval
            )

            if not project_ids and not fetch_active_projects:
                st.warning(
                    "Please enter project IDs or enable 'Fetch active projects', but not both."
                )

            if track:
                project_processor.track_tasks_status(task_ids)

                result_file_path = os.path.join(os.getcwd(), "result.json")
                if os.path.exists(result_file_path):
                    with open(result_file_path, "r") as result_file:
                        result_data = json.load(result_file)
                    st.subheader("Task Status Results:")
                    st.json(result_data)
                else:
                    st.warning("Result file not found.")
            st.success(f"Extraction Completed. Task IDs: {task_ids}")
            extraction_in_progress = False


if __name__ == "__main__":
    main()
