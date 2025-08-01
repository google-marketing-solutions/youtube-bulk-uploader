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
import time
import io
import random
import json
import functions_framework
from dataclasses import dataclass, asdict
from datetime import datetime
from google.cloud import logging as cloud_logging
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build
import logging

CONFIG_RANGE = 'Config!A:B'
SERVICE_PARAMS = {
    'Drive': {
        'serviceName': 'drive',
        'serviceVersion': 'v3'
    },
    'Sheets': {
        'serviceName': 'sheets',
        'serviceVersion': 'v4'
    },
    'DriveLabels': {
        'serviceName': 'drivelabels',
        'serviceVersion': 'v2'
    },
    'YouTube': {
        'serviceName': 'youtube',
        'serviceVersion': 'v3'
    }
}

SCOPES = {
    'Drive and Sheets': [
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/spreadsheets'
    ],
    'YouTube': [
        'https://www.googleapis.com/auth/youtube.upload',
        'https://www.googleapis.com/auth/youtube.readonly'
    ]
}

# Constants for resumable upload
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]
MAX_RETRIES = 10

# suppress excessive logging
logging.getLogger('googleapiclient.discovery').setLevel(logging.WARNING)
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)


@dataclass
class Config:
  """A typed object to hold configuration settings."""
  drive_root_folder_id: str | None = None
  youtube_channel_id: str | None = None
  client_id: str | None = None
  client_secret: str | None = None
  refresh_token: str | None = None
  spreadsheet_id: str | None = None
  fetch_labels: bool = False
  default_video_description: str = ''
  post_upload_action: str = 'rename'
  completed_folder_id: str | None = None


class UploadError(Exception):
  """Custom exception for upload errors."""
  pass


class MaxRetriesExceededError(UploadError):
  """Raised when the maximum number of retries is exceeded."""
  pass


def _get_sheet_config_values(sheets_service, spreadsheet_id) -> dict[str, str]:
  """Gets configuration values from the 'Config' sheet and returns a dict."""
  config_values = {}
  try:
    request = sheets_service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=CONFIG_RANGE)
    response = request.execute()

    for row in response.get('values', []):
      if len(row) > 1:
        key = row[0]
        value = row[1]
        config_values[key] = value
  except HttpError as e:
    logging.warning('Could not read spreadsheet config. Error: %s', e)
  return config_values


def get_credentials(config: Config):
  """Builds the credentials object from a config object."""
  # 1. Add diagnostic checks for environment variables
  if not config.client_id:
    raise ValueError('CLIENT_ID is not set in config.')
  if not config.client_secret:
    raise ValueError('CLIENT_SECRET is not set in config.')
  if not config.refresh_token:
    raise ValueError('REFRESH_TOKEN is not set in config.')

  try:
    # 2. Create and refresh credentials
    creds = Credentials(
        None,
        refresh_token=config.refresh_token,
        token_uri='https://accounts.google.com/o/oauth2/token',
        client_id=config.client_id,
        client_secret=config.client_secret,
        scopes=SCOPES['Drive and Sheets'] + SCOPES['YouTube'])
    creds.refresh(Request())
    return creds
  except Exception as e:
    # 3. Add improved error handling
    logging.error('An error occurred while creating credentials: %s', e)
    raise


def get_service(service_type, creds):
  """Builds a Google API service object."""
  logging.debug('Getting %s service...', service_type)
  keys = SERVICE_PARAMS[service_type]
  service = build(
      keys['serviceName'], keys['serviceVersion'], credentials=creds)
  return service


