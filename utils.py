import argparse
import os.path
import os
import re

from datetime import datetime
from hashlib import md5
from typing import Dict, List
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import createStringObject, NameObject


class Status:
    def __init__(self):
        self.__stack = []
        self.__sep = ' : '
        self.__endl = '\r'

    def push(self, message: str):
        self.__stack.append(message)
        self.write()

    def pop(self):
        if len(self.__stack) > 0:
            self.__stack.pop()
            self.write()

    def clear(self):
        self.__stack = []
        self.write()

    def write(self, message: str = None):
        addl = [message] if message is not None else []
        print(f'{self.__sep.join(self.__stack + addl)}',
              end=f'\033[K{self.__endl}')

    def debug(self, enable):
        self.__endl = '\n' if enable else '\r'


status = Status()


class Hashes:
    class HashedData:
        def __init__(self, data):
            self.__hash = md5(data).hexdigest()

        def hash(self):
            return self.__hash

    class HashedFile:
        def __init__(self, hash_root_dir, rel_file_path):
            self.__hash_root_dir = hash_root_dir
            self.__rel_file_path = rel_file_path
            self.__hash = None

        def hash(self):
            real_path = os.path.join(
                self.__hash_root_dir, self.__rel_file_path)
            if os.path.isfile(real_path):
                with open(real_path, 'rb+') as file:
                    return md5(file.read()).hexdigest()
            return None

    def __init__(self, hash_file_path: str):
        self.__hash_file_path = hash_file_path
        self.__blobs = {}
        self.__files = {}
        self.__loaded = {}
        self.__is_loaded = False

    def add_blob(self, blob_name: str, hashable_data):
        self.__blobs[blob_name] = Hashes.HashedData(hashable_data)

    def add_file(self, file_path: str):
        relpath = os.path.relpath(
            file_path, os.path.dirname(self.__hash_file_path))
        if not file_path in self.__files:
            self.__files[relpath] = Hashes.HashedFile(
                os.path.dirname(self.__hash_file_path), relpath)

    def has_changes(self, name: str = None) -> bool:
        self.__load()
        combined = self.__blobs | self.__files

        if name is None:
            if len(combined) != len(self.__loaded):
                return True
            for new in combined:
                if new not in self.__loaded:
                    return True
                if combined[new].hash() != self.__loaded[new]:
                    return True
            return False
        else:
            if name not in self.__loaded:
                return True;
            if combined[name].hash() != self.__loaded[name]:
                return True
            return False

    def save(self):
        combined = self.__blobs | self.__files
        with open(self.__hash_file_path, 'w+') as file:
            for name in combined:
                file.write(f'{name}:{combined[name].hash()}\n')

    def __load(self):
        if self.__is_loaded:
            return
        self.__is_loaded = True

        if not os.path.isfile(self.__hash_file_path):
            return

        with open(self.__hash_file_path, 'r+') as f:
            self.__loaded = {h[0]: h[1]
                             for h in (l.split(':') for l in f.read().splitlines())}

    def get_hash(self, file_path):
        relpath = os.path.relpath(
            file_path, os.path.dirname(self.__hash_file_path))
        if not relpath in self.__files:
            raise Exception(f'No hash info for {relpath} (from {file_path})')
        return self.__files[relpath].hash()


_singleton = None
_description = ""


def ArgumentParser(description=None, *arg_l, **arg_d):
    global _singleton, _description
    if description:
        if _description:
            _description += " & "+description
        else:
            _description = description
    if _singleton is None:
        _singleton = argparse.ArgumentParser(
            description=_description, *arg_l, **arg_d)
        _singleton.add_argument('--force', default=False,
                                action=argparse.BooleanOptionalAction, help='Force regeneration of the SVG placard even if no changes are detected.')
        _singleton.add_argument('--debug', default=False,
                                action=argparse.BooleanOptionalAction, help='Do not overwrite status messages during execution')
        _singleton.add_argument('--beer', default=None,
                                help='Only process beers with this exact name')

    return _singleton


def syscmd(cmd):
    parser = ArgumentParser()
    args = parser.parse_args()
    redirect = '' if args.debug else ' > /dev/null 2>&1'
    return os.system(f'{cmd} {redirect}')


def make_hash_stable_pdf(pdf_path):
    # Get rid of dynamic ids
    pdf_path_cleansed = f'{pdf_path}.cleansed'
    if syscmd(f'qpdf --static-id --pages {pdf_path} 1-z -- --empty {pdf_path_cleansed}') != 0:
        raise Exception(
            f'Failed to make pdf hash-stable.  Do you have qpdf installed?')

    # Kill creator and date-related metadata buried way down in the doc by Chrome's PDF renderer
    blank = u'blank'
    blank_date = u"D:20220101000000+00'00'"
    reader = PdfReader(pdf_path_cleansed)
    writer = PdfWriter()
    for page_num in range(reader.getNumPages()):
        infoDict = reader.flattened_pages[page_num].get_object(
        )['/Resources']['/XObject']['/Im1']['/PTEX.InfoDict']
        infoDict[NameObject('/Creator')] = createStringObject(blank)
        infoDict[NameObject('/CreationDate')] = createStringObject(blank_date)
        infoDict[NameObject('/ModDate')] = createStringObject(blank_date)
        infoDict[NameObject('/Producer')] = createStringObject(blank)
        writer.add_page(reader.flattened_pages[page_num])
    with open(pdf_path, 'wb') as output_stream:
        writer.write(output_stream)

    os.remove(pdf_path_cleansed)


class OutputFile:
    def __init__(self, type, mime_type, file_path, hashes: Hashes):
        self.type = type
        self.mime_type = mime_type
        self.file_path = file_path
        self.__hashes: Hashes = hashes

    def get_hash(self):
        return self.__hashes.get_hash(self.file_path)


class PreparedPlacard:
    def __init__(self, name: str, placard_dir: str):
        self.output_files: Dict[str, OutputFile] = {}
        self.processed: bool = False
        self.name = name
        self.placard_dir = placard_dir


class Site:
    def __init__(self, name, prepared_dir):
        self.name = name
        self.site_dir = os.path.join(prepared_dir, self._safe_path(name))
        self.prepared_placards: List[PreparedPlacard] = []

    def prepare_placard(self, brewer: str, beer: str, style: str, abv_str: str, logo_url: str) -> PreparedPlacard:
        placard = self._do_prepare_placard(
            brewer, beer, style, abv_str, logo_url)
        self.prepared_placards.append(placard)
        return placard

    def _safe_path(self, path: str):
        return re.sub('[^a-zA-Z0-9_-]', '_', path.lower())

    def _do_prepare_placard(self, brewer: str, beer: str, style: str, abv_str: str, logo_url: str) -> PreparedPlacard:
        pass
