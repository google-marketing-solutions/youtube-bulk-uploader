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
"""Helper script to generate a refresh token."""

# pylint: disable=C0330, g-bad-import-order, g-multiple-import, g-importing-member
import os
from urllib import parse
import argparse
import json

import google_auth_oauthlib.flow

# This scope allows the application to access and manage files in Google Drive,
# read and write to Google Sheets, and upload videos to YouTube.
SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly'
]


def main():
  """Runs the authorization flow and prints the refresh token."""
  parser = argparse.ArgumentParser(
      description='Generate a refresh token for the YouTube Bulk Uploader.')
  parser.add_argument(
      'client_secrets_file', help='Path to the OAuth 2.0 client secrets file.')
  args = parser.parse_args()

  if not os.path.exists(args.client_secrets_file):
    print(
        f"Error: The credentials file ('{args.client_secrets_file}') was not found."
    )
    return

  # Determine the flow type based on the client secrets file
  with open(args.client_secrets_file, 'r') as f:
    client_config = json.load(f)

  flow_type = 'installed' if 'installed' in client_config else 'web'

  if flow_type == 'installed':
    print("Detected 'Desktop' credentials. Using local server flow.")
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        args.client_secrets_file, scopes=SCOPES)
    creds = flow.run_local_server(port=0)
  else:
    print("Detected 'Web' credentials. Using manual copy/paste flow.")
    print("For a better experience, consider creating 'Desktop' credentials.")
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        args.client_secrets_file, scopes=SCOPES)
    flow.redirect_uri = 'https://developers.google.com/oauthplayground'
    authorization_url, _ = flow.authorization_url(
        access_type='offline', include_granted_scopes='true', prompt='consent')

    print('-----------------------------------------------------------')
    print('Authentication:')
    print('-----------------------------------------------------------')
    print('Click on the following URL and login with your Google account:\n'
          f'{authorization_url}\n')
    print('-----------------------------------------------------------')
    print(
        'After approving, you will be redirected to the "Google OAuth 2.0 Playground".'
    )
    print(
        'Do NOT use the UI in the browser. Instead, copy the FULL URL from your'
    )
    print(
        'browser\'s address bar (it will start with "https://developers.google.com/oauthplayground...")'
    )
    print('and paste it here:')
    url = input('URL: ').strip()
    code = parse.parse_qs(parse.urlparse(url).query)['code'][0]
    os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
    flow.fetch_token(code=code)
    creds = flow.credentials

  print('-----------------------------------------------------------')
  print('SUCCESS!')
  print('-----------------------------------------------------------')
  print(f'Your credentials have been generated: {creds.refresh_token}\n')
  print('To put them into Secret Manager execute the following commands:\n')

  print('# Store the client ID')
  print(
      f'./setup.sh create_secret --secret ytbu-client-id --value "{creds.client_id}"\n'
  )

  print('# Store the client secret')
  print(
      f'./setup.sh create_secret --secret ytbu-client-secret --value "{creds.client_secret}"\n'
  )

  print('# Store the refresh token')
  print(
      f'./setup.sh create_secret --secret ytbu-refresh-token --value "{creds.refresh_token}"\n'
  )

  print('-----------------------------------------------------------')


if __name__ == '__main__':
  main()
