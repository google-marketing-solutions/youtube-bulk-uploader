import argparse
import sys
import os
import pickle
import time
import io
import shutil
from datetime import datetime
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from urllib import parse
import google.oauth2.credentials

from apiclient.http import MediaFileUpload, MediaInMemoryUpload

SPREADSHEET_ID = '' #Insert your spreadsheet ID here e.g. 1n9O8L-wGL3E9BSDTRRhr87voNw9tNcHmGYE-Xq3259E
CREDENTIALS_JSON_FILE_NAME = 'yt_credentials.json'
CONFIG_RANGE = 'Config!A1:B3'
UPLOAD_LIST_RANGE = 'File Upload List!A2:F101' #Max 100 uploads at a time
UPDATE_RANGE = 'File Upload List!G2:G101'
SERVICE_PARAMS = {
    'Drive': {
        'serviceName': 'drive',
        'serviceVersion': 'v3'
    },
    'YouTube': {
        'serviceName': 'youtube',
        'serviceVersion': 'v3'
    },
    'Sheets': {
        'serviceName': 'sheets',
        'serviceVersion': 'v4'
    }
}
SCOPES = ["https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/spreadsheets"]


def main():
    print('____YOUTUBE UPLOAD SCRIPT STARTING_____')
    creds = get_credentials()
    sheets_service = get_service("Sheets", creds)
    drive_service = get_service("Drive", creds)
    youtube_service = get_service("YouTube", creds)

    default_video_description = ""
    
    # Call the Sheets API for config
    request_body = {'spreadsheetId': SPREADSHEET_ID, 'range': CONFIG_RANGE}
    request = sheets_service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=CONFIG_RANGE)
    sheets_response = request.execute()

    for value in sheets_response['values']:
        if str(value[0]) == "Description Template":
          default_video_description = str(value[1])

    # Call the Sheets API for file list
    request_body = {'spreadsheetId': SPREADSHEET_ID, 'range': UPLOAD_LIST_RANGE}
    request = sheets_service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=UPLOAD_LIST_RANGE)
    sheets_response = request.execute()

    #Find completed uploads folder
    page_token = None
    completed_uploads_folder_ID = ""
    response = drive_service.files().list(q="mimeType='application/vnd.google-apps.folder' and name='YTBU - Completed Uploads'",
                                            spaces='drive',
                                            fields='nextPageToken, files(id, name)',
                                            pageToken=page_token).execute()
    for file in response.get('files', []):
      completed_uploads_folder_ID = file.get('id')
      page_token = response.get('nextPageToken', None)
      if page_token is None:
        break

    print("completed_uploads_folder_ID = " + completed_uploads_folder_ID)
    newFolderID = create_new_completed_videos_folder(drive_service, completed_uploads_folder_ID)

    '''
    Below are the columns in the Station Extract Sheet
    value[0] -> File Name   
    value[1] -> File ID    
    value[2] -> Title   
    value[3] -> Description   
    value[4] -> Tags
    value[5] -> Self Declared Made for Kids
    '''
    values_for_sheet = []
    logCounter = 1
    for value in sheets_response['values']:
        print("Processing line " + str(logCounter) + " / " + str(len(sheets_response['values'])) + " for file name " + str(value[0]) + " and file ID " + str(value[1]) )
        file_name = str(value[0])
        file_ID = str(value[1])
        logCounter = logCounter + 1

        download_file_from_drive(file_ID, file_name, drive_service)

        if len(value) > 2:
          title = str(value[2])
        else:
          title = ""
        
        if len(value) > 3:
          description = str(value[3])
        else:
          description = default_video_description

        if len(value) > 4:
          tags = str(value[4])
        else:
          tags = ""

        if len(value) > 5:
          self_declared_made_for_kids = str(value[5])
        else:
          self_declared_made_for_kids = False

        #If no title is provided, set it to file name
        if title == "":
          title = str(value[0]).replace(".mp4", "")

        body = {
            'snippet':{
                'title': title,
                'description': description,
                'tags': tags
            },
            'status' : {
                'privacyStatus': 'unlisted',
                'selfDeclaredMadeForKids': self_declared_made_for_kids
            }
        }

        print("Starting YouTube Upload")

        media_body=MediaFileUpload(file_name, chunksize=-1, resumable=True)

        # Call the API's videos.insert method to create and upload the video.
        insert_request = youtube_service.videos().insert(
          part=','.join(body.keys()),
          body=body,

          media_body=media_body
          #media_body = MediaInMemoryUpload(blobObj, 'video/mp4', resumable=True)
        )
        
        videoLink = resumable_upload(insert_request)
        values_for_sheet.append([videoLink])

        # Move uploaded file
        # Retrieve the existing parents to remove
        file = drive_service.files().get(fileId=file_ID, fields='parents').execute()
        previous_parents = ",".join(file.get('parents'))

        # Move the file to the Completed Uploads folder
        file = drive_service.files().update(
            fileId=file_ID,
            addParents=newFolderID,
            removeParents=previous_parents,
            fields='id, parents'
        ).execute()

        #delete finished upload
        media_body.stream().close()
        os.remove(file_name) 

        body = {
          'values': values_for_sheet
        }

    result = sheets_service.spreadsheets().values().update(spreadsheetId=SPREADSHEET_ID, range=UPDATE_RANGE, valueInputOption='USER_ENTERED', body=body).execute()