def initialize_config(request) -> Config:
  """Initializes config from HTTP request, Spreadsheet, or env vars."""
  # Use force=True to ignore content-type, which might be missing from Scheduler
  raw_json = request.get_json(silent=True, force=True) or {}

  # Cloud Scheduler can be inconsistent, sometimes wrapping the payload in an
  # 'argument' field. We handle both cases to make the function robust.
  if 'argument' in raw_json and isinstance(raw_json['argument'], str):
    try:
      # If 'argument' exists and is a string, parse the nested JSON
      request_json = json.loads(raw_json['argument'])
    except json.JSONDecodeError:
      logging.warning('Failed to decode "argument" from scheduler payload.')
      request_json = {}
  else:
    # Otherwise, use the payload as is
    request_json = raw_json
  log_level = request_json.get('log_level') or os.environ.get('LOG_LEVEL')
  if log_level:
    logging.info('Log level set to %s', log_level)
    logging.getLogger().setLevel(log_level)
  logging.debug(request_json)

  # Get primary config values with priority: request > env
  client_id = request_json.get('client_id') or os.environ.get('CLIENT_ID')
  client_secret = request_json.get('client_secret') or os.environ.get(
      'CLIENT_SECRET')
  refresh_token = request_json.get('refresh_token') or os.environ.get(
      'REFRESH_TOKEN')
  spreadsheet_id = request_json.get('spreadsheet_id') or os.environ.get(
      'SPREADSHEET_ID')

  # Load from sheet if possible
  sheet_values = {}
  if spreadsheet_id:
    # We need creds to get sheet values.
    temp_creds_config = Config(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token)
    creds = get_credentials(temp_creds_config)
    sheets_service = get_service('Sheets', creds)
    sheet_values = _get_sheet_config_values(sheets_service, spreadsheet_id)

  # Combine sources with priority: request > sheet > env
  def get_value(key, default=None, type_cast=lambda x: x):
    # HTTP request (lower_case)
    val = request_json.get(key)

    # Spreadsheet (Title Case with spaces)
    if val is None and sheet_values:
      sheet_key = ' '.join(word.title() for word in key.split('_'))
      val = sheet_values.get(sheet_key)

    # Environment variable (UPPER_CASE)
    if val is None:
      env_key = key.upper()
      val = os.environ.get(env_key)

    if val is None:
      return default
    return type_cast(val)

  config_dict = {
      'client_id':
          client_id,
      'client_secret':
          client_secret,
      'refresh_token':
          refresh_token,
      'spreadsheet_id':
          spreadsheet_id,
      'fetch_labels':
          get_value(
              'fetch_labels',
              default=False,
              type_cast=lambda v: str(v).lower() == 'true'),
      'drive_root_folder_id':
          get_value('drive_root_folder_id'),
      'youtube_channel_id':
          get_value('youtube_channel_id'),
      'default_video_description':
          get_value('default_video_description', ''),
      'post_upload_action':
          get_value(
              'post_upload_action', 'rename', type_cast=lambda v: v.lower()),
      'completed_folder_id':
          get_value('completed_folder_id'),
  }

  return Config(**config_dict)


def _ensure_log_sheet_exists(sheets_service, config: Config):
  """Checks if a 'Logs' sheet exists and creates it if it doesn't."""
  if not config.spreadsheet_id:
    logging.warning('No spreadsheet ID configured. Skipping log sheet check.')
    return
  try:
    spreadsheet = sheets_service.spreadsheets().get(
        spreadsheetId=config.spreadsheet_id).execute()
    sheet_titles = [s['properties']['title'] for s in spreadsheet['sheets']]

    if 'Logs' not in sheet_titles:
      logging.info("Creating 'Logs' sheet...")
      body = {
          'requests': [{
              'addSheet': {
                  'properties': {
                      'title': 'Logs',
                      'gridProperties': {
                          'rowCount': 1,
                          'columnCount': 7
                      }
                  }
              }
          }]
      }
      sheets_service.spreadsheets().batchUpdate(
          spreadsheetId=config.spreadsheet_id, body=body).execute()

      # Add headers to the new sheet
      header_body = {
          'values': [[
              'Timestamp', 'Original Filename', 'Drive File ID', 'YouTube ID',
              'YouTube Link', 'Action', 'Additional Info'
          ]]
      }
      sheets_service.spreadsheets().values().update(
          spreadsheetId=config.spreadsheet_id,
          range='Logs!A1',
          valueInputOption='RAW',
          body=header_body).execute()
  except HttpError as e:
    logging.error('An error occurred while ensuring Logs sheet exists: %s', e)


