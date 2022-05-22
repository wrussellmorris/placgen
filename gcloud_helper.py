#!/usr/bin/env python3

from __future__ import print_function

import os.path
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from utils import status

# If modifying these scopes, delete the file token.json.
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/drive.metadata.readonly',
    'https://www.googleapis.com/auth/drive.file'
]


def load_sheet(spreadsheet_id, range_name):
    """Shows basic usage of the Sheets API.
    Prints values from a sample spreadsheet.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    service = build('sheets', 'v4', credentials=creds)

    # Call the Sheets API
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id,
                                range=range_name).execute()
    values = result.get('values', [])
    if not values:
        status.write('No data found.')
        return []
    for row in values:
        while len(row) < 5:
            row.append('')
    return values


class GCloud:

    class _UploadFolder:
        def __init__(self, name: str, mime_type: str):
            self.name = name
            self.mime_type = mime_type
            self.id = None
            self.__file_name_to_hash = {}

        def set_file_hash(self, name, hash):
            self.__file_name_to_hash[name] = hash

        def get_file_hash(self, name):
            if name in self.__file_name_to_hash:
                return self.__file_name_to_hash[name]
            else:
                return None

    class _RemoteFileData:
        def __init__(self, item):
            self.name = item['name']
            self.id = item['id']
            self.hash = None
            if not 'properties' in item:
                return
            if not 'md5' in item['properties']:
                return
            self.hash = item['properties']['md5']

    def __init__(self, placards_folder_id):
        self.__init_gapi()
        self.__placards_folder_id = placards_folder_id
        self.__remote_hashes_loaded = False
        self.__upload_folders = {}
        self.__upload_folders_loaded = False
        self.__drive_initialized = False

    def __init_gapi(self):
        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        self.__files = build('drive', 'v3', credentials=creds).files()
        self.__sheets = build('sheets', 'v4', credentials=creds).spreadsheets()

    def add_upload_folder(self, name, content_mime_type):
        self.__upload_folders[name] = GCloud._UploadFolder(
            name, content_mime_type)

    def __init_upload_folders(self):
        if self.__upload_folders_loaded:
            return
        self.__upload_folders_loaded = True

        for folder in self.__upload_folders.values():
            folder.id = self.__get_or_create_folder_id(folder.name)

    def __load_remote_hashes(self):
        if self.__remote_hashes_loaded:
            return
        self.__remote_hashes_loaded = True
        self.__init_upload_folders()

        status.push("Loading remote hashes")
        # List files in each of the main upload dirs
        for folder in self.__upload_folders.values():
            names = set()
            status.push(folder.name)
            nextPageToken = ''
            page = 1
            while True:
                results = self.__files.list(
                    q=f"mimeType='{folder.mime_type}' and parents in '{folder.id}' and trashed=false",
                    spaces='drive',
                    pageSize=10,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    fields="nextPageToken, files(id, name, properties)",
                    pageToken=nextPageToken).execute()
                items = results.get('files', [])
                nextPageToken = results.get('nextPageToken')
                for item in items:
                    remote = GCloud._RemoteFileData(item)
                    if remote.name in names:
                        raise Exception(
                            f'Duplicate remote file {folder.name} / {remote.name}')
                    names.add(remote.name)
                    status.write(remote.name)
                    folder.set_file_hash(remote.name, remote.hash)
                page += 1
                if nextPageToken is None:
                    break
            status.pop()
        status.pop()

    def __get_or_create_folder_id(self, folder_name):
        if not folder_name in self.__upload_folders:
            raise Exception(f'Unknown upload folder {folder_name}')
        folder = self.__upload_folders[folder_name]
        if folder.id:
            return folder.id

        item = self.__find_existing_item(
            self.__placards_folder_id, folder_name, 'application/vnd.google-apps.folder')
        if not item:
            # Need to create folder in parent
            status.write(f'Creating upload folder {folder_name}')
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [self.__placards_folder_id]
            }
            result = self.__files.create(body=file_metadata, supportsAllDrives=True,
                                         fields='id').execute()
            folder.id = result.get('id')
        else:
            folder.id = item['id']
        return folder.id

    def __find_existing_item(self, parent_folder_id: str, item_name: str, mime_type: str):
        results = self.__files.list(
            q=f"mimeType='{mime_type}' and name=\"{item_name}\" and parents in '{parent_folder_id}' and trashed=false",
            spaces='drive',
            pageSize=10,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            fields="files(id, name, properties)").execute()
        items = results.get('files', [])
        if not items:
            return None
        elif len(items) > 1:
            raise Exception(f'More than one item named {item_name}')
        return items[0]

    def init_drive(self):
        if self.__drive_initialized:
            return

        try:
            status.push("Preparing Google Drive folder(s)")
            self.__init_upload_folders()
            self.__load_remote_hashes()
        finally:
            status.pop()
        self.__drive_initialized = True

    def push_to_folder(self, folder_name, brewer, beer, file_path, md5_file_hash):
        self.init_drive()

        # Get folder id for folder_name
        if not folder_name in self.__upload_folders:
            raise Exception(f'Unknown upload folder {folder_name}')
        folder = self.__upload_folders[folder_name]

        # Create name, do initial change detection
        escaping = str.maketrans({'\\': '\\\\', "'": "\'"})
        file_name = f'{brewer} - {beer}{os.path.splitext(file_path)[1]}'.translate(
            escaping)

        # Do chnage detection ASAP
        remote_hash = folder.get_file_hash(file_name)
        if remote_hash == md5_file_hash:
            status.write(f'No change for {file_name}')
            return
        else:
            status.write(f'Change detected for {file_name}')

        # Find existing file (if any)
        file = self.__find_existing_item(
            folder.id, file_name, folder.mime_type)

        # Upload file to this folder
        media = MediaFileUpload(os.path.abspath(file_path),
                                mimetype=folder.mime_type,
                                resumable=True)

        if remote_hash is not None:
            status.write(f'Updating {file_name}')
            file_metadata = {
                'name': file_name,
                'properties': {
                    'md5': md5_file_hash
                }
            }
            self.__files.update(
                fileId=file['id'],
                body=file_metadata,
                media_body=media,
                supportsAllDrives=True,
                fields="id").execute()
        else:
            status.write(f'Uploading {file_name}')
            file_metadata = {
                'name': file_name,
                'parents': [folder.id],
                'properties': {
                    'md5': md5_file_hash
                }
            }
            self.__files.create(
                body=file_metadata,
                media_body=media,
                supportsAllDrives=True,
                fields="id").execute()

    def load_sheet(self, spreadsheet_id, range_name):
        result = self.__sheets.values().get(spreadsheetId=spreadsheet_id,
                                            range=range_name).execute()
        values = result.get('values', [])
        if not values:
            status.write('No data found.')
            return []
        for row in values:
            while len(row) < 5:
                row.append('')
        return values
