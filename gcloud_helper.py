#!/usr/bin/env python3

from __future__ import print_function

import os.path
import os
from typing import Dict, List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from utils import OutputFile, PreparedPlacard, Site, status, ArgumentParser

# If modifying these scopes, delete the file token.json.
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    # Need to make sure we can overwrite files other users upload.
    'https://www.googleapis.com/auth/drive'
]

PAGE_SIZE = 150

parser = ArgumentParser()


class GCloud:
    class Folder:
        def __init__(self, name):
            self.name = name
            self.id = None

    class _SiteFolder(Folder):
        def __init__(self, site: Site):
            self.name = site.name
            self.id = None
            self.upload_folders: Dict[str, GCloud._UploadFolder] = {}
            for placard in site.prepared_placards:
                for name, output_file in placard.output_files.items():
                    if not name in self.upload_folders:
                        self.upload_folders[name] = GCloud._UploadFolder(
                            name, output_file.mime_type)
                    elif self.upload_folders[name].mime_type != output_file.mime_type:
                        raise Exception(
                            f'Mismatched upload folder mime type for {name}.  Both {self.upload_folders[name].mime_type} and {output_file.mime_type} use that name.')

    class _UploadFolder(Folder):
        def __init__(self, name: str, mime_type: str):
            super().__init__(name)
            self.mime_type = mime_type
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

    def __init__(self, placard_folder_id: str, sites: List[Site]):
        self.__args = parser.parse_args()

        self.__init_gapi()
        self.__placards_folder_id = placard_folder_id
        self.__remote_hashes_loaded = False
        self.__sites = sites
        self.__site_folders: Dict[str, GCloud._SiteFolder] = {}
        self.__site_folders_loaded = False
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

    def __init_site_folders(self):
        if self.__site_folders_loaded:
            return
        self.__site_folders_loaded = True

        for site in self.__sites:
            site_folder = GCloud._SiteFolder(site)
            self.__site_folders[site.name] = site_folder
            self.__get_or_create_folder_id(
                self.__placards_folder_id, site_folder)
            for folder in site_folder.upload_folders.values():
                self.__get_or_create_folder_id(site_folder.id, folder)

    def __load_remote_hashes(self):
        if self.__remote_hashes_loaded:
            return
        self.__remote_hashes_loaded = True
        self.__init_site_folders()

        status.push("Loading remote hashes")
        # List files in each site's upload folders
        for site_folder in self.__site_folders.values():
            status.push(f'Site: {site_folder.name}')
            for folder in site_folder.upload_folders.values():
                names = set()
                status.push(folder.name)
                nextPageToken = ''
                page = 1
                while True:
                    results = self.__files.list(
                        q=f"mimeType='{folder.mime_type}' and parents in '{folder.id}' and trashed=false",
                        spaces='drive',
                        pageSize=PAGE_SIZE,
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
                    status.write(f'Loaded page #{page}')
                    page += 1
                    if nextPageToken is None:
                        status.write(f'No more pages.  Loaded {len(names)} file hashes.')
                        break
                status.pop()
            status.pop()
        status.pop()

    def __get_or_create_folder_id(self, parent_folder_id, folder: Folder):
        if folder.id:
            return folder.id

        item = self.__find_existing_item(
            parent_folder_id, folder.name, 'application/vnd.google-apps.folder')
        if not item:
            # Need to create folder in parent
            status.write(f'Creating upload folder {folder.name}')
            file_metadata = {
                'name': folder.name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_folder_id]
            }
            result = self.__files.create(body=file_metadata, supportsAllDrives=True,
                                         fields='id').execute()
            folder.id = result.get('id')
        else:
            folder.id = item['id']

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
            self.__init_site_folders()
            self.__load_remote_hashes()
        finally:
            status.pop()
        self.__drive_initialized = True

    def upload(self):
        self.init_drive()

        status.push('Sync')
        for site in self.__sites:
            status.push(site.name)
            site_folder = self.__site_folders[site.name]
            for placard in site.prepared_placards:
                status.push(placard.name)
                for output_file in placard.output_files.values():
                    self._push_to_folder(
                        site_folder.upload_folders[output_file.type], placard, output_file)
                    pass
                status.pop()
            status.pop()
        status.pop()

    def _push_to_folder(self, upload_folder: _UploadFolder, placard: PreparedPlacard, output_file: OutputFile):

        # Create name, do initial change detection
        escaping = str.maketrans({'\\': '\\\\', "'": "\'"})
        file_name = f'{placard.name}{os.path.splitext(output_file.file_path)[1]}'.translate(
            escaping)

        # Do change detection
        local_hash = output_file.get_hash()
        remote_hash = upload_folder.get_file_hash(file_name)
        if remote_hash == local_hash:
            status.write(f'No change for {file_name}')
            return
        else:
            status.write(f'Change detected for {file_name} - remote: {remote_hash} vs local: {local_hash}')

        # Find existing file (if any)
        file = self.__find_existing_item(
            upload_folder.id, file_name, upload_folder.mime_type)

        # Upload file to this folder
        media = MediaFileUpload(os.path.abspath(output_file.file_path),
                                mimetype=upload_folder.mime_type,
                                resumable=True)

        if file is not None:
            status.write(f'Updating {file_name}')
            file_metadata = {
                'name': file_name,
                'properties': {
                    'md5': local_hash
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
                'parents': [upload_folder.id],
                'properties': {
                    'md5': local_hash
                }
            }
            self.__files.create(
                body=file_metadata,
                media_body=media,
                supportsAllDrives=True,
                fields="id").execute()

    def load_sheet(self, spreadsheet_id, range_name, min_cols):
        result = self.__sheets.values().get(spreadsheetId=spreadsheet_id,
                                            range=range_name).execute()
        values = result.get('values', [])
        if not values:
            status.write('No data found.')
            return []
        for row in values:
            while len(row) < min_cols:
                row.append('')
        return values