def download_file_from_drive(file_ID, file_name, drive_service):   
    print("Downloading file from Drive - " + file_ID)
    
    request = drive_service.files().get_media(fileId=file_ID)
    #fh = io.BytesIO()
    
    fh = io.FileIO(file_name, mode='wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
        print ("Download %d%%." % int(status.progress() * 100))

    #return fh.read()

def resumable_upload(request):
    response = None
    error = None
    retry = 0
    while response is None:
        try:
            print( 'Uploading file...')
            status, response = request.next_chunk()
            if response is not None:
                # print(response)
                if 'id' in response:
                    print()
                    print( 'Video id "%s" was successfully uploaded.' % response['id'])
                    return f'https://www.youtube.com/watch?v={response["id"]}'
                else:
                    exit('The upload failed with an unexpected response: %s' % response)
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS_CODES:
                error = 'A retriable HTTP error %d occurred:\n%s' % (e.resp.status, e.content)
            else:
                raise
        except RETRIABLE_EXCEPTIONS as e:
            error = 'A retriable error occurred: %s' % e

        if error is not None:
            print( error)
            retry += 1
            if retry > MAX_RETRIES:
                exit('No longer attempting to retry.')

            max_sleep = 2 ** retry
            sleep_seconds = random.random() * max_sleep
            print( 'Sleeping %f seconds and then retrying...' % sleep_seconds)
            time.sleep(sleep_seconds)

def create_new_completed_videos_folder(drive_service, parentID):
  now = datetime.now()
  newFolderName = str(now)

  folder_id = parentID

  file_metadata = {
      'name': newFolderName,
      'parents': [folder_id],
      'mimeType': 'application/vnd.google-apps.folder'
  }
  file = drive_service.files().create(body=file_metadata,
                                      fields='id').execute()
  print ('Completed Folder ID: %s' % file.get('id'))

  return file.get('id')

def get_credentials():
    print("Getting OAuth Credentials")
    creds = None

    # The file credentials.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('credentials.pickel'):
        with open('credentials.pickel', 'rb') as token:
            creds = pickle.load(token)
        # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
                        CREDENTIALS_JSON_FILE_NAME,
                        scopes=SCOPES)
            flow.redirect_uri = 'http://localhost:8080'
            authorization_url, state = flow.authorization_url(
                # Enable offline access so that you can refresh an access token without
                # re-prompting the user for permission. Recommended for web server apps.
                access_type='offline',
                # Enable incremental authorization. Recommended as a best practice.
                include_granted_scopes='true',
                prompt='consent')
            print('\n-----------------------------------------------------------')
            print('Click on the following URL and login with your Google account: \n%s\n' % authorization_url)
            print('-----------------------------------------------------------')
            print('After approving you will ecounter ERR_CONNECTION_REFUSED - This is expected.')
            print('Copy and paste the full URL from your browsers address bar.')
            url = input('URL: ').strip()
            code = parse.parse_qs(parse.urlparse(url).query)['code'][0]
            os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
            flow.fetch_token(code=code)
            creds = flow.credentials
            # Save the credentials for the next run
            with open('credentials.pickel', 'wb') as token:
                pickle.dump(creds, token)
    return creds


def get_service(service_type, creds):
  print("Getting " + service_type + " service...")
  newService = None
  keys = SERVICE_PARAMS[service_type]
    
  newService = build(keys['serviceName'], keys['serviceVersion'], credentials=creds)
  return newService

if __name__ == "__main__":
    main()