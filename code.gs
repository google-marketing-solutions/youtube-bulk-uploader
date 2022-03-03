// Note: Apps Script automatically requests authorization
// based on the API's used in the code.

CHANNEL_VIDEOS_SHEET_NAME = "Channel Videos List";
CHANNEL_VIDEOS_SHEET_HEADER = ["Video Title", "Video ID", "Video Description", "Thumbnail", "Video URL"];
FILE_UPLOAD_LIST_SHEET_NAME = "File Upload List";
FILE_UPLOAD_LIST_SHEET_HEADER = ["File Name", "File ID", "Title", "Description", "Tags", "YouTube URL"];
CHANNEL_ID = SpreadsheetApp.getActive().getRange("Config!B4").getValue();

function onOpen() {
  var ui = SpreadsheetApp.getUi();
  ui.createMenu('YouTube Bulk Uploader')
    .addItem('List My Uploads', 'listMyUploads')
    .addSeparator()
    .addItem('Pull Files From Google Drive', 'pullFilesFromRootFolder') // old one: pullDriveFiles
    //.addSeparator()
    //.addItem('Upload To Youtube', 'uploadFiles')
    .addToUi();
}

function listMyUploads() {
  Logger.log("inside listMyUploads")
  var channelID = SpreadsheetApp.getActive().getRange("Config!B3").getValue();
  var sheet = SpreadsheetApp.getActive().getSheetByName(CHANNEL_VIDEOS_SHEET_NAME);
  var valuesForSheet = []; //File array to be written to sheet in the end
  valuesForSheet.push(CHANNEL_VIDEOS_SHEET_HEADER);

  var results = YouTube.Channels.list('contentDetails', { id: channelID/* mine: true*/ });
  for (var i in results.items) {
    var item = results.items[i];
    // Get the playlist ID, which is nested in contentDetails, as described in the
    // Channel resource: https://developers.google.com/youtube/v3/docs/channels
    var playlistId = item.contentDetails.relatedPlaylists.uploads;

    var nextPageToken = '';

    // This loop retrieves a set of playlist items and checks the nextPageToken in the
    // response to determine whether the list contains additional items. It repeats that process
    // until it has retrieved all of the items in the list.
    while (nextPageToken != null) {
      var playlistResponse = YouTube.PlaylistItems.list('snippet', {
        playlistId: playlistId,
        maxResults: 25,
        pageToken: nextPageToken
      });

      for (var j = 0; j < playlistResponse.items.length; j++) {
        var playlistItem = playlistResponse.items[j];
        valuesForSheet.push([playlistItem.snippet.title, playlistItem.snippet.resourceId.videoId, playlistItem.snippet.description,
                              "=IMAGE(\"" + playlistItem.snippet.thumbnails.default.url + "\")",
                              "https://www.youtube.com/watch?v=" + playlistItem.snippet.resourceId.videoId]);
      }
      nextPageToken = playlistResponse.nextPageToken;
    }
  }

  sheet.clearContents();
  var lastRow = sheet.getLastRow();
  var range = sheet.getRange(lastRow + 1, 1, valuesForSheet.length, 5);
  range.setValues(valuesForSheet);
}

