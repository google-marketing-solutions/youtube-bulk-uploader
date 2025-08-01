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
pushd $SCRIPT_PATH > /dev/null

REGION=$(git config -f $SETTING_FILE common.region || echo "europe-west1")
FUNCTION_NAME="youtube-bulk-uploader"

echo -e "${CYAN}Fetching URL for Cloud Function '${FUNCTION_NAME}' in region '${REGION}'...${NC}"
FUNCTION_URL=$(gcloud functions describe ${FUNCTION_NAME} --region=${REGION} --gen2 --format="value(serviceConfig.uri)")

if [[ -z "$FUNCTION_URL" ]]; then
  echo -e "${RED}Error: Could not retrieve the function URL. Please ensure the function is deployed correctly.${NC}"
  popd > /dev/null
  exit 1
fi

echo -e "${CYAN}Function URL: ${FUNCTION_URL}${NC}"
echo -e "${CYAN}Invoking function via authenticated POST request...${NC}"

curl -m 300 -X POST "${FUNCTION_URL}" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d "{}"

echo -e "\n\n${CYAN}Function invocation complete. Check the Cloud Function logs for execution details.${NC}"

popd > /dev/null