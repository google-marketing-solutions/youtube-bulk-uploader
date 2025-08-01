#!/bin/bash
#
# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#------------------------------------------------------------------------------
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

SETTING_FILE="./settings.ini"
SCRIPT_PATH=$(readlink -f "$0" | xargs dirname)
SETTING_FILE="${SCRIPT_PATH}/settings.ini"

# changing the cwd to the script's containing folder so all paths inside can be local to it
# (important as the script can be called via absolute path and as a nested path)
pushd $SCRIPT_PATH > /dev/null

args=()
started=0
# pack all arguments into args array (except --settings)
for ((i=1; i<=$#; i++)); do
  if [[ ${!i} == --* ]]; then started=1; fi
  if [ ${!i} = "--settings" ]; then
    ((i++))
    SETTING_FILE=${!i}
  elif [ $started = 1 ]; then
    args+=("${!i}")
  fi
done
echo "Using settings from $SETTING_FILE"

PROJECT_ID=$(gcloud config get-value project 2> /dev/null)
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="csv(projectNumber)" | tail -n 1)
REGION=$(git config -f $SETTING_FILE common.region || echo "europe-west1")
SERVICE_ACCOUNT=$(git config -f $SETTING_FILE functions.service-account || echo $PROJECT_NUMBER-compute@developer.gserviceaccount.com)
echo $SERVICE_ACCOUNT
JOB_NAME="youtube-bulk-uploader"

enable_apis() {
  gcloud services enable secretmanager.googleapis.com
  gcloud services enable artifactregistry.googleapis.com # required for Gen2 GCF
  gcloud services enable run.googleapis.com # required for Gen2 GCF
  gcloud services enable cloudfunctions.googleapis.com
  gcloud services enable cloudscheduler.googleapis.com
  gcloud services enable drive.googleapis.com
  gcloud services enable youtube.googleapis.com
  gcloud services enable sheets.googleapis.com
}


set_iam_permissions() {
  echo -e "${CYAN}Setting up IAM permissions...${NC}"
  declare -ar ROLES=(
    # For deploying Gen2 CF 'artifactregistry.repositories.list' and 'artifactregistry.repositories.get' permissions are required
    roles/artifactregistry.repoAdmin
    roles/iam.serviceAccountUser
    roles/secretmanager.secretAccessor
    roles/cloudfunctions.admin
    roles/cloudscheduler.admin
  )
  for role in "${ROLES[@]}"
  do
    gcloud projects add-iam-policy-binding $PROJECT_ID \
      --member=serviceAccount:$SERVICE_ACCOUNT \
      --role=$role \
      --condition=None
  done
}


create_secret() {
  local SECRET_NAME
  SECRET_NAME=$(_get_arg_value "--secret" "$@")
  local SECRET_VALUE
  SECRET_VALUE=$(_get_arg_value "--value" "$@")
  if [[ ! -n $SECRET_NAME ]]; then
    echo -e "${RED}Please provide a secret name via --secret argument${NC}"
    return 1
  fi
  if [[ ! -n $SECRET_VALUE ]]; then
    echo -e "${RED}Please provide a secret value via --value argument${NC}"
    return 1
  fi
  if gcloud secrets describe $SECRET_NAME >/dev/null 2>&1; then
      # Secret exists - add new version
      echo -n "$SECRET_VALUE" | gcloud secrets versions add $SECRET_NAME --data-file=-
  else
      # Secret doesn't exist - create new
      echo -n "$SECRET_VALUE" | gcloud secrets create $SECRET_NAME --data-file=-
  fi
}


_get_env_vars_from_settings() {
  local set_env_vars
  set_env_vars="--set-env-vars="
  local first_var=true
  # Read all keys from the [envvars] section
  for key in $(git config -f $SETTING_FILE --name-only --get-regexp "envvars\..*"); do
    local value
    value=$(git config -f $SETTING_FILE --get "$key")
    # Remove the 'envvars.' prefix
    local env_var_name
    env_var_name=$(echo "$key" | sed 's/envvars\.//')
    # Convert to uppercase and replace hyphens with underscores
    env_var_name=$(echo "$env_var_name" | tr '[:lower:]-' '[:upper:]_')

    if [ "$first_var" = true ]; then
      set_env_vars="$set_env_vars$env_var_name=$value"
      first_var=false
    else
      set_env_vars="$set_env_vars,$env_var_name=$value"
    fi
  done
  echo "$set_env_vars"
}


deploy_functions() {
  CF_MEMORY=$(git config -f $SETTING_FILE functions.memory || echo '512MB')
  if [[ -n $CF_MEMORY ]]; then
    CF_MEMORY="--memory=$CF_MEMORY"
  fi

  local set_secrets
  set_secrets=$(git config -f $SETTING_FILE functions.use-secret-manager || echo false)
  if [[ "$set_secrets" == "true" ]]; then
    set_secrets="--set-secrets=CLIENT_ID=ytbu-client-id:latest,CLIENT_SECRET=ytbu-client-secret:latest,REFRESH_TOKEN=ytbu-refresh-token:latest"
  else
    set_secrets=""
  fi

  local set_env_vars
  set_env_vars=$(_get_env_vars_from_settings)
  if [[ "$set_env_vars" == "--set-env-vars=" ]]; then
    set_env_vars="--clear-env-vars"
  fi

  local trigger_flags
  local timeout
  trigger_flags="--trigger-http --no-allow-unauthenticated"
  timeout="--timeout=3600s"
  set -e
  set -x
  gcloud functions deploy youtube-bulk-uploader \
      $trigger_flags \
      --entry-point=main \
      --runtime=python311 \
      $timeout \
      $CF_MEMORY \
      --region=$REGION \
      --quiet \
      --gen2 \
      $set_secrets \
      $set_env_vars \
      --source=./gcp/
  return $?
}


_get_json_from_arguments() {
  local json_body
  json_body="{"
  local first_var=true
  # Read all keys from the [arguments] section
  for key in $(git config -f $SETTING_FILE --name-only --get-regexp "arguments\..*"); do
    local value
    value=$(git config -f $SETTING_FILE --get "$key")
    # Remove the 'arguments.' prefix
    local json_key
    json_key=$(echo "$key" | sed 's/arguments\.//')
    # Convert to lowercase and replace hyphens with underscores
    json_key=$(echo "$json_key" | tr '[:upper:]-' '[:lower:]_')

    if [ "$first_var" = true ]; then
      json_body="$json_body\"$json_key\": \"$value\""
      first_var=false
    else
      json_body="$json_body, \"$json_key\": \"$value\""
    fi
  done
  json_body="$json_body}"
  echo "$json_body"
}


schedule_job() {
  FUNCTION_URL=$(gcloud functions describe youtube-bulk-uploader --region=$REGION --gen2 --format="value(serviceConfig.uri)")
  SCHEDULE_CRON=$(git config -f $SETTING_FILE scheduler.schedule || echo "0 1 * * *") # Default: 1 AM daily
  SCHEDULE_TZ=$(git config -f $SETTING_FILE scheduler.schedule-timezone|| echo "Etc/UTC")

  JOB_EXISTS=$(gcloud scheduler jobs list --location=$REGION --format="value(ID)" --filter="ID:'$JOB_NAME'")
  if [[ -n $JOB_EXISTS ]]; then
    gcloud scheduler jobs delete $JOB_NAME --location $REGION --quiet
  fi
  local gcloud_command
  gcloud_command=(gcloud scheduler jobs create http "$JOB_NAME"
    --schedule="$SCHEDULE_CRON"
    --time-zone="$SCHEDULE_TZ"
    --uri="$FUNCTION_URL"
    --http-method=POST
    --location="$REGION"
    --oidc-service-account-email="$SERVICE_ACCOUNT"
  )

  json_body=$(_get_json_from_arguments)
  if [[ "$json_body" != "{}" ]]; then
    escaped_json_body="$(echo "$json_body" | sed 's/"/\\"/g')"
    gcloud_command+=(--message-body="{\"argument\": \"$escaped_json_body\"}")
  fi

  "${gcloud_command[@]}"
  return $?
}


run_job() {
  gcloud scheduler jobs run $JOB_NAME --location=$REGION
}


deploy_all() {
#  enable_apis || return $?
#  set_iam_permissions $@ || return $?
  deploy_functions $@ || return $?
  schedule_job $@ || return $?
}


_get_arg_value() {
  local arg_name=$1
  shift
  for ((i=1; i<=$#; i++)); do
    if [ ${!i} = "$arg_name" ]; then
      # Check if this is the last argument or if next argument starts with - or --
      ((next=i+1))
      if [ $next -gt $# ] || [[ "${!next}" == -* ]]; then
        # This is a flag without value
        echo "true"
        return 0
      else
        # This is a value argument
        echo ${!next}
        return 0
      fi
    fi
  done
  return 1
}


_list_functions() {
  # list all functions in this file not starting with "_"
  declare -F | awk '{print $3}' | grep -v "^_"
}


if [[ $# -eq 0 ]]; then
  echo "USAGE: $0 target1 target2 ... [--settings /path/to/settings.ini]"
  echo "  where supported targets:"
  _list_functions
else
  for i in "$@"; do
    if [[ $i == --* ]]; then
      break
    fi
    if declare -F "$i" > /dev/null; then
      "$i" ${args[@]}
      exitcode=$?
      if [ $exitcode -ne 0 ]; then
        echo -e "${RED}Breaking script as command '$i' failed${NC}"
        exit $exitcode
      fi
    else
      echo -e "${RED}Function '$i' does not exist.${NC}"
      exit -1
    fi
  done
fi

popd > /dev/null