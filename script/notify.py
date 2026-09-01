
import base64
from email.mime.text import MIMEText
import numpy as np
import pandas as pd, datetime as dt
from script.helper import read_member, load_drive_config, load_email_template, duty_time_table
from script.parameter import str_email_button_html, dict_duty_info
from script.drive_io import (
    get_services, prep_drive_paths, read_csv, read_member_matrix_csv, ensure_gsheet_tab, get_file_web_link,
    SCOPE_DRIVE_CALENDAR, SCOPE_DRIVE_GMAIL,
)


###############################################################################
# Create the "調整結果" (adjustment result) Google Sheet -- a human-readable duty table for the
# month (tab 'ver.<today>', from assign_print.csv) plus a per-doctor score breakdown (tab
# 'score', from score_print.csv), both written by script/helper.py::convert_assignment during
# "3. Assign". Column widths/colors/borders/merges below were reverse-engineered from a hand-
# built reference sheet for this same roster to match its look exactly -- see git history for
# the reference this was matched against if these ever need re-deriving.
#
# Columns 'B当直' and the left half of the merged 'ECT' header are duty slots staffed by a
# separate, non-dutyshift process (e.g. a hospital team-leader rotation) -- they are always left
# blank here, on purpose, for someone to fill in by hand afterward.
###############################################################################
_COLOR_BORDER = {'red': 0.8509804, 'green': 0.8509804, 'blue': 0.8509804}
_COLOR_HEADER_BG = {'red': 0.34901962, 'green': 0.34901962, 'blue': 0.34901962}
_COLOR_HEADER_FG = {'red': 1, 'green': 1, 'blue': 1}
_COLOR_HOLIDAY_BG = {'red': 0.7176471, 'green': 0.7176471, 'blue': 0.7176471}
_ASSIGN_COL_WIDTH = [90, 71, 64, 86, 145, 47, 55, 59, 59]  # 日付,am,pm,A当直,B当直,ocday,ocnight,ECT(左右)
_BORDER_ALL_SIDES = {side: {'style': 'SOLID', 'width': 1, 'color': _COLOR_BORDER}
                     for side in ('top', 'bottom', 'left', 'right')}


def _is_holiday_title_date(title_date):
    """title_date is script/helper.py::prep_calendar's '8/1(土)' / '8/11(火・祝)' style string --
    holiday rows (weekends and jpholiday-flagged dates) are the ones whose weekday/holiday marker
    is 土, 日 or 祝, which only ever appears inside that trailing parenthetical."""
    return any(marker in title_date for marker in ('土', '日', '祝'))


_ZENKAKU_DIGIT = str.maketrans('0123456789', '０１２３４５６７８９')


def _repeat_cell(id_sheet, r0, r1, c0, c1, fmt, fields):
    return {'repeatCell': {
        'range': {'sheetId': id_sheet, 'startRowIndex': r0, 'endRowIndex': r1,
                 'startColumnIndex': c0, 'endColumnIndex': c1},
        'cell': {'userEnteredFormat': fmt},
        'fields': fields,
    }}


def _merge(id_sheet, r0, r1, c0, c1):
    return {'mergeCells': {'range': {'sheetId': id_sheet, 'startRowIndex': r0, 'endRowIndex': r1,
                                     'startColumnIndex': c0, 'endColumnIndex': c1},
                           'mergeType': 'MERGE_ALL'}}


