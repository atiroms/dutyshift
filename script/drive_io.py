
###############################################################################
# Google Drive-backed data I/O layer
#
# Replaces local-filesystem data storage (previously a Dropbox-synced folder resolved via a
# hardcoded, machine-specific `lp_root` path list) with direct Google Drive API access. No
# local file mirror is used for shared/production data: a Drive folder named "dutyshift" is
# resolved by name from `root`, which is identical from every machine/account with access --
# there is nothing machine-specific left to configure beyond where local OAuth credential files
# live (see load_config()/config.local.json).
#
# Layout convention (mirrors the old local layout, normalized against the one place -- the
# Google Form -- that used a different convention before this module existed):
#   dutyshift/                    Drive root folder
#     config/                     member.xlsx (doctor roster)
#     <yyyymm>/                   live per-month data (CSVs)
#       result/<prefix>_<timestamp>/   timestamped snapshot of each pipeline run
#
# Every function here is pure I/O plumbing -- no pipeline/scheduling logic lives in this
# module.
###############################################################################

import os, io, json, datetime
from pathlib import Path
from dataclasses import dataclass

import pandas as pd
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload


###############################################################################
# OAuth scopes
###############################################################################
# The two identical scope lists previously duplicated in script/helper.py and script/form.py
# are centralized here. script/notify.py's Calendar scope is legitimately different and stays
# separate.
SCOPE_DRIVE_FORMS = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/forms.body']
SCOPE_DRIVE_CALENDAR = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/calendar']


###############################################################################
# Local per-machine config (config.local.json)
###############################################################################
def load_config():
    """Read config.local.json from the repo root. This is the only remaining
    machine-specific configuration -- where this machine's local OAuth credential/token files
    live. Everything else (the shared Drive data) is resolved by name, not by path, and is
    therefore identical across machines."""
    p_repo_root = Path(__file__).resolve().parents[1]
    p_config = p_repo_root / 'config.local.json'
    if not p_config.exists():
        raise FileNotFoundError(
            'config.local.json not found at ' + str(p_config) + '. Copy config.local.example.json '
            'to config.local.json and fill in your local credentials_path/token_path.'
        )
    with open(p_config, 'r') as f:
        config = json.load(f)
    for key in ['credentials_path', 'token_path']:
        if key not in config:
            raise KeyError("config.local.json is missing required key '" + key + "'.")
    return config


###############################################################################
# Credentials and service construction
###############################################################################
def get_credentials(p_cred, p_token, l_scope):
    """Load and reuse an existing token, refreshing it if expired; only fall back to the
    interactive browser consent flow if no valid/refreshable token exists. Unlike the old
    prep_api_creds (which unconditionally re-ran the full InstalledAppFlow every call), this
    means a normal run doesn't need a browser at all once token.json exists."""
    creds = None
    if os.path.exists(p_token):
        try:
            creds = Credentials.from_authorized_user_file(p_token, l_scope)
        except (ValueError, json.JSONDecodeError):
            creds = None

    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(p_cred, l_scope)
        creds = flow.run_local_server(port = 0)

    with open(p_token, 'w') as token:
        token.write(creds.to_json())

    return creds


@dataclass
class DriveServices:
    drive: object
    forms: object
    calendar: object


_dict_service_cache = {}

def get_services(config, l_scope):
    """Build {drive, forms, calendar} service objects from one set of credentials, memoized
    per (scope-set, credentials path) so a pipeline stage authenticates once regardless of how
    many I/O calls it makes."""
    key = (tuple(sorted(l_scope)), config['credentials_path'])
    if key not in _dict_service_cache:
        creds = get_credentials(config['credentials_path'], config['token_path'], l_scope)
        _dict_service_cache[key] = DriveServices(
            drive = build('drive', 'v3', credentials = creds),
            forms = build('forms', 'v1', credentials = creds),
            calendar = build('calendar', 'v3', credentials = creds),
        )
    return _dict_service_cache[key]


###############################################################################
# Check, create Google Drive folder/path
#
# Moved unchanged from script/helper.py, which is now imported from here instead of defining
# these itself.
###############################################################################
def check_gdrive_folder(service, id_folder_parent, name_folder_child):
    q = (
        f"'{id_folder_parent}' in parents "
        f"and name = '{name_folder_child}' "
        "and mimeType = 'application/vnd.google-apps.folder' "
        "and trashed = false"
    )
    resp = service.files().list(
        q = q,
        spaces = 'drive',
        fields = 'files(id, name)'
    ).execute()
    folder_old = resp.get('files', [])
    if folder_old:
        exist = True
        id_folder_child = folder_old[0]['id']
    else:
        exist = False
        id_folder_child = None

    return {'exist': exist, 'id_folder_child': id_folder_child}


