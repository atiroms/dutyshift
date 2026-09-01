
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
#     config/                     member (doctor roster, native Google Sheet -- one tab per
#                                  month, see script/helper.py::member_sheet_name)
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
# Used only by script/form.py::prepare_form, which is the only stage that drafts a notification
# email -- principle of least privilege, no other stage needs Gmail access. gmail.compose is the
# minimal Gmail scope that permits creating a draft; Gmail's scope model has no narrower
# "draft-only, can never send" option, so the "never auto-send" guarantee is enforced entirely
# at the code level (nothing in this codebase ever calls a send/drafts.send endpoint).
SCOPE_DRIVE_FORMS_GMAIL = SCOPE_DRIVE_FORMS + ['https://www.googleapis.com/auth/gmail.compose']
# Used by script/notify.py's draft-notification actions (draft_dropin_notification/
# draft_fixed_notification), which need Drive (assignment sheet link, config/member,
# config/config.json, template/*.json) and Gmail (drafting) but neither Forms nor Calendar.
SCOPE_DRIVE_GMAIL = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/gmail.compose']


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
    interactive browser consent flow if no valid/refreshable token exists, OR the cached token
    was granted for a narrower scope than l_scope now needs. Unlike the old prep_api_creds
    (which unconditionally re-ran the full InstalledAppFlow every call), this means a normal run
    doesn't need a browser at all once token.json exists.

    The narrower-scope check matters because Credentials.from_authorized_user_file(path, scopes)
    ADOPTS whatever `scopes` you pass in as the returned object's own .scopes -- it does not
    validate that against what's actually recorded in the file (google-auth only falls back to
    the file's own 'scopes' field when the scopes argument is None, which we never pass). A
    token cached before some new scope was added to l_scope would otherwise be silently reused
    or refreshed, producing credentials that report .scopes as the newly-requested (broader) set
    while the underlying refresh token is still only actually authorized, server-side, for the
    old (narrower) one -- Google's refresh endpoint can't expand a refresh token's scope after
    the fact. That surfaces later as a confusing insufficient-scope error from whichever API
    needed the new scope, not as an obvious auth failure here -- so check the file's own
    recorded scopes directly before trusting it."""
    creds = None
    if os.path.exists(p_token):
        try:
            with open(p_token, 'r') as f:
                dict_token_cached = json.load(f)
            if set(l_scope) <= set(dict_token_cached.get('scopes') or []):
                creds = Credentials.from_authorized_user_file(p_token, l_scope)
            # else: cached token doesn't cover everything l_scope now needs -- leave creds=None
            # so the interactive flow below runs and grants the full scope fresh.
        except (ValueError, OSError, json.JSONDecodeError):
            creds = None

    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(p_cred, l_scope)
        creds = flow.run_local_server(port=0)

    with open(p_token, 'w') as token:
        token.write(creds.to_json())

    return creds


@dataclass
class DriveServices:
    drive: object
    forms: object
    calendar: object
    gmail: object
    sheets: object


_dict_service_cache = {}

def get_services(config, l_scope):
    """Build {drive, forms, calendar, gmail, sheets} service objects from one set of
    credentials, memoized per (scope-set, credentials path) so a pipeline stage authenticates
    once regardless of how many I/O calls it makes. Building a client here doesn't require its
    scope to have been granted -- only actually calling one of its methods does -- so all five
    are built unconditionally regardless of which scopes l_scope actually requested, same as
    before gmail was added. sheets needs no scope of its own: Google accepts the broad 'drive'
    scope (already in both SCOPE_DRIVE_FORMS and SCOPE_DRIVE_CALENDAR) for Sheets API calls
    too."""
    key = (tuple(sorted(l_scope)), config['credentials_path'])
    if key not in _dict_service_cache:
        creds = get_credentials(config['credentials_path'], config['token_path'], l_scope)
        _dict_service_cache[key] = DriveServices(
            drive=build('drive', 'v3', credentials=creds),
            forms=build('forms', 'v1', credentials=creds),
            calendar=build('calendar', 'v3', credentials=creds),
            gmail=build('gmail', 'v1', credentials=creds),
            sheets=build('sheets', 'v4', credentials=creds),
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
        q=q,
        spaces='drive',
        fields='files(id, name)'
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
            body=folder_metadata,
            fields='id,name'
        ).execute()
        id_folder_child = folder_new['id']

    return {'new': new, 'id_folder_child': id_folder_child}


def check_gdrive_path(service, path):
    l_folder = path.split('/')
    l_folder = [folder for folder in l_folder if folder != '']
    root = service.files().get(
        fileId='root',
        fields='id'
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
        fileId='root',
        fields='id'
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
            q=(
                f"'{id_folder}' in parents "
                f"and name = '{name_form}' "
                "and mimeType = 'application/vnd.google-apps.form' "
                "and trashed = false"
            ),
            fields='files(id, name)',
            pageSize=1
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


def resolve_folder_id(service, path, create=False, cache=None):
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
        q=(
            f"'{id_folder}' in parents "
            f"and name = '{filename}' "
            "and trashed = false"
        ),
        fields='files(id, name)',
        pageSize=1
    ).execute()
    l_file = resp.get('files', [])
    return l_file[0]['id'] if l_file else None


def _download_bytes(service, id_file):
    request = service.files().get_media(fileId=id_file)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf


def _upload_bytes(service, id_folder, filename, buf, mimetype):
    media = MediaIoBaseUpload(buf, mimetype=mimetype, resumable=False)
    id_file = _find_file_id(service, id_folder, filename)
    if id_file is None:
        body = {'name': filename, 'parents': [id_folder]}
        result = service.files().create(body=body, media_body=media, fields='id').execute()
    else:
        # Upsert-by-name: overwrite the existing file's content, matching the old local
        # behavior where re-running a stage overwrote the CSVs already in p_month.
        result = service.files().update(fileId=id_file, media_body=media, fields='id').execute()
    return result['id']


def get_file_web_link(service, id_folder, filename):
    """Return the Drive webViewLink URL for `filename` in `id_folder`, or None if no such file
    exists yet. Used by script/notify.py's draft-notification actions to link to the
    'assignment_<yyyymm>' Google Sheet script/notify.py::create_assignment_sheet already
    created."""
    id_file = _find_file_id(service, id_folder, filename)
    if id_file is None:
        return None
    return service.files().get(fileId=id_file, fields='webViewLink').execute().get('webViewLink')


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
    return _upload_bytes(service, id_folder, filename, buf, mimetype='text/csv')


def read_member_matrix_csv(service, id_folder, filename):
    """Read a date_duty x member_id wide matrix (availability.csv, assign.csv): rows indexed by
    date_duty, one column per member ID. Member ID column headers always round-trip through CSV
    as strings; this restores them to int so callers never need to re-cast them by hand (a cast
    that was previously done ad hoc at some call sites and missing at others)."""
    df = read_csv(service, id_folder, filename, index_col=0)
    df.columns = [int(col) for col in df.columns]
    return df


def read_gsheet(service_sheets, service_drive, id_folder, filename, sheet_name, header=0):
    """Read one tab of a native Google Sheet (e.g. config/member) into a DataFrame, mirroring
    pandas.read_excel's header=0 default: the tab's `header`-th row becomes the DataFrame's
    column labels and rows above it are discarded (pass header=None for a raw grid with no
    column-label row consumed). Google Sheets' values.get trims trailing blank cells -- rows can
    come back shorter than the widest row, or missing trailing blank rows/columns entirely -- so
    rows are padded to a common width first."""
    id_file = _find_file_id(service_drive, id_folder, filename)
    if id_file is None:
        raise FileNotFoundError(filename + ' not found in Drive folder ' + id_folder)
    resp = service_sheets.spreadsheets().values().get(
        spreadsheetId=id_file, range=sheet_name, valueRenderOption='UNFORMATTED_VALUE'
    ).execute()
    l_row = resp.get('values', [])
    if not l_row:
        return pd.DataFrame()
    n_col = max(len(row) for row in l_row)
    l_row = [row + [None] * (n_col - len(row)) for row in l_row]
    if header is None:
        return pd.DataFrame(l_row)
    return pd.DataFrame(l_row[header + 1:], columns=l_row[header]).reset_index(drop=True)


def list_gsheet_tabs(service_sheets, service_drive, id_folder, filename):
    id_file = _find_file_id(service_drive, id_folder, filename)
    if id_file is None:
        raise FileNotFoundError(filename + ' not found in Drive folder ' + id_folder)
    resp = service_sheets.spreadsheets().get(
        spreadsheetId=id_file, fields='sheets.properties(title)'
    ).execute()
    return [sheet['properties']['title'] for sheet in resp.get('sheets', [])]


def copy_gsheet_tab(service_sheets, service_drive, id_folder, filename, sheet_src, sheet_dst):
    """Duplicate an existing tab within a native Google Sheet and rename the copy, preserving
    every other tab (Sheets API DuplicateSheetRequest carries over cell values/styles/merges/
    formatting, same as the old openpyxl-based copy this replaces).

    Returns 'copied', 'exists' (sheet_dst already present -- left untouched, never overwritten,
    since clobbering an admin's already-edited per-doctor parameters would be destructive), or
    'missing_source' (sheet_src not found)."""
    id_file = _find_file_id(service_drive, id_folder, filename)
    if id_file is None:
        raise FileNotFoundError(filename + ' not found in Drive folder ' + id_folder)
    resp = service_sheets.spreadsheets().get(
        spreadsheetId=id_file, fields='sheets.properties(sheetId,title)'
    ).execute()
    dict_title_to_id = {sheet['properties']['title']: sheet['properties']['sheetId']
                         for sheet in resp.get('sheets', [])}
    if sheet_dst in dict_title_to_id:
        return 'exists'
    if sheet_src not in dict_title_to_id:
        return 'missing_source'
    body = {'requests': [{'duplicateSheet': {
        'sourceSheetId': dict_title_to_id[sheet_src],
        'newSheetName': sheet_dst,
    }}]}
    service_sheets.spreadsheets().batchUpdate(spreadsheetId=id_file, body=body).execute()
    return 'copied'


def ensure_gsheet_tab(service_sheets, service_drive, id_folder, filename, sheet_name, values,
                      build_requests=None, overwrite=False):
    """Ensure a native Google Sheet named `filename` exists in Drive folder `id_folder` and has a
    tab `sheet_name` populated with `values` (list of rows, each a list of cell values -- row 0
    is typically the header). Creates the spreadsheet (moving it into id_folder) if it doesn't
    exist yet; adds the tab within it if the spreadsheet already exists but the tab doesn't.

    If the tab already exists: left untouched (returns 'tab_exists') unless overwrite=True, in
    which case its content and formatting are replaced in place. Pass overwrite=True only for
    tabs with no hand-editable content (e.g. a purely computed score table) -- never for a tab a
    human might have since hand-edited, same non-destructive convention as copy_gsheet_tab.

    `build_requests(id_sheet)`, given the tab's real sheetId once it exists, may optionally
    return a list of further Sheets API batchUpdate request dicts (repeatCell for
    colors/fonts/borders, mergeCells, updateDimensionProperties for column widths, ...), applied
    right after the values are written.

    Returns ('file_and_tab_created' | 'tab_created' | 'tab_overwritten' | 'tab_exists', id_file).
    """
    id_file = _find_file_id(service_drive, id_folder, filename)
    file_created = False
    if id_file is None:
        body_create = {'properties': {'title': filename},
                       'sheets': [{'properties': {'title': sheet_name}}]}
        result = service_sheets.spreadsheets().create(
            body=body_create, fields='spreadsheetId,sheets.properties.sheetId'
        ).execute()
        id_file = result['spreadsheetId']
        id_sheet = result['sheets'][0]['properties']['sheetId']

        # spreadsheets().create() always creates the file in the caller's My Drive root -- move
        # it into id_folder to match every other Drive-backed file this codebase writes.
        file_meta = service_drive.files().get(fileId=id_file, fields='parents').execute()
        str_parent_prev = ','.join(file_meta.get('parents', []))
        service_drive.files().update(fileId=id_file, addParents=id_folder,
                                     removeParents=str_parent_prev, fields='id').execute()
        file_created = True
    else:
        resp = service_sheets.spreadsheets().get(
            spreadsheetId=id_file, fields='sheets.properties(sheetId,title)'
        ).execute()
        dict_title_to_id = {s['properties']['title']: s['properties']['sheetId']
                            for s in resp.get('sheets', [])}
        if sheet_name in dict_title_to_id:
            if not overwrite:
                return 'tab_exists', id_file
            id_sheet = dict_title_to_id[sheet_name]
            service_sheets.spreadsheets().values().clear(
                spreadsheetId=id_file, range=sheet_name, body={}
            ).execute()
        else:
            body_add = {'requests': [{'addSheet': {'properties': {'title': sheet_name}}}]}
            resp_add = service_sheets.spreadsheets().batchUpdate(spreadsheetId=id_file, body=body_add).execute()
            id_sheet = resp_add['replies'][0]['addSheet']['properties']['sheetId']

    service_sheets.spreadsheets().values().update(
        spreadsheetId=id_file, range=sheet_name, valueInputOption='RAW', body={'values': values}
    ).execute()

    if build_requests:
        requests = build_requests(id_sheet)
        if requests:
            service_sheets.spreadsheets().batchUpdate(spreadsheetId=id_file, body={'requests': requests}).execute()

    if file_created:
        return 'file_and_tab_created', id_file
    return ('tab_overwritten' if overwrite else 'tab_created'), id_file


def read_json(service, id_folder, filename, default=None):
    """Unlike read_csv/read_gsheet, returns `default` instead of raising when the file doesn't
    exist -- callers (solver-preset/audit-record lookups) treat 'nothing recorded yet' as an
    expected, common state, not an error."""
    id_file = _find_file_id(service, id_folder, filename)
    if id_file is None:
        return default
    buf = _download_bytes(service, id_file)
    return json.loads(buf.read().decode('utf-8'))


def write_json(service, id_folder, filename, obj):
    buf = io.BytesIO(json.dumps(obj, indent=2, ensure_ascii=False).encode('utf-8'))
    return _upload_bytes(service, id_folder, filename, buf, mimetype='application/json')


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
            q=(
                f"'{id_parent}' in parents "
                "and mimeType = 'application/vnd.google-apps.folder' "
                "and trashed = false"
            ),
            fields='files(id, name)',
            pageSize=1000
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
    service_sheets: object = None


def prep_drive_paths(config, services, year_plan, month_plan, prefix_dir, make_data_dir=True):
    """`services` is a DriveServices (see get_services) -- takes the whole bundle, not just
    .drive, so DrivePaths can also carry .sheets through for callers that end up needing
    read_gsheet (e.g. script/helper.py::read_member) without every caller having to thread it
    separately."""
    service_drive = services.drive
    cache = DriveFolderCache()
    id_root = cache.get_or_create(service_drive, 'dutyshift')

    path_month = month_folder_path(year_plan, month_plan)
    id_month = cache.get_or_create(service_drive, path_month)

    if make_data_dir:
        d_data = prefix_dir + '_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        id_data = cache.get_or_create(service_drive, path_month + '/result/' + d_data)
    else:
        id_data = None

    return DrivePaths(service_drive, id_root, id_month, id_data, cache, services.sheets)