def _append_log_entry(sheets_service, log_entry, config: Config):
  """Appends a new row to the 'Logs' sheet."""
  try:
    body = {'values': [log_entry]}
    sheets_service.spreadsheets().values().append(
        spreadsheetId=config.spreadsheet_id,
        range='Logs!A1',
        valueInputOption='USER_ENTERED',
        insertDataOption='INSERT_ROWS',
        body=body).execute()
  except Exception as e:
    logging.error('An error occurred while appending to the Logs sheet: %s', e)


def _log_upload_to_sheet(sheets_service, config: Config, video_details):
  """Logs the details of a successful upload to the spreadsheet."""
  if not config.spreadsheet_id:
    return

  _ensure_log_sheet_exists(sheets_service, config)
  log_entry = [
      datetime.utcnow().isoformat(), video_details['file_name'],
      video_details['file_id'], video_details['youtube_video_id'],
      f"https://www.youtube.com/watch?v={video_details['youtube_video_id']}",
      video_details['action_details'].get('action'),
      video_details['action_details'].get('info')
  ]
  _append_log_entry(sheets_service, log_entry, config)


def get_youtube_videos(youtube_service, channel_id):
  """Gets a list of all video objects from a YouTube channel."""
  videos = []
  try:
    params = {}
    if channel_id:
      logging.info('Fetching channel details for channel_id: %s', channel_id)
      params['id'] = channel_id
    else:
      logging.info(
          'No channel_id provided, fetching channel for the authenticated user.'
      )
      params['mine'] = True

    request = youtube_service.channels().list(part='contentDetails', **params)
    response = request.execute()

    if not response.get('items'):
      logging.error(
          'Could not find a YouTube channel with the provided criteria.')
      return videos

    uploads_playlist_id = response['items'][0]['contentDetails'][
        'relatedPlaylists']['uploads']
    logging.info('Found uploads playlist ID: %s', uploads_playlist_id)

    next_page_token = None
    while True:
      playlist_request = youtube_service.playlistItems().list(
          part='snippet',
          playlistId=uploads_playlist_id,
          maxResults=50,
          pageToken=next_page_token)
      playlist_response = playlist_request.execute()
      for item in playlist_response.get('items', []):
        videos.append({
            'id': item['snippet']['resourceId']['videoId'],
            'title': item['snippet']['title']
        })
      next_page_token = playlist_response.get('nextPageToken')
      if not next_page_token:
        break
  except HttpError as e:
    logging.error('An error occurred fetching YouTube videos: %s', e)
  return videos


def recursive_drive_search(drive_service, folder_id, label_ids):
  """Recursively finds all video files in a Google Drive folder."""
  videos = []
  page_token = None
  while True:
    response = drive_service.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields='nextPageToken, files(id, name, mimeType, description, properties, labelInfo)',
        includeLabels=','.join(label_ids) if label_ids else None,
        pageToken=page_token).execute()
    for file in response.get('files', []):
      if file.get('mimeType') == 'application/vnd.google-apps.folder':
        videos.extend(
            recursive_drive_search(drive_service, file.get('id'), label_ids))
      elif file.get('mimeType', '').startswith('video/'):
        videos.append(file)
    page_token = response.get('nextPageToken')
    if not page_token:
      break
  return videos


def get_drive_labels(drivelabels_service):
  """Gets all available Drive labels."""
  labels_map = {}
  page_token = None
  while True:
    response = drivelabels_service.labels().list(
        pageSize=100, pageToken=page_token, publishedOnly=True).execute()
    for label in response.get('labels', []):
      labels_map[label['id']] = label['properties']['title']
    page_token = response.get('nextPageToken')
    if not page_token:
      break
  return labels_map


