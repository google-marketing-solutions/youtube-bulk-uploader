# YouTube Bulk Uploader

Bulk upload videos to YouTube using video files stored in Google Drive.

This tool allows users to streamline and automate their YouTube video uploads,
especially when managing a high volume of content.
Videos are pulled directly from a designated Google Drive folder.

## Features

- ✅ **Serverless Architecture**: Runs as a Google Cloud Function, eliminating the need to manage servers.
- ✅ **Automated Triggering**: Uses Cloud Scheduler to run the uploader on a configurable schedule.
- ✅ **Dynamic Configuration**: Settings can be managed via a Google Sheet, environment variables, or passed in an HTTP request, providing flexible configuration options without redeploying.
- ✅ **Resumable Uploads**: Ensures large files can be uploaded reliably, even with network interruptions.
- ✅ **Post-Upload Actions**: Automatically `rename`, `delete`, or `move` files in Google Drive after a successful upload.
- ✅ **Detailed Logging**: Keeps a record of all uploads and actions in a dedicated "Logs" tab in the Google Sheet.
- ✅ **Metadata from Drive**: Automatically uses the video's filename as the title and can pull tags from Drive labels or file properties.

---

## How It Works

1.  **Scheduled Trigger**: A Cloud Scheduler job triggers the `youtube-bulk-uploader` Cloud Function on a defined schedule (e.g., daily).
2.  **Get Configuration**: The function reads its configuration from the HTTP request, a designated Google Sheet, or environment variables, including the Drive folder ID, YouTube channel ID, and post-upload actions.
3.  **Scan for Videos**: The function recursively scans the specified Google Drive folder for video files. To avoid re-uploading, it checks if a video already exists on YouTube. It does this by comparing the video's filename (without the extension) against the list of all video IDs in the target YouTube channel. This works seamlessly with the `rename` post-upload action, which renames uploaded files to their YouTube video ID.
4.  **Process and Upload**: For each new video, the function:
    a. Downloads the video file from Google Drive.
    b. Constructs the video metadata (title, description, tags) based on the file and the settings in the Google Sheet.
    c. Uploads the video to YouTube using the YouTube Data API.
5.  **Post-Upload Action**: After a successful upload, the function performs the configured action on the original file in Google Drive (`rename`, `delete`, or `move`).
6.  **Log Results**: The function logs the details of the upload (including the new YouTube video URL and the post-upload action taken) in the "Logs" tab of the Google Sheet.

---

# Deployment Guide

This guide provides step-by-step instructions for deploying the YouTube Bulk Uploader as a Google Cloud Function.

## Prerequisites

1.  **Google Cloud Project**: You must have a Google Cloud project with billing enabled.
2.  A user with Google account which has access to Google Drive folder (the source) and a YouTube channel (the destination)

- you'll need to generate credentials for that user and save them in Cloud Secret Manager (they will be used the Cloud Function)

To run installation scripts we'll need:

1.  **gcloud CLI**: Ensure the [Google Cloud CLI](https://cloud.google.com/sdk/install) is installed and authenticated.
2.  **Python 3**: Python 3.8 or higher is required to run the helper script.

> The easiest way to run all scripts is using Google Cloud Shell environment.

## Deployment Steps

### Google Cloud Setup

You might need to create a new Google Cloud project if you don't have one:

- Go to [Google Cloud Console](https://console.cloud.google.com/)
- Ensure billing is enabled
- Configure OAuth Consent Screen:
  - Navigate to "OAuth consent screen" in the Cloud Console
  - Choose **External** user type
  - Save and continue

**Create OAuth 2.0 Credentials**

For automated processing you'll need to provide user credentials
under which the tool will access all APIs.
Ultimately you need a client id, client secret and refresh token.
For generating a refresh token you need to create an OAuth client.
It can be either a Web-type or Desktop-type.

To do authentication and get a refresh token you can use the `get_refresh_token.py` script,
or [OAuth Playground](https://developers.google.com/oauthplayground).

In either case we need to create an oauth client:

- Go to [Credentials](https://console.developers.google.com/apis/credentials)
- Click "+ Create Credentials" → OAuth 2.0 Client ID
- Application type: **Desktop application**
- Name: `YouTube Uploader Client` (not important)
- Download OAuth client json file locally (important: if you close the dialog you won't be able to download the file later!)

If you're going to use OAuth Playground then create a client with 'Web application' type
and add the url `https://developers.google.com/oauthplayground` to 'Authorized redirect URI'.
While use OAuth Playground you'll need to provide required by the tool authentication scopes
(see inside `get_refresh_token.py` for actual list):

- 'https://www.googleapis.com/auth/drive'
- 'https://www.googleapis.com/auth/spreadsheets'
- 'https://www.googleapis.com/auth/youtube.upload'
- 'https://www.googleapis.com/auth/youtube.readonly'

### Generate a Refresh Token

The Cloud Function needs a refresh token to authenticate with Google APIs on your behalf.
Run the following command, passing the path to your credentials file
(downloaded after creation of an oauth client):

```bash
python ../get_refresh_token.py <client_secret_xxx.json.json>
```

NOTE: you might need to install `google-auth-oauthlib` library used by the script first:

```bash
pip install google-auth-oauthlib
```

The script will detect the type of credentials you are using:

- **If you are using "Desktop" credentials (Recommended)**: The script will automatically open your browser for you to approve the permissions.
  The process will complete automatically.
- **If you are using "Web" credentials**: The script will print a URL. You must copy this URL into your browser, approve the permissions,
  and then copy the final URL from your browser's address bar back into the terminal.

For the best experience, it is highly recommended to create and use **Desktop** type OAuth credentials.

**Important**: Store this refresh token in a secure location. You will need it in the next step.

### Enable Google Cloud APIs

Run the following command to enable all the necessary APIs in your Google Cloud project:

```bash
./setup.sh enable_apis
```

### Create Secrets in Secret Manager

The `get_refresh_token.py` script on completion shows the exact commands required to store the necessary credentials in Secret Manager.
Using the Secret Manager is optional but the default approach.
Alternatively you can pass credentials directly via parameters to the Function.
To disable Secret Manager change the `use-secret-manager` setting in `settings.ini` to false:

```
use-secret-manager = false
```

To put credentials to Secret Manager simply take commands printed by `get_refresh_token.py`.
For the reference, or if you didn't use the script, they are:

```bash
# Store the client ID
./setup.sh create_secret --secret ytbu-client-id --value "12345..."

# Store the client secret
./setup.sh create_secret --secret ytbu-client-secret --value "GOCSPX-..."

# Store the refresh token
./setup.sh create_secret --secret ytbu-refresh-token --value "1//..."
```

Those ytbu-\* secrets are mapped to environment variables for the Function on its deployment (see below).

### User settings

You need to decide where you want to keep settings for the CLoud Function.
There are several ways:

- Spreadsheet
- Function's environment variables
- Request parameters for Function - passed as Scheduler Job's arguments

If you want to manage settings in Google Sheets make a copy of this template:
[YouTube Bulk Uploader](https://docs.google.com/spreadsheets/d/1b_F-beNSvJbaY65vraiOgBS3SmiiRmkVTyF1jZvGb_A/edit?usp=sharing)
(under the same user that created credentials).

Then set the spreadsheet id (the new one, after copying) in `gcp/settings.ini` as value for `spreadsheet-id` (section `envvars`).

If you want to manage settings in environment variables or the Job's parameters, you can define them in `settings.ini` under the `[envvars]` and `[arguments]` sections, respectively.

- **[envvars]**: Settings in this section will be passed as environment variables to the Cloud Function.
- **[arguments]**: Settings in this section will be passed as a JSON payload in the request body of the Cloud Scheduler job.

For both sections the format of setting names is the same: snake-case.

The script automatically converts the setting names to the correct format for each context:

- **Sheets**: `Drive Root Folder Id`
- **settings.ini**: `drive-root-folder-id`
- **Environment Variable**: `DRIVE_ROOT_FOLDER_ID`
- **Job's Argument (JSON key)**: `drive_root_folder_id`

#### The full list of user settings:

- **Drive Root Folder Id**: The ID of the Google Drive folder where your videos are stored.
- **YouTube Channel Id**: The ID of the YouTube channel you want to upload to. If left blank, the function will upload to the default channel of the authenticated user.
- **Post Upload Action**: Set this to one of three options: `rename` (default), `delete`, or `move`.
- **Completed Folder Id**: If you chose `move` as the post-upload action, you must provide the ID of the Google Drive folder where you want to move the completed files.
- **Default Video Description**: A default description to use for videos.
- **Fetch Labels**: Set to `TRUE` to fetch and use Drive labels as video tags.

### Configure `settings.ini` (optional)

Beside user settings in `settings.ini` we can provide some environment related settings:

- `common.region`: region to deploy the Function to
- `functions.memory`: the memory size for the Cloud Function
- `functions.service-account`: The email address of the service account you want to use to run the Cloud Function.
  By default the default compute service account is used. Keep it commented out if not needed.
- `functions.use-secret-manager`: true to use secret manager (i.e. map secrets from SM to environment variables)
- `scheduler.schedule`: a cron expression for scheduling a Scheduler Job (which will be triggering the Function) (e.g. `0 1 * * *` run daily on 1am)
- `scheduler.schedule-timezone`: a timezone for time to run the job (e.g. 'Etc/UTC')

Example:

```
[common]
region = europe-west1

[functions]
memory = 512MB

[scheduler]
schedule = 0 1 * * *

[envvars]
;spreadsheet-id =
```

### Deploy the Solution

Run the following command to deploy the entire solution, including the Cloud Function and the Cloud Scheduler job that triggers it:

```bash
./setup.sh deploy_all
```

This script will:

1.  Set the required IAM permissions for the service account.
2.  Deploy the Cloud Function.
3.  Create a Cloud Scheduler job to run the function on the schedule defined in `settings.ini`.

## Conclusion

Once the deployment is complete, the Cloud Function will automatically run on the schedule you've configured,
check your Google Drive for new videos, and upload them to YouTube.
If you're using a spreadsheet (and provided its id via the envvar) then the Function will add a list of uploaded video
on each run to the Logs sheet.

---

## Troubleshooting

### Testing the Deployed Function

After a successful deployment, you can manually trigger the function to test its full workflow without waiting for the scheduled execution.

Run the following command:

```bash
./test_function.sh
```

This script will securely fetch the function's URL and make an authenticated request to start the process. You can monitor the execution by viewing the logs for the `youtube-bulk-uploader` function in the Google Cloud Console.

### Verifying Your Refresh Token

If you suspect your refresh token does not have the correct permissions for all three required APIs (Drive, Sheets, and YouTube), you can verify it using the `test_token.py` script.

1.  **Find your credentials**: You will need your Client ID, Client Secret, and the Refresh Token you generated.
2.  **Find a Sheet ID**: You will need the ID of any valid Google Sheet in the same account.
3.  **Run the script**: Execute the following command, replacing the placeholders with your values:

    ```bash
    python test_token.py "YOUR_CLIENT_ID" "YOUR_CLIENT_SECRET" "YOUR_REFRESH_TOKEN" "YOUR_SPREADSHEET_ID"
    ```

The script will test each of the three APIs and report whether the access was a SUCCESS or a FAILURE.

---

## Quota & Limitations

By default, YouTube Data API has a daily quota limit of ~50,000 units (~5-6 videos/day). You can [request a quota increase](https://developers.google.com/youtube/v3/determine_quota_cost) if needed.

## The Cloud Function gets the maximum available execution timeout - 60 minutes, so the processing should fit into that time.

## License

Apache 2.0

---

## Disclaimer

This is not an officially supported Google product. Use at your own risk.