def create_gdrive_folder(service, id_folder_parent, name_folder_child):
    result = check_gdrive_folder(service, id_folder_parent, name_folder_child)
    if result['exist']:
        new = False
        id_folder_child = result['id_folder_child']
    else:
        new = True
        id_folder_child = result['id_folder_child']
        folder_metadata = {
            'name': name_folder_child,                            # The folder name
            'mimeType': 'application/vnd.google-apps.folder',   # This tells Drive to make it a folder
            'parents': [id_folder_parent],
        }
        folder_new = service.files().create(
            body = folder_metadata,
            fields = 'id,name'
        ).execute()
        id_folder_child = folder_new['id']

    return {'new': new, 'id_folder_child': id_folder_child}


def check_gdrive_path(service, path):
    l_folder = path.split('/')
    l_folder = [folder for folder in l_folder if folder != '']
    root = service.files().get(
        fileId = 'root',
        fields = 'id'
    ).execute()
    id_folder_parent = root.get('id')
    l_id_folder = [id_folder_parent]

    exist = True
    for folder in l_folder:
        result = check_gdrive_folder(service, id_folder_parent, folder)
        if result['exist']:
            id_folder_parent = result['id_folder_child']
            l_id_folder.append(id_folder_parent)
        else:
            print('Missing path', path)
            exist = False
            break

    return {'exist': exist, 'l_id_folder': l_id_folder}


def create_gdrive_path(service, path):
    l_folder = path.split('/')
    l_folder = [folder for folder in l_folder if folder != '']
    root = service.files().get(
        fileId = 'root',
        fields = 'id'
    ).execute()
    id_folder_parent = root.get('id')
    l_id_folder = [id_folder_parent]

    for folder in l_folder:
        result_folder = create_gdrive_folder(service, id_folder_parent, folder)
        id_folder_parent = result_folder['id_folder_child']
        l_id_folder.append(id_folder_parent)
    return l_id_folder


def check_form_exists(service, path_form):
    path_folder = '/'.join(path_form.split('/')[:-1])
    name_form = path_form.split('/')[-1]
    result_folder = check_gdrive_path(service, path_folder)
    if result_folder['exist']:
        id_folder = result_folder['l_id_folder'][-1]
        resp = service.files().list(
            q = (
                f"'{id_folder}' in parents "
                f"and name = '{name_form}' "
                "and mimeType = 'application/vnd.google-apps.form' "
                "and trashed = false"
            ),
            fields = 'files(id, name)',
            pageSize = 1
        ).execute()
        if len(resp.get('files', [])) > 0:
            return resp.get('files', [])[0]['id']
        else:
            print('Form does not exist', name_form)
            return False
    else:
        return False


###############################################################################
# Per-call folder-ID cache and path resolution
#
# Deliberately per-call, not global/module-level: folder structure is created lazily during a
# run (create_gdrive_path), so a stale global cache could serve an id from before this run's
# own folder creation, or miss folders another process created concurrently. A cache created at
# the top of one pipeline-stage call and reused for that call's ~10-20 I/O sites turns what
# would be that many redundant files().list round trips into a small handful.
###############################################################################
class DriveFolderCache:
    def __init__(self):
        self._dict_id = {}

    def get_or_create(self, service, path):
        if path not in self._dict_id:
            l_id_folder = create_gdrive_path(service, path)
            self._dict_id[path] = l_id_folder[-1]
        return self._dict_id[path]

    def get_or_raise(self, service, path):
        if path not in self._dict_id:
            result = check_gdrive_path(service, path)
            if not result['exist']:
                raise FileNotFoundError('Drive path not found: ' + path)
            self._dict_id[path] = result['l_id_folder'][-1]
        return self._dict_id[path]


def resolve_folder_id(service, path, create = False, cache = None):
    if cache is None:
        cache = DriveFolderCache()
    if create:
        return cache.get_or_create(service, path)
    else:
        return cache.get_or_raise(service, path)


###############################################################################
# CSV / Excel read-write against Google Drive
#
# Everything stays in memory (io.BytesIO/io.StringIO) -- no local temp files are used, so this
# introduces no new machine-specific coupling.
###############################################################################
def _find_file_id(service, id_folder, filename):
    resp = service.files().list(
        q = (
            f"'{id_folder}' in parents "
            f"and name = '{filename}' "
            "and trashed = false"
        ),
        fields = 'files(id, name)',
        pageSize = 1
    ).execute()
    l_file = resp.get('files', [])
    return l_file[0]['id'] if l_file else None


def _download_bytes(service, id_file):
    request = service.files().get_media(fileId = id_file)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf


def _upload_bytes(service, id_folder, filename, buf, mimetype):
    media = MediaIoBaseUpload(buf, mimetype = mimetype, resumable = False)
    id_file = _find_file_id(service, id_folder, filename)
    if id_file is None:
        body = {'name': filename, 'parents': [id_folder]}
        result = service.files().create(body = body, media_body = media, fields = 'id').execute()
    else:
        # Upsert-by-name: overwrite the existing file's content, matching the old local
        # behavior where re-running a stage overwrote the CSVs already in p_month.
        result = service.files().update(fileId = id_file, media_body = media, fields = 'id').execute()
    return result['id']


