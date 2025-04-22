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
"""Main CLI script."""

# pylint: disable=C0330, g-bad-import-order, g-multiple-import, g-importing-member
import os
import pickle
import time
import io
import random  # Added import
from datetime import datetime
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build
import google_auth_oauthlib.flow
from google.auth.transport.requests import Request
from urllib import parse

SPREADSHEET_ID = ''  # Insert your spreadsheet ID here
CREDENTIALS_JSON_FILE_NAME = 'yt_credentials.json'
CONFIG_RANGE = 'Config!A1:B3'
UPLOAD_LIST_RANGE = 'File Upload List!A2:F101'  # Max 100 uploads at a time
UPDATE_RANGE = 'File Upload List!G2:G101'
SERVICE_PARAMS = {
    'Drive': {
        'serviceName': 'drive',
        'serviceVersion': 'v3'
    },
    'Sheets': {
        'serviceName': 'sheets',
        'serviceVersion': 'v4'
    },
    'YouTube': {
        'serviceName': 'youtube',
        'serviceVersion': 'v3'
    }
}

SCOPES = {
    'Drive and Sheets': [
        'https://www.googleapis.com/auth/drive.file',
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/spreadsheets'
    ],
    'YouTube': ['https://www.googleapis.com/auth/youtube.upload']
}

# Constants for resumable upload
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]
RETRIABLE_EXCEPTIONS = (HttpError,)
MAX_RETRIES = 10


def main():
  print('____YOUTUBE UPLOAD SCRIPT STARTING_____')
  drive_creds = get_credentials('Drive and Sheets')
  youtube_creds = get_credentials('YouTube')
  sheets_service = get_service('Sheets', drive_creds)
  drive_service = get_service('Drive', drive_creds)
  youtube_service = get_service('YouTube', youtube_creds)

  default_video_description = ''

  # Call the Sheets API for config
  request = sheets_service.spreadsheets().values().get(
      spreadsheetId=SPREADSHEET_ID, range=CONFIG_RANGE)  # pylint: disable=no-member
  sheets_response = request.execute()

  for value in sheets_response['values']:
    if str(value[0]) == 'Description Template':
      default_video_description = str(value[1])

  # Call the Sheets API for file list
  request = sheets_service.spreadsheets().values().get(
      spreadsheetId=SPREADSHEET_ID, range=UPLOAD_LIST_RANGE)  # pylint: disable=no-member
  sheets_response = request.execute()

  #Find completed uploads folder
  page_token = None
  completed_uploads_folder_id = ''
  response = drive_service.files().list(
      # pylint: disable=no-member
      q="mimeType='application/vnd.google-apps.folder' "
        "and name='YTBU - Completed Uploads'",
      spaces='drive',
      fields='nextPageToken, files(id, name)',
      pageToken=page_token).execute()
  for file in response.get('files', []):
    completed_uploads_folder_id = file.get('id')
    page_token = response.get('nextPageToken', None)
    if page_token is None:
      break

  print('completed_uploads_folder_id = ' + completed_uploads_folder_id)
  new_folder_id = create_new_completed_videos_folder(drive_service,
                                                   completed_uploads_folder_id)
  # Below are the columns in the Station Extract Sheet:
  # value[0] -> File Name
  # value[1] -> File ID
  # value[2] -> Title
  # value[3] -> Description
  # value[4] -> Tags
  # value[5] -> Self Declared Made for Kids
  values_for_sheet = []
  log_counter = 1
  for value in sheets_response['values']:
    print(f'Processing line {log_counter} / {len(sheets_response['values'])} '
          f'for file name {value[0]} and file ID {value[1]}')
    file_name = str(value[0])
    file_id = str(value[1])
    log_counter = log_counter + 1

    download_file_from_drive(file_id, file_name, drive_service)

    if len(value) > 2:
      title = str(value[2])
    else:
      title = ''

    if len(value) > 3:
      description = str(value[3])
    else:
      description = default_video_description

    if len(value) > 4:
      tags = str(value[4])
    else:
      tags = ''

    if len(value) > 5:
      self_declared_made_for_kids = str(value[5])
    else:
      self_declared_made_for_kids = False

    #If no title is provided, set it to file name
    if not title:
      title = str(value[0]).replace('.mp4', '')

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags
        },
        'status': {
            'privacyStatus': 'unlisted',
            'selfDeclaredMadeForKids': self_declared_made_for_kids
        }
    }

    print('Starting YouTube Upload')

    media_body = MediaFileUpload(file_name, chunksize=-1, resumable=True)

    # Call the API's videos.insert method to create and upload the video.
    insert_request = youtube_service.videos().insert(  # pylint: disable=no-member
        part=','.join(body.keys()),
        body=body,
        media_body=media_body
        #media_body = MediaInMemoryUpload(blobObj, 'video/mp4', resumable=True)
    )

    video_link = resumable_upload(insert_request)
    values_for_sheet.append([video_link])

    # Move uploaded file
    # Retrieve the existing parents to remove
    file = drive_service.files().get(fileId=file_id, fields='parents').execute()  # pylint: disable=no-member
    previous_parents = ','.join(file.get('parents'))

    # Move the file to the Completed Uploads folder
    file = drive_service.files().update(  # pylint: disable=no-member
        fileId=file_id,
        addParents=new_folder_id,
        removeParents=previous_parents,
        fields='id, parents').execute()

    #delete finished upload
    media_body.stream().close()
    os.remove(file_name)

    body = {'values': values_for_sheet}

  sheets_service.spreadsheets().values().update(
      spreadsheetId=SPREADSHEET_ID,
      range=UPDATE_RANGE,
      valueInputOption='USER_ENTERED',
      body=body).execute()  # pylint: disable=no-member


