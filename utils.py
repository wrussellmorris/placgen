import os.path
import os

from hashlib import md5


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

    def add_blob(self, blob_name: str, hashable_data):
        self.__blobs[blob_name] = Hashes.HashedData(hashable_data)

    def add_file(self, file_path: str):
        relpath = os.path.relpath(
            file_path, os.path.dirname(self.__hash_file_path))
        if not file_path in self.__files:
            self.__files[relpath] = Hashes.HashedFile(
                os.path.dirname(self.__hash_file_path), relpath)

    def has_changes(self) -> bool:
        self.__load()
        combined = self.__blobs | self.__files

        if len(combined) != len(self.__loaded):
            status.write(
                f'Mismatch size: {len(combined)} vs {len(self.__loaded)}')
            return True
        for new in combined:
            if new not in self.__loaded:
                status.write(f'New: {new} - not present previously')
                return True
            if combined[new].hash() != self.__loaded[new]:
                status.write(
                    f'Mismatch: {new} - old:{self.__loaded[new]} vs new:{combined[new].hash()}')
                return True
        return False

    def save(self):
        combined = self.__blobs | self.__files
        with open(self.__hash_file_path, 'w+') as file:
            for name in combined:
                file.write(f'{name}:{combined[name].hash()}\n')

    def __load(self):
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
