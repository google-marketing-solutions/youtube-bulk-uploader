<!--
Copyright 2024 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

      https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# YouTube Bulk Uploader

Bulk upload videos to YouTube using metadata managed in Google Sheets and video files stored in Google Drive.

This tool allows users to streamline and automate their YouTube video uploads, especially when managing a high volume of content. Metadata is stored in a connected Google Sheet, and videos are pulled directly from a designated Google Drive folder. Uploads are performed via a Python script using the YouTube Data API.

**Disclaimer: This is not an official Google product.**

---

## Features

- ✅ Upload multiple videos to YouTube via a single command
- ✅ Manage video metadata (title, description, tags, etc.) via Google Sheets
- ✅ Organize video files in Google Drive
- ✅ Supports nested folders and dynamic metadata mapping
- ✅ Google Apps Script UI integrated with Sheets to list existing uploads and manage upload queue
- ✅ Uploads videos as **unlisted** by default

---

## How It Works

1. Users drop video files into a predefined Google Drive folder.
2. Google Sheets script lists available files and populates a table for metadata entry.
3. A Python script authenticates with the YouTube Data API and uploads videos using metadata from the Sheet.
4. Uploaded files are moved to an "Uploaded" folder in Drive.

---

## Requirements

### Google Cloud Setup

1. **Create a Google Cloud Project**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Ensure billing is enabled

2. **Enable Required APIs**
   - YouTube Data API v3
   - Google Drive API
   - Google Sheets API
   - Visit: [Enabled APIs](https://console.developers.google.com/apis/enabled)

3. **Configure OAuth Consent Screen**
   - Navigate to "OAuth consent screen" in the Cloud Console
   - Choose **External** user type and set testing mode
   - Add your email to "Test Users"
   - Save and continue

4. **Create OAuth 2.0 Credentials**
   - Go to [Credentials](https://console.developers.google.com/apis/credentials)
   - Click "+ Create Credentials" → OAuth 2.0 Client ID
   - Application type: **Web application**
   - Name: `YouTube Uploader Client`
   - **Authorized redirect URI**: `https://developers.google.com/oauthplayground`

5. **Download and Rename the Credential File**
   - Download the generated JSON file
   - Rename it to `yt_credentials.json`
   - Place it in the working directory where the Python script (`main.py`) will run

> ⚠️ This file contains sensitive information. Do not share or expose this file publicly.

---

## Folder and Sheet Structure

### Google Drive

Create the following folders:

- `YouTube Upload` (source folder for videos)
- `YTBU - Completed Uploads` (destination for uploaded files)

### Google Sheets

Make a copy of this template: [YouTube Bulk Uploader - Distributable](https://docs.google.com/spreadsheets/d/1C2hdQOw6u8nOY3VxwS8_RmwmQZksqJcKBj4XnAwLjD4/edit)

#### Config Tab

| Field                        | Description                                                      |
|-----------------------------|------------------------------------------------------------------|
| Drive Folder URL            | URL to your `YouTube Upload` folder                              |
| Description Template        | Default video description                                         |
| YouTube Channel ID          | Your YouTube channel ID                                           |
| Drive Root Folder for Files | Google Drive folder ID (used to fetch videos recursively)         |

#### File Upload List
Populated via "Pull Files From Google Drive" menu item

#### Channel Videos List
Populated via "List My Uploads" menu item

---

## Authentication & Installation

### Python (Cloud Shell or Local)

1. Clone the repo:
```bash
git clone https://github.com/google-marketing-solutions/youtube-bulk-uploader.git
cd youtube-bulk-uploader
```

2. Replace `yt_credentials.json` with your downloaded OAuth file from GCP

3. Edit `main.py` and set:
```python
SPREADSHEET_ID = 'your_sheet_id_here'
```

4. Install dependencies:
```bash
pip install --upgrade google-api-python-client google-auth-oauthlib
```

5. Run the tool:
```bash
python main.py
```

6. Follow the prompts to authenticate Google Sheets, Drive, and YouTube access

> Note: First-time users must complete two browser-based OAuth flows. Copy/paste the URL back into the terminal when prompted (ERR_CONNECTION_REFUSED is expected).

---

## Google Apps Script

This script powers the custom menu within the Google Sheet. It pulls files from Drive and lists existing channel uploads.

Deploy the `code.gs` file:
1. Open Extensions → Apps Script in your Google Sheet
2. Paste the contents of `code.gs`
3. Save and reload the sheet

You will now see a new menu: **YouTube Bulk Uploader**

---

## Quota & Limitations

By default, YouTube Data API has a daily quota limit of ~50,000 units (~5-6 videos/day). You can [request a quota increase](https://developers.google.com/youtube/v3/determine_quota_cost) if needed.

---

## Troubleshooting

- ⚠️ `ERR_CONNECTION_REFUSED` during OAuth: This is expected; copy the final browser URL into the terminal.
- ⚠️ Missing credentials: Ensure `yt_credentials.json` is in the working directory.
- ⚠️ Script not working in Google Sheets: Refresh the sheet and ensure the Apps Script is deployed.

---

## License

Apache 2.0

---

## Disclaimer

This is not an officially supported Google product. Use at your own risk.