def download_file_from_drive(file_id, file_name, drive_service):
  print('Downloading file from Drive - ' + file_id)

  request = drive_service.files().get_media(fileId=file_id)
  #fh = io.BytesIO()

  fh = io.FileIO(file_name, mode='wb')
  downloader = MediaIoBaseDownload(fh, request)
  done = False
  while done is False:
    status, done = downloader.next_chunk()
    print(f'Download {int(status.progress() * 100)}%.')

  #return fh.read()


def resumable_upload(request):
  response = None
  error = None
  retry = 0
  while response is None:
    try:
      print('Uploading file...')
      _, response = request.next_chunk()
      if response is not None:
        # print(response)
        if 'id' in response:
          print()
          print(f'Video id "{response['id']}" was successfully uploaded.')
          return f'https://www.youtube.com/watch?v={response['id']}'
        else:
          exit('The upload failed with an unexpected response: %s' % response)
    except HttpError as e:
      if e.resp.status in RETRIABLE_STATUS_CODES:
        error = f'A retriable HTTP error {e.resp.status} occurred:\n{e.content}'
      else:
        raise
    except RETRIABLE_EXCEPTIONS as e:
      error = f'A retriable error occurred: {e}'

    if error is not None:
      print(error)
      retry += 1
      if retry > MAX_RETRIES:
        exit('No longer attempting to retry.')

      max_sleep = 2**retry
      sleep_seconds = random.random() * max_sleep
      print(f'Sleeping {sleep_seconds} seconds and then retrying...')
      time.sleep(sleep_seconds)


def create_new_completed_videos_folder(drive_service, parent_id):
  now = datetime.now()
  new_folder_name = str(now)

  folder_id = parent_id

  file_metadata = {
      'name': new_folder_name,
      'parents': [folder_id],
      'mimeType': 'application/vnd.google-apps.folder'
  }
  file = drive_service.files().create(body=file_metadata, fields='id').execute()
  print(f'Completed Folder ID: {file.get('id')}')

  return file.get('id')


def get_credentials(service_name):
  print('Getting OAuth Credentials')
  creds = None

  # The file credentials.pickle stores the user's access and refresh tokens,
  # and is created automatically when the authorization flow completes
  # for the first time.
  pickle_credentials_file_name = service_name.replace(' ',
                                                      '_').lower() + '.pickle'
  scopes = SCOPES[service_name]
  if os.path.exists(pickle_credentials_file_name):
    with open(pickle_credentials_file_name, 'rb') as token:
      creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
  if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
      creds.refresh(Request())
    else:
      flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
          CREDENTIALS_JSON_FILE_NAME, scopes=scopes)
      flow.redirect_uri = 'https://developers.google.com/oauthplayground'
      authorization_url, _ = flow.authorization_url(
          # Enable offline access so that you can refresh an access token
          # without re-prompting the user for permission.
          # Recommended for web server apps
          access_type='offline',
          # Enable incremental authorization. Recommended as a best practice.
          include_granted_scopes='true',
          prompt='consent')
      print('\n-----------------------------------------------------------')
      print(f'{service_name} authentication:')
      print('\n-----------------------------------------------------------')
      print('Click on the following URL and login '
            f'with your Google account: \n{authorization_url}\n')
      print('-----------------------------------------------------------')
      print('After approving you will encounter ERR_CONNECTION_REFUSED'
            ' - This is expected.')
      print('Copy and paste the full URL from your browsers address bar.')
      url = input('URL: ').strip()
      code = parse.parse_qs(parse.urlparse(url).query)['code'][0]
      os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
      flow.fetch_token(code=code)
      creds = flow.credentials
      # Save the credentials for the next run
      with open(pickle_credentials_file_name, 'wb') as token:
        pickle.dump(creds, token)
  return creds


def get_service(service_type, creds):
  print(f'Getting {service_type} service...')
  new_service = None
  keys = SERVICE_PARAMS[service_type]

  new_service = build(
      keys['serviceName'], keys['serviceVersion'], credentials=creds)
  return new_service


if __name__ == '__main__':
  main()