def read_csv(service, id_folder, filename, **kwargs):
    id_file = _find_file_id(service, id_folder, filename)
    if id_file is None:
        raise FileNotFoundError(filename + ' not found in Drive folder ' + id_folder)
    buf = _download_bytes(service, id_file)
    return pd.read_csv(buf, **kwargs)


def write_csv(service, id_folder, filename, df, **kwargs):
    sio = io.StringIO()
    df.to_csv(sio, **kwargs)
    buf = io.BytesIO(sio.getvalue().encode('utf-8'))
    return _upload_bytes(service, id_folder, filename, buf, mimetype = 'text/csv')


def read_excel(service, id_folder, filename, **kwargs):
    id_file = _find_file_id(service, id_folder, filename)
    if id_file is None:
        raise FileNotFoundError(filename + ' not found in Drive folder ' + id_folder)
    buf = _download_bytes(service, id_file)
    return pd.read_excel(buf, **kwargs)


def read_json(service, id_folder, filename, default = None):
    """Unlike read_csv/read_excel, returns `default` instead of raising when the file doesn't
    exist -- callers (solver-preset/audit-record lookups) treat 'nothing recorded yet' as an
    expected, common state, not an error."""
    id_file = _find_file_id(service, id_folder, filename)
    if id_file is None:
        return default
    buf = _download_bytes(service, id_file)
    return json.loads(buf.read().decode('utf-8'))


def write_json(service, id_folder, filename, obj):
    buf = io.BytesIO(json.dumps(obj, indent = 2, ensure_ascii = False).encode('utf-8'))
    return _upload_bytes(service, id_folder, filename, buf, mimetype = 'application/json')


def month_folder_path(year, month):
    """Canonical Drive path (relative to root) for a month's live data folder:
    dutyshift/result/<year>/<month, zero-padded>/ -- this matches where script/form.py has
    always created that month's Google Form, and is the layout data gets manually placed in on
    Drive, so every other function resolves month folders through this one place rather than
    hand-building the path."""
    if isinstance(month, str):
        month_str = month
    else:
        month_str = str(month).zfill(2)
    return 'dutyshift/result/' + str(year) + '/' + month_str


def list_month_folders(service, id_root):
    """Enumerate existing past-month data folders under dutyshift/result/<year>/<month>/,
    returning them as sorted yyyymm strings (e.g. '202608') -- the same shape
    prep_assign_previous/past_score expect, previously produced by filtering
    os.listdir(Dropbox root) for startswith('20')/len==6 names."""
    result_result = check_gdrive_folder(service, id_root, 'result')
    if not result_result['exist']:
        return []
    id_result = result_result['id_folder_child']

    def _list_child_folders(id_parent):
        resp = service.files().list(
            q = (
                f"'{id_parent}' in parents "
                "and mimeType = 'application/vnd.google-apps.folder' "
                "and trashed = false"
            ),
            fields = 'files(id, name)',
            pageSize = 1000
        ).execute()
        return resp.get('files', [])

    l_dir = []
    for year_folder in _list_child_folders(id_result):
        year_name = year_folder['name']
        if not (year_name.startswith('20') and len(year_name) == 4 and year_name.isdigit()):
            continue  # skips non-year siblings under dutyshift/result/, e.g. 'replacement'
        for month_folder in _list_child_folders(year_folder['id']):
            month_name = month_folder['name']
            if len(month_name) == 2 and month_name.isdigit():
                l_dir.append(year_name + month_name)
    return sorted(l_dir)


###############################################################################
# Prepare Drive paths for one pipeline-stage call
#
# Direct replacement for script/helper.py::prep_dirs's (p_root, p_month, p_data) tuple. Unlike
# prep_dirs, this does not chdir the process or assume a 'GitHub/dutyshift' checkout location
# -- there is no local-path assumption left to make.
###############################################################################
@dataclass
class DrivePaths:
    service_drive: object
    id_root: str
    id_month: str
    id_data: object   # str, or None if make_data_dir=False
    cache: DriveFolderCache


def prep_drive_paths(config, service_drive, year_plan, month_plan, prefix_dir, make_data_dir = True):
    cache = DriveFolderCache()
    id_root = cache.get_or_create(service_drive, 'dutyshift')

    path_month = month_folder_path(year_plan, month_plan)
    id_month = cache.get_or_create(service_drive, path_month)

    if make_data_dir:
        d_data = prefix_dir + '_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        id_data = cache.get_or_create(service_drive, path_month + '/result/' + d_data)
    else:
        id_data = None

    return DrivePaths(service_drive, id_root, id_month, id_data, cache)
