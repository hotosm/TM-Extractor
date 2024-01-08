# To be used by main.tf & managed through terragrunt.
# Check 

variable "aws_region" {
  description = "The AWS region to deploy to (e.g. us-east-1)"
  type        = string
  default = "ap-south-1"
}

variable "account_name" {
  type = string
  default = "hotosm"
  description = "AWS Account name, acts as suffix to variour resources"
}

variable "iam_lambda_role_name" {
  description = "The name of the role lambda functions runs as"
  type        = string
}

variable "cw_retention_in_days" {
  description = "Defines number of days cloudwatch logs are retained. Example: 1 or 10 Years"
  type        = string
  default = "14"
}

variable "environment" {
  description = "The Environment lambda functions are deploymed on. Changes the prefix and names of resources. eg: dev, stag, prod"
  type        = string
  default = "dev"
}

variable "lambda_memory_size" {
  description = "Defines the memory size the lambda functions runs on. Default 128 MB"
  type        = string
  default = "128"
}

variable "lambda_timeout" {
  description = "Defines the timeout for the lambda function. Increase if lambda function times out. Default 20 sec."
  type        = string
  default = "20"
}

variable "lambda_cron_expression" {
  description = "Defines the Cron expression for the lambda function to run. Defaults to everyday at 00:00 am"
  type        = string
  default = "cron(0 0 * * ? *)"
}
# To be Exported from environment as TG_active_projects_api_base_url, from circleci or gh actions.
variable "active_projects_api_base_url" {
   description = "Link to your tasking manage project"
   type = string
   default = "https://tasking-manager-staging-api.hotosm.org/api/v2"
}

# To be Exported from environment as TG_rawdata_api_auth_token, from circleci or gh actions.
variable "rawdata_api_auth_token" {
   type = string
   description = "API Token for rawdata api, get your token from https://api-prod.raw-data.hotosm.org/v1"
}

# To be Exported from environment as TG_raw_data_api, from circleci or gh actions.
variable "raw_data_api" {
   type = strings
   description = "Link to raw data api"
   default = "https://api-prod.raw-data.hotosm.org/v1"
}

variable "zip_output_dir" {
   description = "This is a path to temporary folder directory due to TG limitations, check: https://github.com/gruntwork-io/terragrunt/issues/716"
   type = string
   default = "files"
}

variable "config_json" {
   description = "Path to config.json, if the file exits in another directory."
   type = string
   default = "config.json"
}