def handle_post_upload_action(drive_service, file_id, original_file_name,
                              youtube_video_id, config: Config):
  """Handles the post-upload action for a file."""
  action = config.post_upload_action
  action_info = ''

  if action == 'rename':
    logging.info('Renaming file %s to %s...', file_id, youtube_video_id)
    original_extension = os.path.splitext(original_file_name)[1]
    new_name = f'{youtube_video_id}{original_extension}'
    try:
      drive_service.files().update(
          fileId=file_id, body={
              'name': new_name
          }).execute()
      logging.info("Successfully renamed file to '%s'.", new_name)
      action_info = f'Renamed to {new_name}'
    except HttpError as e:
      logging.error('An error occurred while renaming file %s: %s', file_id, e)
      action_info = f'Rename failed: {e}'

  elif action == 'delete':
    logging.info('Deleting file %s...', file_id)
    try:
      drive_service.files().delete(fileId=file_id).execute()
      logging.info('Successfully deleted file %s.', file_id)
      action_info = 'File deleted'
    except HttpError as e:
      logging.error('An error occurred while deleting file %s: %s', file_id, e)
      action_info = f'Delete failed: {e}'

  elif action == 'move':
    if not config.completed_folder_id:
      error_msg = 'Error: Post-Upload Action is "move" but "Completed Folder ID" is not set.'
      logging.error(error_msg)
      action_info = error_msg
    else:
      logging.info('Moving file %s to folder %s...', file_id,
                   config.completed_folder_id)
      try:
        file = drive_service.files().get(
            fileId=file_id, fields='parents').execute()
        previous_parents = ','.join(file.get('parents'))

        drive_service.files().update(
            fileId=file_id,
            addParents=config.completed_folder_id,
            removeParents=previous_parents,
            fields='id, parents').execute()
        logging.info('Successfully moved file %s.', file_id)
        action_info = f'Moved to folder {config.completed_folder_id}'
      except HttpError as e:
        logging.error('An error occurred while moving file %s: %s', file_id, e)
        action_info = f'Move failed: {e}'
  else:
    action_info = f"Unknown action '{action}'"
    logging.warning("Unknown Post-Upload Action: '%s'. No action taken.",
                    action)

  return {'action': action, 'info': action_info}


def download_file_from_drive(file_id, file_name, drive_service):
  """Downloads a file from Drive to the local filesystem."""
  logging.info('Downloading file from Drive - %s', file_id)
  request = drive_service.files().get_media(fileId=file_id)
  fh = io.FileIO(file_name, mode='wb')
  downloader = MediaIoBaseDownload(fh, request)
  done = False
  while not done:
    status, done = downloader.next_chunk()
    logging.info('Download %s%%.', int(status.progress() * 100))


def _resumable_upload(request):
  """Executes a resumable upload request, with retries."""
  response = None
  retry = 0
  while response is None:
    try:
      logging.debug('Uploading file...')
      _, response = request.next_chunk()
      if response is not None:
        if 'id' in response:
          logging.info('Video id "%s" was successfully uploaded.',
                       response['id'])
          return response
        else:
          logging.error('The upload failed with an unexpected response: %s',
                        response)
          # Raising an exception is better than returning None
          raise UploadError(f'The upload failed: {response}')
    except HttpError as e:
      # Check if the error is a retriable HttpError
      if isinstance(e,
                    HttpError) and e.resp.status not in RETRIABLE_STATUS_CODES:
        logging.error('A non-retriable HTTP error occurred: %s', e)
        raise

      retry += 1
      if retry > MAX_RETRIES:
        logging.error('Maximum number of retries exceeded.')
        raise MaxRetriesExceededError(
            'Failed to upload file to YouTube - max attempt count was exceeded.'
        ) from e

      # Implement exponential backoff with jitter
      sleep_time = (2**retry) + random.random()
      logging.warning(
          'A retriable error occurred: %s. Retrying in %.2f seconds...', e,
          sleep_time)
      time.sleep(sleep_time)