def _build_assignment_requests(id_sheet, l_title_date):
    """id_sheet: real sheetId of the 'ver.<today>' tab. l_title_date: this month's '日付' column
    values in row order, used only to find which rows are holidays (get the gray row fill and the
    am/pm cell merge)."""
    n_row_data = len(l_title_date)
    n_row_total = 2 + n_row_data  # row0 title, row1 header, rows2.. data
    n_col = len(_ASSIGN_COL_WIDTH)

    l_request = [
        {'updateSheetProperties': {'properties': {'sheetId': id_sheet, 'gridProperties': {'hideGridlines': True}},
                                   'fields': 'gridProperties.hideGridlines'}},
    ]
    for idx, width in enumerate(_ASSIGN_COL_WIDTH):
        l_request.append({'updateDimensionProperties': {
            'range': {'sheetId': id_sheet, 'dimension': 'COLUMNS', 'startIndex': idx, 'endIndex': idx + 1},
            'properties': {'pixelSize': width}, 'fields': 'pixelSize'}})

    # Base look for every header+data cell: font, bottom-aligned text, light-gray border. Applied
    # first so the more specific requests below only need to override what actually differs.
    l_request.append(_repeat_cell(id_sheet, 1, n_row_total, 0, n_col,
        {'textFormat': {'fontFamily': 'Calibri', 'fontSize': 11}, 'verticalAlignment': 'BOTTOM',
         'borders': _BORDER_ALL_SIDES},
        'userEnteredFormat(textFormat,verticalAlignment,borders)'))
    # Title row: bold, larger, centered, no border/background.
    l_request.append(_repeat_cell(id_sheet, 0, 1, 0, n_col,
        {'horizontalAlignment': 'CENTER', 'textFormat': {'fontFamily': 'Calibri', 'fontSize': 18, 'bold': True}},
        'userEnteredFormat(horizontalAlignment,textFormat)'))
    # Header row: dark background, white centered text.
    l_request.append(_repeat_cell(id_sheet, 1, 2, 0, n_col,
        {'backgroundColor': _COLOR_HEADER_BG, 'horizontalAlignment': 'CENTER',
         'textFormat': {'foregroundColor': _COLOR_HEADER_FG, 'fontFamily': 'Calibri', 'fontSize': 11}},
        'userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)'))
    # Data cells: every column but the date one is centered.
    l_request.append(_repeat_cell(id_sheet, 2, n_row_total, 1, n_col,
        {'horizontalAlignment': 'CENTER'}, 'userEnteredFormat.horizontalAlignment'))

    # Title cell, and the merged 'ECT' header.
    l_request.append(_merge(id_sheet, 0, 1, 0, n_col))
    l_request.append(_merge(id_sheet, 1, 2, 7, 9))

    # Holiday rows (weekends/national holidays): gray row fill, and the am/pm cells merged into
    # one (this system's 'day' duty already puts the same name in both, see convert_assignment).
    for i, title_date in enumerate(l_title_date):
        if not _is_holiday_title_date(title_date):
            continue
        r = 2 + i
        l_request.append(_repeat_cell(id_sheet, r, r + 1, 0, n_col,
            {'backgroundColor': _COLOR_HOLIDAY_BG}, 'userEnteredFormat.backgroundColor'))
        l_request.append(_merge(id_sheet, r, r + 1, 1, 3))

    return l_request


