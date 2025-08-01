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
"""Tests a refresh token to ensure it has access to all required APIs."""

# pylint: disable=C0330, g-bad-import-order, g-multiple-import, g-importing-member
import argparse
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly'
]


def main():
  """Builds credentials and tests access to Drive, Sheets, and YouTube."""
  parser = argparse.ArgumentParser(
      description='Test a refresh token for API access.')
  parser.add_argument('client_id', help='Your OAuth 2.0 Client ID.')
  parser.add_argument('client_secret', help='Your OAuth 2.0 Client Secret.')
  parser.add_argument('refresh_token', help='Your OAuth 2.0 Refresh Token.')
  parser.add_argument(
      'spreadsheet_id', help='A valid Google Sheet ID to test against.')
  args = parser.parse_args()

  try:
    creds = Credentials(
        None,
        refresh_token=args.refresh_token,
        token_uri='https://accounts.google.com/o/oauth2/token',
        client_id=args.client_id,
        client_secret=args.client_secret,
        scopes=SCOPES)

    print('Credentials built successfully. Testing API access...\n')

    # Test Google Drive API
    try:
      print('Testing Google Drive API...')
      drive_service = build('drive', 'v3', credentials=creds)
      drive_service.about().get(fields='user').execute()
      print('✅ Google Drive API access: SUCCESS\n')
    except HttpError as e:
      print(f'❌ Google Drive API access: FAILED. Error: {e}\n')

    # Test Google Sheets API
    try:
      print('Testing Google Sheets API...')
      sheets_service = build('sheets', 'v4', credentials=creds)
      sheets_service.spreadsheets().get(
          spreadsheetId=args.spreadsheet_id).execute()
      print('✅ Google Sheets API access: SUCCESS\n')
    except HttpError as e:
      print(f'❌ Google Sheets API access: FAILED. Error: {e}\n')

    # Test YouTube Data API
    try:
      print('Testing YouTube Data API...')
      youtube_service = build('youtube', 'v3', credentials=creds)
      youtube_service.channels().list(part='snippet', mine=True).execute()
      print('✅ YouTube Data API access: SUCCESS\n')
    except HttpError as e:
      print(f'❌ YouTube Data API access: FAILED. Error: {e}\n')

  except Exception as e:
    print(f'An unexpected error occurred: {e}')


if __name__ == '__main__':
  main()