@functions_framework.http
def main(request):
  """Cloud Function main entry point."""
  logging_client = cloud_logging.Client()
  logging_client.setup_logging()
  logging.info('____YOUTUBE BULK UPLOADER STARTING_____')
  config = initialize_config(request)

  # Log the effective config, redacting sensitive values
  config_to_log = asdict(config)
  config_to_log['client_secret'] = '***HIDDEN***'
  config_to_log['refresh_token'] = '***HIDDEN***'
  logging.info('Effective config: %s', config_to_log)
  creds = get_credentials(config)
  sheets_service = get_service('Sheets', creds)
  drive_service = get_service('Drive', creds)
  youtube_service = get_service('YouTube', creds)
  drivelabels_service = None
  if config.fetch_labels:
    drivelabels_service = get_service('DriveLabels', creds)

  if not config.drive_root_folder_id:
    raise ValueError('Error: "Drive Root Folder Id" setting is not set.')

  # 2. Get all available Drive labels
  drive_labels = {}
  if config.fetch_labels:
    logging.info('Fetching all available Drive labels...')
    drive_labels = get_drive_labels(drivelabels_service)

  # 3. Get existing videos from YouTube
  logging.info('Fetching existing videos from YouTube...')
  youtube_videos = get_youtube_videos(youtube_service,
                                      config.youtube_channel_id)
  youtube_video_ids = {video['id'] for video in youtube_videos}
  logging.info('Found %s videos on YouTube.', len(youtube_video_ids))

  # 4. Get all video files from Google Drive
  logging.info('Scanning Google Drive for video files...')
  drive_videos = recursive_drive_search(drive_service,
                                        config.drive_root_folder_id,
                                        list(drive_labels.keys()))
  logging.info('Found %s video files in Google Drive.', len(drive_videos))
  logging.debug(drive_videos)

  # 5. Determine which videos are new
  videos_to_upload = []
  for video in drive_videos:
    video_name_without_ext = os.path.splitext(video['name'])[0]
    if video_name_without_ext not in youtube_video_ids:
      videos_to_upload.append(video)

  if not videos_to_upload:
    logging.info('No new videos to upload.')
    result = {
        'result': 'No new videos to upload',
        'youtube videos': list(youtube_video_ids),
        'files': list(drive_videos)
    }
    return result, 200

  logging.info('Found %s new videos to upload.', len(videos_to_upload))

  # 6. Process each new video
  for video in videos_to_upload:
    file_id = video['id']
    file_name = video['name']
    title_without_ext = os.path.splitext(file_name)[0]

    logging.info("Processing '%s' (ID: %s)", file_name, file_id)

    # Download the video file from Drive
    download_file_from_drive(file_id, file_name, drive_service)

    # Get metadata or use defaults
    title = title_without_ext
    description = video.get('description') or config.default_video_description
    # Get tags from file properties
    tags_from_properties = list(video.get('properties', {}).keys())

    # Get tags from Drive labels
    tags_from_labels = []
    if config.fetch_labels and 'labelInfo' in video and 'labels' in video[
        'labelInfo']:
      for label in video['labelInfo']['labels']:
        label_id = label['id']
        if label_id in drive_labels:
          tags_from_labels.append(drive_labels[label_id])

    all_tags = tags_from_properties + tags_from_labels
    tags = ','.join(all_tags)
    made_for_kids = video.get('properties', {}).get('madeForKids',
                                                    'FALSE').upper() == 'TRUE'

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags
        },
        'status': {
            'privacyStatus': 'unlisted',
            'selfDeclaredMadeForKids': made_for_kids
        }
    }

    logging.info("Starting YouTube upload for '%s'...", title)
    media_body = MediaFileUpload(file_name, chunksize=-1, resumable=True)

    insert_request = youtube_service.videos().insert(
        part=','.join(body.keys()), body=body, media_body=media_body)

    upload_response = _resumable_upload(insert_request)
    if not upload_response or 'id' not in upload_response:
      logging.error("Upload failed for '%s'. Skipping post-upload action.",
                    title)
      continue

    youtube_video_id = upload_response['id']
    logging.info(
        "Successfully uploaded '%s': https://www.youtube.com/watch?v=%s", title,
        youtube_video_id)

    # Perform post-upload action
    action_details = handle_post_upload_action(drive_service, file_id,
                                               file_name, youtube_video_id,
                                               config)

    # Log the successful upload to the spreadsheet
    _log_upload_to_sheet(
        sheets_service, config, {
            'file_name': file_name,
            'file_id': file_id,
            'youtube_video_id': youtube_video_id,
            'action_details': action_details
        })

    # Clean up the downloaded file
    os.remove(file_name)

  logging.info('All new videos have been processed.')
  result = {
      'result': 'All new videos have been processed',
      'uploaded': list(videos_to_upload),
      'youtube videos': list(youtube_video_ids),
      'files': list(drive_videos)
  }
  return result, 200