def _build_score_requests(id_sheet):
    l_request = [{'updateDimensionProperties': {
        'range': {'sheetId': id_sheet, 'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 12},
        'properties': {'pixelSize': 100}, 'fields': 'pixelSize'}}]
    l_request.append(_merge(id_sheet, 0, 1, 2, 7))   # '当月分' group header
    l_request.append(_merge(id_sheet, 0, 1, 7, 12))  # '今年度分' group header
    return l_request


def create_assignment_sheet(config, year_plan, month_plan):
    print('[1/3] Reading assignment and score...')
    services = get_services(config, SCOPE_DRIVE_CALENDAR)
    dp = prep_drive_paths(config, services, year_plan, month_plan, prefix_dir='', make_data_dir=False)
    d_assign_print = read_csv(services.drive, dp.id_month, 'assign_print.csv')
    d_score_print = read_csv(services.drive, dp.id_month, 'score_print.csv')

    def cell(v):
        return '' if pd.isna(v) else v

    print('[2/3] Creating assignment table...')
    # 'A当直' here is script/helper.py::convert_assignment's '当直' column (night duty, folding
    # in emnight) -- named 'A当直' to distinguish it from the separately-staffed 'B当直' rotation.
    # 'ECT' is a header merged across two columns in the reference sheet this mirrors: the left
    # (team-leader) half is filled by hand, the right half is this system's own 'ect' assignment.
    title = str(month_plan).translate(_ZENKAKU_DIGIT) + '月　精神神経科　日当直'
    header = ['日付', '午前日直', '午後日直', 'A当直', 'B当直', '日直OC', '当直OC', 'ECT', '']
    values_assign = [[title], header]
    l_title_date = d_assign_print['日付'].tolist()
    for _, row in d_assign_print.iterrows():
        values_assign.append([cell(row['日付']), cell(row['午前日直']), cell(row['午後日直']), cell(row['当直']),
                              '', cell(row['日直OC']), cell(row['当直OC']), '', cell(row['ECT'])])

    filename = 'assignment_{:04d}{:02d}'.format(year_plan, month_plan)
    sheet_name_assign = 'ver.' + dt.date.today().strftime('%Y%m%d')
    result_assign, _ = ensure_gsheet_tab(
        services.sheets, services.drive, dp.id_month, filename, sheet_name_assign, values_assign,
        build_requests=lambda id_sheet: _build_assignment_requests(id_sheet, l_title_date))
    if result_assign == 'tab_exists':
        print(sheet_name_assign + ' tab already exists in ' + filename + ' -- left untouched (avoids clobbering any hand edits).')
    else:
        print('Wrote ' + filename + ' tab ' + sheet_name_assign + '.')

    print('[3/3] Creating score table...')
    header_group1 = ['', '', '当月分', '', '', '', '', '今年度分']
    header_group2 = ['', '', '平日日直', '当直・休日日直', '日当直計', 'オンコール', 'ECT当番',
                     '平日日直', '当直・休日日直', '日当直計', 'オンコール', 'ECT当番']
    values_score = [header_group1, header_group2, d_score_print.columns.tolist()]
    for _, row in d_score_print.iterrows():
        values_score.append([cell(v) for v in row.tolist()])
    # A purely computed table (no hand-editable columns) -- safe to overwrite in place on rerun,
    # unlike the assignment tab above.
    result_score, _ = ensure_gsheet_tab(
        services.sheets, services.drive, dp.id_month, filename, 'score', values_score,
        build_requests=_build_score_requests, overwrite=True)
    print(filename + " tab 'score' " + ('overwritten' if result_score == 'tab_overwritten' else 'written') + '.')
    print('Done')


###############################################################################
# Draft (never send) notification emails linking to the 'assignment_<yyyymm>' Google Sheet
# create_assignment_sheet above creates -- one before publishing (a still-editable draft roster,
# soliciting a last look) and one after (the finalized roster). Both live in the "4. Notify" tab,
# between "Create Assignment Sheet" and "Publish to Calendar" (drop-in) and at the bottom (fixed)
# -- see script/gui.py::build_notify_panel. Neither touches the calendar itself.
###############################################################################
def _assignment_sheet_filename(year_plan, month_plan):
    return 'assignment_{:04d}{:02d}'.format(year_plan, month_plan)


def _button_pair(services, id_config, url_sheet, dict_email):
    """Build the two HTML buttons every drop-in/fixed notification body embeds: {button} (links
    to the assignment Google Sheet) and {button_replace} (links to the shift-swap request form,
    dutyshift/config/config.json's url_replace_form -- see script/helper.py::load_drive_config)."""
    url_replace_form = load_drive_config(services.drive, id_config)['url_replace_form']
    str_button = str_email_button_html.format(url=url_sheet, label=dict_email['button_label'])
    str_button_replace = str_email_button_html.format(url=url_replace_form, label=dict_email['button_label_replace'])
    return str_button, str_button_replace


def draft_dropin_notification(config, year_plan, month_plan, str_deadline):
    """Draft a notification email to active doctors linking to this month's assignment Google
    Sheet, meant to be sent while the roster is still a work-in-progress draft -- i.e. any time
    after 'Create Assignment Sheet' and before 'Publish to Calendar'. str_deadline (the
    correction deadline set next to the 'Draft Drop-in Notification' button, see
    script/gui.py::build_notify_panel) is embedded in the subject."""
    services = get_services(config, SCOPE_DRIVE_GMAIL)
    dp = prep_drive_paths(config, services, year_plan, month_plan, prefix_dir='', make_data_dir=False)

    print('[1/2] Looking up the assignment sheet...')
    filename = _assignment_sheet_filename(year_plan, month_plan)
    url_sheet = get_file_web_link(services.drive, dp.id_month, filename)
    if not url_sheet:
        print('Assignment sheet not found -- run "Create Assignment Sheet" first.')
        return

    print('[2/2] Drafting notification email...')
    id_config = dp.cache.get_or_create(services.drive, 'dutyshift/config')
    d_member = read_member(services.drive, services.sheets, id_config, year_plan, month_plan)
    d_member_active = d_member.loc[d_member['active'] == True, :]
    l_email_active = [email for email in d_member_active['email'].tolist()
                      if isinstance(email, str) and email.strip()]
    n_missing_email = len(d_member_active) - len(l_email_active)
    if n_missing_email > 0:
        print('[WARNING]', n_missing_email, 'active doctor(s) have no email on file -- excluded from the draft.')
    if len(l_email_active) == 0:
        print('No active doctors with an email on file -- skipping notification email draft.')
        return

    id_template = dp.cache.get_or_create(services.drive, 'dutyshift/template')
    dict_email = load_email_template(services.drive, id_template, 'dropin')
    str_button, str_button_replace = _button_pair(services, id_config, url_sheet, dict_email)
    str_body = dict_email['body'].format(button=str_button, button_replace=str_button_replace,
                                         deadline=str_deadline, year=year_plan, month=month_plan)
    message = MIMEText(str_body, 'html')
    message['bcc'] = ', '.join(l_email_active)
    message['subject'] = dict_email['subject'].format(deadline=str_deadline, year=year_plan, month=month_plan)
    str_raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    services.gmail.users().drafts().create(userId='me', body={'message': {'raw': str_raw}}).execute()
    print('Drafted drop-in notification email to', len(l_email_active), 'active doctor(s) (not sent).')
    print('Done')


def draft_fixed_notification(config, year_plan, month_plan):
    """Draft a notification email to active doctors plus any extra recipients configured in
    dutyshift/config/config.json's l_email_extra_fixed (see script/helper.py::load_drive_config),
    announcing the finalized duty roster and linking to this month's assignment Google Sheet."""
    services = get_services(config, SCOPE_DRIVE_GMAIL)
    dp = prep_drive_paths(config, services, year_plan, month_plan, prefix_dir='', make_data_dir=False)

    print('[1/2] Looking up the assignment sheet...')
    filename = _assignment_sheet_filename(year_plan, month_plan)
    url_sheet = get_file_web_link(services.drive, dp.id_month, filename)
    if not url_sheet:
        print('Assignment sheet not found -- run "Create Assignment Sheet" first.')
        return

    print('[2/2] Drafting notification email...')
    id_config = dp.cache.get_or_create(services.drive, 'dutyshift/config')
    l_email_extra = load_drive_config(services.drive, id_config).get('l_email_extra_fixed', [])
    d_member = read_member(services.drive, services.sheets, id_config, year_plan, month_plan)
    d_member_active = d_member.loc[d_member['active'] == True, :]
    l_email_active = [email for email in d_member_active['email'].tolist()
                      if isinstance(email, str) and email.strip()]
    n_missing_email = len(d_member_active) - len(l_email_active)
    if n_missing_email > 0:
        print('[WARNING]', n_missing_email, 'active doctor(s) have no email on file -- excluded from the draft.')
    l_email_all = l_email_active + [email for email in l_email_extra if email not in l_email_active]
    if len(l_email_all) == 0:
        print('No recipients (active doctors or configured extras) with an email on file -- skipping notification email draft.')
        return

    id_template = dp.cache.get_or_create(services.drive, 'dutyshift/template')
    dict_email = load_email_template(services.drive, id_template, 'fixed')
    str_button, str_button_replace = _button_pair(services, id_config, url_sheet, dict_email)
    str_body = dict_email['body'].format(button=str_button, button_replace=str_button_replace,
                                         year=year_plan, month=month_plan)
    message = MIMEText(str_body, 'html')
    message['bcc'] = ', '.join(l_email_all)
    message['subject'] = dict_email['subject'].format(year=year_plan, month=month_plan)
    str_raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    services.gmail.users().drafts().create(userId='me', body={'message': {'raw': str_raw}}).execute()
    print('Drafted fixed notification email to', len(l_email_all), 'recipient(s) (',
         len(l_email_active), 'active doctor(s) +', len(l_email_extra), 'extra) (not sent).')
    print('Done')


def compare_event(d_assign_date_duty, d_event_exist):
    l_date_duty_assigned = d_assign_date_duty.loc[~np.isnan(d_assign_date_duty['id_member']), 'date_duty'].tolist()
    l_date_duty_delete = [dd for dd in d_event_exist['date_duty'].tolist() if dd not in l_date_duty_assigned]
    l_date_duty_change = []
    l_date_duty_add = []
    for id, row in d_assign_date_duty.loc[~np.isnan(d_assign_date_duty['id_member']), :].iterrows():
        date_duty = row['date_duty']
        id_member = int(row['id_member'])
        id_member_calendar = d_event_exist.loc[d_event_exist['date_duty'] == date_duty, 'id_member'].tolist()
        if len(id_member_calendar) > 0:
            if id_member_calendar[0] != id_member:
                l_date_duty_change.append(date_duty)
        else:
            l_date_duty_add.append(date_duty)

    return l_date_duty_delete, l_date_duty_change, l_date_duty_add


def update_calendar(config, year_plan, month_plan, num_retries=5):
    services = get_services(config, SCOPE_DRIVE_CALENDAR)
    dp = prep_drive_paths(config, services, year_plan, month_plan, prefix_dir='', make_data_dir=False)
    # id_calendar (target Google Calendar) and url_replace_form (embedded in each event's
    # description) live on Drive (dutyshift/config/config.json), not in code -- see
    # script/helper.py::load_drive_config. Read fresh on every publish.
    id_config = dp.cache.get_or_create(services.drive, 'dutyshift/config')
    dict_drive_config = load_drive_config(services.drive, id_config)
    id_calendar = dict_drive_config['id_calendar']
    url_replace_form = dict_drive_config['url_replace_form']
    d_member = read_csv(services.drive, dp.id_month, 'member.csv')

    # Access calendar
    service_calendar = services.calendar

    # Read events on G calendar
    d_assign_calendar = list_duty(service_calendar, id_calendar, year_plan, month_plan, d_member, num_retries)

    # Read target assignment
    d_assign_date_duty = read_csv(services.drive, dp.id_month, 'assign_date_duty.csv')

    # Compare existing and target events
    l_date_duty_delete, l_date_duty_change, l_date_duty_add = compare_event(d_assign_date_duty, d_assign_calendar)

    # Delete events
    l_result_delete = delete_duty(service_calendar, id_calendar, l_date_duty_delete + l_date_duty_change, d_assign_calendar, num_retries)

    # Add events
    d_date_duty_add = d_assign_date_duty.loc[d_assign_date_duty['date_duty'].isin(l_date_duty_add + l_date_duty_change), :]
    d_member = read_csv(services.drive, dp.id_month, 'member.csv')
    d_availability = read_member_matrix_csv(services.drive, dp.id_month, 'availability.csv')
    d_time_duty = pd.DataFrame(duty_time_table(dict_duty_info))

    # Single pass over all additions/changes: with num_retries applying googleapiclient's own
    # randomized-exponential-backoff to each call (see script/parameter.py::n_retry_calendar),
    # a genuine rate-limit hit is retried in place within seconds rather than needing a
    # preventive multi-minute pause between member-sized batches.
    l_result_add = add_duty(service_calendar, id_calendar, d_date_duty_add, d_member, d_time_duty, d_availability, num_retries, url_replace_form)

    # Assert result
    d_assign_calendar = list_duty(service_calendar, id_calendar, year_plan, month_plan, d_member, num_retries)
    l_date_duty_delete, l_date_duty_change, l_date_duty_add = compare_event(d_assign_date_duty, d_assign_calendar)
    if len(l_date_duty_delete) > 0:
        print('Duty not deleted ', l_date_duty_delete)
    if len(l_date_duty_change) > 0:
        print('Duty not changed ', l_date_duty_change)
    if len(l_date_duty_add) > 0:
        print('Duty not added ', l_date_duty_add)
    if len(l_date_duty_delete) + len(l_date_duty_change) + len(l_date_duty_add) == 0:
        print('Confirmed update')
    print('Done')


def add_duty(service, id_calendar, d_date_duty, d_member, d_time_duty, d_availability, num_retries=5,
            url_replace_form='https://forms.gle/oxvdt8CNkW6iPPFm6'):

    #d_member['id_member'] = d_member.index
    #d_member = d_member.reset_index()
    d_date_duty = pd.merge(d_date_duty, d_member[['id_member','name_jpn_full','email']], on='id_member', how='left')
    d_date_duty = pd.merge(d_date_duty, d_time_duty, on='duty', how='left')

    l_result = []
    for _, row in d_date_duty.iterrows():
        date_duty = row['date_duty']
        title_duty = row['duty_jpn']
        year = int(row['year'])
        month = int(row['month'])
        date = int(row['date'])
        duty = row['duty']
        id_member = int(row['id_member'])
        name_member = row['name_jpn_full'].replace('　',' ')
        email = row['email']
        str_start = row['start']
        str_end = row['end']
        t_start = (dt.datetime(year=year, month=month, day=date) +\
                dt.timedelta(hours=int(str_start[0:2]), minutes=int(str_start[3:5]))).isoformat()
        t_end = (dt.datetime(year=year, month=month, day=date) +\
                dt.timedelta(hours=int(str_end[0:2]), minutes=int(str_end[3:5]))).isoformat()
        s_id_member_proxy = d_availability.loc[d_availability.index == date_duty,:].reset_index(drop=True).squeeze().iloc[1:]

        l_id_member_proxy = [int(id) for id in s_id_member_proxy.loc[s_id_member_proxy > 0].index.tolist()]
        d_member_proxy = d_member.loc[d_member['id_member'].isin(l_id_member_proxy),['id_member', 'name_jpn_full', 'designation']]
        # Consider designation status for day and night
        if duty in ['day','night']:
            designation_member = d_member.loc[d_member['id_member'] == id_member, 'designation'].tolist()[0]
            l_id_member_proxy = d_member_proxy.loc[d_member_proxy['designation'] == designation_member, 'id_member'].tolist()
            l_id_member_proxy_sub = d_member_proxy.loc[d_member_proxy['designation'] != designation_member, 'id_member'].tolist()
        else:
            l_id_member_proxy_sub = []
        l_id_member_proxy = [id for id in l_id_member_proxy if id != id_member]
        if len(l_id_member_proxy) > 0:
            l_member_proxy = d_member_proxy.loc[d_member_proxy['id_member'].isin(l_id_member_proxy),'name_jpn_full'].tolist()
            l_member_proxy = [name.replace('　',' ') for name in l_member_proxy]
            str_member_proxy = ','.join(l_member_proxy)
        else:
            str_member_proxy = ''
        if len(l_id_member_proxy_sub) > 0:
            l_member_proxy_sub = d_member_proxy.loc[d_member_proxy['id_member'].isin(l_id_member_proxy_sub),'name_jpn_full'].tolist()
            l_member_proxy_sub = [name.replace('　',' ') for name in l_member_proxy_sub]
            str_member_proxy = str_member_proxy + '(,' + ','.join(l_member_proxy_sub) + ')'
        if str_member_proxy == '':
            str_member_proxy == 'なし'

        description = name_member + '先生ご担当\n代理候補(敬称略): ' + str_member_proxy +\
                    '\n変更申請: ' + url_replace_form +\
                    '\nhttps://github.com/atiroms/dutyshift で自動生成'

        body_event = {'summary': title_duty,
                    'location': '東大病院',
                    'start': {'dateTime': t_start, 'timeZone': 'Asia/Tokyo'},
                    'end': {'dateTime': t_end, 'timeZone': 'Asia/Tokyo'},
                    'attendees': [{'email': email}],
                    #'attendees': [{'email': email, 'displayName':name_member}],
                    #'attendees': [{'email': email, 'responseStatus':'accepted'}],
                    'description': description
                    }
        result_event = service.events().insert(calendarId=id_calendar, body=body_event).execute(num_retries=num_retries)
        l_result.append(result_event)

    return l_result


def delete_duty(service_calendar, id_calendar, l_date_duty_delete, d_event_exist, num_retries=5):
    l_id_event_delete = []
    for date_duty in l_date_duty_delete:
        id_event = d_event_exist.loc[d_event_exist['date_duty'] == date_duty, 'id_event'].tolist()[0]
        l_id_event_delete.append(id_event)

    l_result = []
    for id_event in l_id_event_delete:
        result_delete = service_calendar.events().delete(calendarId=id_calendar, eventId=id_event).execute(num_retries=num_retries)
        l_result.append(result_delete)

    return l_result


def list_duty(service_calendar, id_calendar, year, month, d_member, num_retries=5):
    #d_member = d_member.reset_index()

    if month == 12:
        year_end = year + 1
        month_end = 1
    else:
        year_end = year
        month_end = month + 1

    # Extract from G calendar
    time_start = str(year) + '-' + str(month).zfill(2) + '-01T00:00:00Z'
    time_end = str(year_end) + '-' + str(month_end).zfill(2) + '-01T00:00:00Z'
    l_event = service_calendar.events().list(
        calendarId=id_calendar,
        timeMin=time_start,
        timeMax=time_end,
        maxResults=1000,
        singleEvents=True,
        orderBy='startTime'
    ).execute(num_retries=num_retries)
    d_event = pd.DataFrame(l_event.get('items', []))

    # Convert result
    d_time_duty = pd.DataFrame(duty_time_table(dict_duty_info))
    l_assign_calendar = []
    for id, row in d_event.iterrows():
        str_ymd = row['start']['dateTime']
        #duty = d_time_duty.loc[d_time_duty['duty_jpn'] == row['summary'], 'duty'].tolist()[0]
        duty = d_time_duty.loc[d_time_duty['duty_jpn'] == row['summary'], 'duty'].tolist()
        if len(duty) > 0:
            duty = duty[0]
            name_jpn_full = row['description'].split('先生')[0]
            #email = row['attendees'][0]['email']
            id_member = d_member.loc[d_member['name_jpn_full'] == name_jpn_full, 'id_member'].tolist()[0]
            name_jpn = d_member.loc[d_member['name_jpn_full'] == name_jpn_full, 'name_jpn'].tolist()[0]
            l_assign_calendar.append({'date_duty': str(int(str_ymd[8:10])) + '_' + duty,
                                    'year': int(str_ymd[0:4]),
                                    'month': int(str_ymd[5:7]),
                                    'date': int(str_ymd[8:10]),
                                    'duty': duty,
                                    'id_member': id_member,
                                    'name_jpn': name_jpn,
                                    'id_event': row['id']})

    if len(l_assign_calendar) > 0:
        d_assign_calendar = pd.DataFrame(l_assign_calendar)
    else:
        d_assign_calendar = pd.DataFrame(columns=['date_duty', 'year', 'month', 'date', 'duty', 'id_member', 'name_jpn', 'id_event'])

    return d_assign_calendar