function uploadFiles() {
  try {
    //Upload Files to YouTube
    Logger.log("upload");

    var sheet = SpreadsheetApp.getActive().getSheetByName(FILE_UPLOAD_LIST_SHEET_NAME);
    var lastRow = sheet.getLastRow();
    var lastColumn = sheet.getLastColumn();
    var range = sheet.getRange(2, 1, lastRow - 1, lastColumn);
    var values = range.getValues();
    var currentRow = 2;

    var descriptionTemplate =SpreadsheetApp.getActive().getRange("Config!B2").getValue();

    Logger.log(descriptionTemplate);

    //Create a subfolder under Completed Uploads folder to move the finished files
    var completedUploadsFolders = DriveApp.getFoldersByName("Completed Uploads");
    var completedUploadsFolder = completedUploadsFolders.next();
    var now = new Date();
    var newFolder = completedUploadsFolder.createFolder("" + now);

    // r[0] - File Name
    // r[1] - Drive FileID
    // r[2] - Video title
    // r[3] - Video description
    // r[4] - Video tags
    for (var i in values) {
      var r = values[i];
      var fileID = r[1];
      var file = DriveApp.getFileById(fileID);
      var video = file.getBlob();

      var videoTitle = r[2];
      var videoDescription = r[3];
      
      if(videoDescription == "")
      {
        videoDescription = descriptionTemplate;
      }

      if(videoTitle == "")
      {
        videoTitle = r[0];
        videoTitle = videoTitle.replace(".mp4", "") //remove .mp4 from video title
      }
      
      //start uploads
      Logger.log("uploading " + videoTitle);

      var response = YouTube.Videos.insert({
        snippet: {
          title: videoTitle,
          description: videoDescription,
          tags: r[4],
          channelId: CHANNEL_ID
        },
        status: {
          privacyStatus: "unlisted",
          selfDeclaredMadeForKids: false,
        },
      }, "snippet,status", video); 

      sheet.getRange(currentRow, 6).setValue("https://www.youtube.com/watch?v=" + response.id); //5th row is the YouTube URL column
      currentRow = currentRow + 1;

      //move uploaded files to Completed Uploads folder
      file.moveTo(newFolder);      
    }
    Logger.log("uploads complete")
  } catch (err) {
    Logger.log("error message: " + err.message);
    return ContentService.createTextOutput(err.message)
  }
}

function traverseSubFolders(parent, list) {
  parent = parent.getId();
  var childFolder = DriveApp.getFolderById(parent).getFolders();
  while(childFolder.hasNext()) {
    var child = childFolder.next();
    addFilesToList(child, list);
    //Logger.log(child.getName() + " " + child.getId());
    traverseSubFolders(child, list);
  }
  return;
}

function addFilesToList(fromFolder, list) {
  var files = fromFolder.getFiles();
    while (files.hasNext()) {
    var file = files.next();
    if(file.getName().indexOf(".mp4") > -1) //if file is a video
      list.push([fromFolder.getName(), fromFolder.getId(), file.getName(), file.getId()]);
  }
}

function pullFilesFromRootFolder()
{
  var folderList = [];
  var rootFolderId = SpreadsheetApp.getActive().getRange("Config!B4").getValue();
  folderList = traverseDriveFolderforSubFolders(rootFolderId, folderList);

  var searchString = "(parents in '";
  var sheet = SpreadsheetApp.getActive().getSheetByName("File Upload List");
  var valuesForSheet = []; //File array to be written to sheet in the end
  valuesForSheet.push(FILE_UPLOAD_LIST_SHEET_HEADER);

  for(var i in folderList){
    var folderID = folderList[i];
    Logger.log("folderID: " + folderID);
    if(i == folderList.length-1){
      searchString = searchString + folderID;
    }
    else {
      searchString = searchString + folderID + "' or parents in '";
    }
  }

  searchString = searchString + "') and title contains '.mp4'";

  Logger.log(searchString);
  var files = DriveApp.searchFiles(searchString);

  while (files.hasNext()) {
    var file = files.next();
    valuesForSheet.push([file.getName(), file.getId(), "", "", "", ""]);
  }  

  sheet.clearContents();
  var lastRow = sheet.getLastRow();
  var range = sheet.getRange(lastRow + 1, 1, valuesForSheet.length, 6);
  range.setValues(valuesForSheet);
}

function traverseDriveFolderforSubFolders (rootFolderId, folderList) {
  var parentFolder = DriveApp.getFolderById(rootFolderId);
  var childFolders = parentFolder.getFolders();
  while(childFolders.hasNext()) {
    var child = childFolders.next();
    folderList.push(child.getId());
    folderList = traverseDriveFolderforSubFolders(child.getId(), folderList);
  }

  return folderList;
}
