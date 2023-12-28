# TM Extractor

The **TM Extractor** script is designed to trigger extraction requests for Tasking Manager projects. It utilizes the HotOSM Tasking Manager API and the Raw Data API for data extraction.

## Table of Contents
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Usage](#usage)
  - [Command Line](#command-line)
  - [AWS Lambda](#aws-lambda)
- [Configuration](#configuration)
  - [Environment Variables](#environment-variables)
  - [Config JSON](#config-json)
- [Script Overview](#script-overview)


## Getting Started

### Prerequisites

- Python 3.x
- pip (Python package installer)
- Access token for Raw Data API

### Installation
Make sure you have python3 installed on your system
    
- Clone the repository and cd 

```bash
git clone https://github.com/kshitijrajsharma/tm-extractor
cd tm-extractor
```

## Usage

### Command Line

Run the script from the command line with the following options:

```bash
python tm-extractor.py --projects 123 456 789
```

### AWS Lambda

1. **Create an AWS Lambda Function:**

   - In the AWS Management Console, navigate to the Lambda service.
   - Click on "Create function" and choose "Author from scratch."
   - Enter a name for your function and choose an existing role or create a new one with the necessary permissions.

2. **Set Environment Variables:**

   - Add the following environment variables to your Lambda function configuration:

     - `CONFIG_JSON`: Path to the config JSON file. Default is `config.json`.
     - Refer to [Configurations](#configuration) for more env variables

3. **Deploy the Script as a Lambda Function:**

   - Zip the contents of your project, excluding virtual environments and unnecessary files.
   - Upload the zip file to your Lambda function.

4. **Configure Lambda Trigger:**

   - Configure an appropriate event source for your Lambda function. This could be an API Gateway, CloudWatch Event, or another trigger depending on your requirements.

5. **Invoke the Lambda Function:**

   - Trigger the Lambda function manually or wait for the configured event source to invoke it.

   Your Lambda function will execute the script with the provided configurations.

## Configuration

### Environment Variables

Set the following environment variables for proper configuration:

- **`RAWDATA_API_AUTH_TOKEN`**: API token for Raw Data API authentication, Request admins for yours to [RAW DATA API](https://github.com/hotosm/raw-data-api/)

- **`RAW_DATA_API_BASE_URL`**: Base URL for the Raw Data API. Default is `https://api-prod.raw-data.hotosm.org/v1`.

- **`TM_API_BASE_URL`**: Base URL for the Tasking Manager API. Default is `https://tasking-manager-tm4-production-api.hotosm.org/api/v2`.

- **`CONFIG_JSON`**: Path to the config JSON file. Default is `config.json`.

### Config JSON

The `config.json` file contains configuration settings for the extraction process. It includes details about the dataset, categories, and geometry of the extraction area.

```json
{
    "geometry": {...},
    "dataset": {...},
    "categories": [...]
}
```

### Explanation

#### `geometry`
Defines the geographical area for extraction. Typically auto-populated with Tasking Manager (TM) geometry.

#### `queue`
Specifies the Raw Data API queue, often set as "raw_default" for default processing.

#### `dataset`
Contains information about the dataset:
- `dataset_prefix`: Prefix for the dataset name.
- `dataset_folder`: Folder within TM for the dataset.
- `dataset_title`: Title of the Tasking Manager project.

#### `categories`
Array of extraction categories, each represented by a dictionary with:
- `Category Name`: Name of the extraction category (e.g., "Buildings", "Roads").
  - `types`: Types of geometries to extract (e.g., "polygons", "lines", "points").
  - `select`: Attributes to select during extraction (e.g., "name", "highway", "surface").
  - `where`: Conditions for filtering the data during extraction (e.g., filtering by tags).
  - `formats`: File formats for export (e.g., "geojson", "shp", "kml").

Adjust these settings based on your project requirements and the types of features you want to extract.

Refer to the sample [config.json](./config.json) for default config.


## Script Overview

### Purpose
The script is designed to trigger extraction requests for Tasking Manager projects using the Raw Data API. It automates the extraction process based on predefined configurations.

### Features
- Supports both command line and AWS Lambda execution.
- Dynamically fetches project details, including mapping types and geometry, from the Tasking Manager API.
- Configurable extraction settings using a `config.json` file.
