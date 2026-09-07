
###############################################################################
# Libraries
###############################################################################
import datetime, calendar, itertools
import numpy as np, pandas as pd
from math import ceil
from pulp import LpProblem, LpVariable, LpStatus, lpSum, lpDot, value
from ortoolpy import addvars
from script.drive_io import (
    read_csv, write_csv, read_gsheet, read_json, write_json, check_form_exists, list_gsheet_tabs,
    copy_gsheet_tab, list_month_folders, month_folder_path, get_services, prep_drive_paths,
    SCOPE_DRIVE_FORMS,
)
from script.parameter import dict_class_duty


###############################################################################
# Derived views of script/parameter.py's base tables. parameter.py holds base data only
# (dict_duty_info, dict_class_duty, dict_score_duty, dict_score_classes); every function below that
# needs a particular derived shape of that data (duty sort order, Japanese labels, a class_duty
# name list, the class_duty score-weight table, ...) calls the matching function here to cut out
# just the part it needs, rather than importing an already-derived global.
###############################################################################
def duty_order(dict_duty_info):
    """duty -> sort-order int."""
    return dict(zip(dict_duty_info['duty'], dict_duty_info['order']))


def duty_jpn_labels(dict_duty_info, include_ect=False):
    """duty -> Japanese label. ECT is excluded by default: it has no dedicated availability
    question on the Google Form -- script/form.py skips generating a question/column for it,
    inferring its availability from the 'am' question on ECT days instead (see
    script/collect.py). Pass include_ect=True for contexts that do want it (e.g. labeling a
    manual-assignment dropdown in script/gui.py)."""
    return {duty: jpn for duty, jpn in zip(dict_duty_info['duty'], dict_duty_info['duty_jpn'])
            if include_ect or duty != 'ect'}


def duty_time_table(dict_duty_info):
    """{'duty', 'duty_jpn', 'start', 'end'} table (includes 'ect', unlike duty_jpn_labels'
    default) -- ready to build a DataFrame of duty clock times from."""
    return {'duty': dict_duty_info['duty'], 'duty_jpn': dict_duty_info['duty_jpn'],
            'start': dict_duty_info['start'], 'end': dict_duty_info['end']}


def duty_holiday_flags():
    """{holiday: [duty, ...]} -- the fixed structural rule for which of the 8 raw duties occur
    on a non-holiday weekday (False) vs a holiday/weekend day (True). This is prep_calendar's
    own rule for building d_cal, pulled out so script/form.py can derive each Google Form
    section's weekly-pattern grid rows (weekday x duty) from the same source of truth instead of
    duplicating it. 'ect' and 'emnight' are deliberately absent from both lists -- they're
    irregular/date-specific (l_day_ect, the em schedule), not simple weekday/holiday facts, so
    they never appear in the weekly-pattern grid; only the per-date grids handle them."""
    return {False: ['am', 'pm', 'night', 'ocnight'], True: ['day', 'night', 'ocday', 'ocnight']}


def build_weekly_pattern_rows(l_duty_section, dict_duty_info, dict_jpnday):
    """Row labels (e.g. '月　当直') for a Google Form section's weekly-pattern grid: for each
    weekday Mon..Sun, the duties in l_duty_section (a section's title(s) eligible duties, from
    dict_title_duty) that also occur on that weekday per duty_holiday_flags() (weekday rule for
    Mon-Fri, holiday rule for Sat/Sun), in dict_duty_info's duty order. Used by
    script/form.py::prepare_form to build each section's weekly-pattern grid from scratch."""
    dict_duty_holiday_flag = duty_holiday_flags()
    dict_order = duty_order(dict_duty_info)
    dict_jpn = duty_jpn_labels(dict_duty_info)
    l_row = []
    for wday in range(7):
        is_holiday = wday in [5, 6]
        l_duty_wday = [duty for duty in dict_duty_holiday_flag[is_holiday] if duty in l_duty_section]
        l_duty_wday = sorted(l_duty_wday, key=lambda duty: dict_order[duty])
        for duty in l_duty_wday:
            l_row.append(dict_jpnday[wday] + '　' + dict_jpn[duty])
    return l_row


def class_duty_names(dict_class_duty):
    """Unique class_duty names, in first-appearance order of dict_class_duty (order matters for
    output column ordering, e.g. in the member Google Sheet / lim_*.csv columns)."""
    return list(dict.fromkeys(dict_class_duty['class']))


def derive_score_class_constants(dict_score_duty, dict_class_duty, dict_score_classes):
    """For each score axis in dict_score_classes (score -> list of class_duty names), solve the
    per-class_duty constant such that summing constants over the axis's classes reproduces
    dict_score_duty's per-duty weight for that axis. Only dict_class_duty rows with date == 'all'
    participate: weekday/holiday-qualified classes (night_wd, daynight_hd, ...) exist purely for
    per-doctor count limits and never carry score weight.
    """
    d_score_duty = pd.DataFrame(dict_score_duty).set_index('duty')
    d_class_duty_all = pd.DataFrame(dict_class_duty)
    d_class_duty_all = d_class_duty_all[d_class_duty_all['date'] == 'all']

    l_constant = []
    for score, l_class in dict_score_classes.items():
        l_duty = sorted(set(d_class_duty_all.loc[d_class_duty_all['class'].isin(l_class), 'duty']))
        m_incidence = np.array([[duty in set(d_class_duty_all.loc[d_class_duty_all['class'] == class_duty, 'duty'])
                                  for class_duty in l_class] for duty in l_duty], dtype=float)
        v_target = d_score_duty.loc[l_duty, score].to_numpy(dtype=float)
        v_constant, _, _, _ = np.linalg.lstsq(m_incidence, v_target, rcond=None)
        v_constant = np.round(v_constant, 6)
        if not np.allclose(m_incidence @ v_constant, v_target):
            raise ValueError(
                "dict_class_duty can't exactly reproduce dict_score_duty['" + score + "'] via classes " +
                str(l_class) + " -- dict_score_duty and dict_class_duty have drifted out of sync, or " +
                "the score->classes mapping in dict_score_classes needs updating to match.")
        l_constant.extend(v_constant.tolist())
    return l_constant


def score_class_table(dict_score_duty, dict_class_duty, dict_score_classes):
    """dict_score_class: score weight per class_duty, per score axis -- derived from
    dict_score_duty (per-duty weights) + dict_class_duty via derive_score_class_constants, so an
    edit to dict_score_duty can't silently desync assignment-count fairness (stage 1) from
    actual assignment scoring (stage 2)."""
    l_pair = [(score, class_duty) for score, l_class in dict_score_classes.items() for class_duty in l_class]
    return {'score': [score for score, _ in l_pair],
            'class': [class_duty for _, class_duty in l_pair],
            'constant': derive_score_class_constants(dict_score_duty, dict_class_duty, dict_score_classes)}


###############################################################################
# Print candidate replacement
###############################################################################
def print_candidate_replacement(service_drive, id_month, dict_class_duty, d_deviation_summary, d_assign_date_duty, d_assign_member, d_closeduty):
    d_availability_member = read_csv(service_drive, id_month, 'availability_member.csv')
    d_availability_duty = read_csv(service_drive, id_month, 'availability_duty.csv', index_col=0)
    d_class_duty = pd.DataFrame(dict_class_duty)
    ll_result = []
    for i0, col0 in d_deviation_summary.iterrows():
        id_member = col0['id_member']
        str_member = str(id_member) + '_' + col0['name_jpn']
        class_deviant = col0['class_duty']
        duty_deviant = d_class_duty.loc[d_class_duty['class'] == class_deviant, 'duty'].tolist()
        if col0['deviation_exact'] > 0:
            duty_assigned = d_assign_date_duty.loc[(d_assign_date_duty['id_member'] == id_member) & (d_assign_date_duty['duty'].isin(duty_deviant)), ]
            l_result = []
            for i1, col1 in duty_assigned.iterrows():
                date_duty = col1['date_duty']
                # availability_duty.csv has a blank (NaN, not str) 'l_member' for a date_duty no
                # one was available for -- can still show up here if it was only filled via a
                # manual override (assign_manual.csv). No one to suggest as a proxy in that case.
                if type(d_availability_duty.loc[date_duty, 'l_member']) == str:
                    l_member = d_availability_duty.loc[date_duty, 'l_member'].split(', ')
                    l_member_jpn = d_availability_duty.loc[date_duty, 'l_member_jpn'].split(', ')
                    l_member_proxy = [i2 + '_' + name for i2, name in zip(l_member, l_member_jpn) if int(i2) != int(id_member)]
                    str_member_proxy = ', '.join(l_member_proxy)
                else:
                    str_member_proxy = ''
                l_result.append([date_duty, str_member_proxy])
            ll_result.append(['excess', str_member, class_deviant, l_result])
        elif col0['deviation_exact'] < 0:
            l_duty_available = d_availability_member.loc[d_availability_member['id_member'] == id_member, 'l_date_duty'].tolist()[0].split(', ')
            l_duty_available = [duty for duty in l_duty_available if duty.split('_')[1] in duty_deviant]
            l_duty_assigned = d_assign_member.loc[d_assign_member['id_member'] == id_member, 'duty_all'].tolist()[0].split(', ')
            l_duty_available = [duty for duty in l_duty_available if duty not in l_duty_assigned]
            if len(l_duty_available) > 0:
                str_duty = ', '.join(l_duty_available)
            else:
                str_duty = ''
            ll_result.append(['deficiency', str_member, class_deviant, str_duty])

    for l_result in ll_result:
        if l_result[0] == 'excess':
            print('Excess assignment in ' + l_result[1] + ', ' + l_result[2] + ', consider replacing:')
            for replacement in l_result[3]:
                print('  ' + replacement[0] + ' -> ' + replacement[1])
    for l_result in ll_result:
        if l_result[0] == 'deficiency':
            print('Deficient assignment in ' + l_result[1] + ', ' + l_result[2] + ', consider assigning to:')
            print('  ' + l_result[3])

    l_member = sorted(list(set(d_closeduty['id_member'].tolist())))
    ll_result = []
    for id_member in l_member:
        d_closeduty_temp = d_closeduty.loc[d_closeduty['id_member'] == id_member, ]
        str_member = str(id_member) + '_' + d_closeduty_temp['name_jpn'].iloc[0]
        l_result = []
        for i0, col0 in d_closeduty_temp.iterrows():
            date_duty = col0['date_duty']
            if type(d_availability_duty.loc[date_duty, 'l_member']) == str:
                l_member_proxy = d_availability_duty.loc[date_duty, 'l_member'].split(', ')
                l_member_proxy_jpn = d_availability_duty.loc[date_duty, 'l_member_jpn'].split(', ')
                l_member_proxy = [i2 + '_' + name for i2, name in zip(l_member_proxy, l_member_proxy_jpn) if int(i2) != int(id_member)]
                str_member_proxy = ', '.join(l_member_proxy)
                l_result.append([date_duty, str_member_proxy])
        ll_result.append([str_member, l_result])

    for l_result in ll_result:
        print('Close assignment in ' + l_result[0] + ' consider replacing:')
        for replacement in l_result[1]:
            print('  ' + replacement[0] + ' -> ' + replacement[1])


################################################################################
# Read response from Google forms
################################################################################
def read_form_response(services, path_form):
    service_drive = services.drive
    service_forms = services.forms

    # Check if form exists
    id_form = check_form_exists(service_drive, path_form)

    # Fetch the form metadata (to map questionId → question title)
    form = service_forms.forms().get(formId=id_form).execute()
    # Build a mapping of questionId → title
    qid2title = {}
    for item in form.get('items', []):
        if 'questionItem' in item:
            q = item['questionItem']['question']
            qid = q.get('questionId')
            title = item.get('title','')
            if qid:
                qid2title[qid] = title
        elif 'questionGroupItem' in item:
            questions = item['questionGroupItem']['questions']
            title = item.get('title','')
            for q in questions:
                qid = q.get('questionId')
                title_2 = q['rowQuestion'].get('title', '')
                if qid:
                    qid2title[qid] = title + '[' + title_2 + ']'

    # Pull all responses
    l_response = []
    l_timestamp = []
    page_token = None
    while True:
        resp = service_forms.forms().responses().list(
            formId=id_form,
            pageToken=page_token,
            pageSize=100  # up to 5000 max
        ).execute()
        for r in resp.get('responses', []):
            timestamp = r['lastSubmittedTime']
            # each answer is keyed by questionId
            ans = {}
            for qid, answer in r['answers'].items():
                # textAnswers vs choiceAnswers:
                if 'textAnswers' in answer:
                    # concatenate multiple text answers if any
                    vals = [t['value'] for t in answer['textAnswers']['answers']]
                    ans[qid] = ' | '.join(vals)
                elif 'choiceAnswers' in answer:
                    ans[qid] = answer['choiceAnswers']
                else:
                    # other types (e.g. fileUpload), fallback to raw
                    ans[qid] = str(answer)
            l_response.append(ans)
            l_timestamp.append(timestamp)
        page_token = resp.get('nextPageToken')
        if not page_token:
            break

    # Build DataFrame
    d_response = pd.concat([pd.DataFrame(columns=qid2title.keys()), pd.DataFrame.from_records(l_response)], axis=0)
    d_response.columns = qid2title.values()
    d_response = pd.concat([pd.DataFrame({'Timestamp': l_timestamp}), d_response], axis=1)

    return d_response


################################################################################
# Wire up Google Form navigation (goToSectionId) after the items it targets exist.
#
# The Forms API never lets a caller choose a new item's itemId (it's always server-generated,
# returned only in the createItem reply), and per-section "after this page" navigation can only
# be attached to a choice question's option -- there's no unconditional per-section default
# (PageBreakItem itself has no navigation field). So script/form.py::prepare_form builds a form
# in two passes: first create every item (name dropdown, per-section grids/questions, the
# section-end "next" question), then -- once every item's real itemId is known -- come back with
# the two functions below to fill in the goToSectionId values that couldn't be set at creation.
################################################################################

def generate_request_update_name_choices(id_form, service, d_member, dict_sectionid_title, id_item_name):
    """Build the single request that replaces the name dropdown's options with this month's
    active doctors, each option's goToSectionId routing to the Google Form section matching
    that doctor's title_short (dict_sectionid_title: title_short -> that section's pageBreakItem
    itemId, built from parameter.py's l_form_section + the itemIds returned by the create pass --
    see script/form.py::prepare_form; several title_short values can map to the same section id,
    e.g. assist_subleader/assist_kokoro sharing one section). Without this, a doctor who
    joined/left/changed title would need the form hand-edited.

    Returns (request, l_title_unmapped): l_title_unmapped lists the title_short value(s) of any
    active doctor not covered by dict_sectionid_title (a typo, or a title newly added to
    config/member but not yet to l_form_section/dict_title_duty) -- those doctors are silently
    excluded from the option list, so the caller should warn about them rather than let them
    quietly vanish from the form."""
    form = service.forms().get(formId=id_form).execute()
    position_item = next(i for i, itm in enumerate(form['items']) if itm['itemId'] == id_item_name)

    d_member_active = d_member.loc[d_member['active'] == True, :]
    l_title_unmapped = sorted(set(
        d_member_active.loc[~d_member_active['title_short'].isin(dict_sectionid_title.keys()), 'title_short'].tolist()
    ))
    d_member_mapped = d_member_active.loc[d_member_active['title_short'].isin(dict_sectionid_title.keys()), :]

    new_options = [
        {"value": row['name_jpn_full'], "goToSectionId": dict_sectionid_title[row['title_short']]}
        for _, row in d_member_mapped.iterrows()
    ]

    request = {
        "updateItem": {
            "location": {"index": position_item},
            "item": {
                "itemId": id_item_name,
                "questionItem": {"question": {"choiceQuestion": {"options": new_options}}}
            },
            "updateMask": "questionItem.question.choiceQuestion.options"
        }
    }
    return request, l_title_unmapped


def generate_request_update_section_nav(id_form, service, id_item_confirm, id_section_target):
    """Build the single request that points a section-end '次へ' confirmation question's one
    option at id_section_target (the closing survey section's itemId) -- see
    script/form.py::prepare_form. Mirrors generate_request_update_name_choices's shape."""
    form = service.forms().get(formId=id_form).execute()
    position_item = next(i for i, itm in enumerate(form['items']) if itm['itemId'] == id_item_confirm)

    request = {
        "updateItem": {
            "location": {"index": position_item},
            "item": {
                "itemId": id_item_confirm,
                "questionItem": {"question": {"choiceQuestion": {
                    "options": [{"value": "次へ", "goToSectionId": id_section_target}]
                }}}
            },
            "updateMask": "questionItem.question.choiceQuestion.options"
        }
    }
    return request


################################################################################
# Delete date_duty for which no one is available, and not manually assigned
################################################################################
def skip_date_duty(d_date_duty, d_availability, d_availability_ratio, d_assign_manual, l_date_duty_skip_manual, verbose):
    l_date_duty_unavailable = d_availability_ratio.loc[d_availability_ratio['available'] == 0,:].index.tolist()
    l_date_duty_unavailable_notoc = [date_duty for date_duty in l_date_duty_unavailable if not 'oc' in date_duty]
    l_date_duty_manual_assign = d_assign_manual.loc[~d_assign_manual['id_member'].isna(), 'date_duty'].tolist()
    # Slots with a manual assignment aren't actually short of members -- exclude them from what
    # gets reported as "no member available for" (they're reported separately below instead).
    l_date_duty_unavailable_print = [date_duty for date_duty in l_date_duty_unavailable if date_duty not in l_date_duty_manual_assign]
    l_date_duty_unavailable_notoc_print = [date_duty for date_duty in l_date_duty_unavailable_notoc if date_duty not in l_date_duty_manual_assign]
    if len(l_date_duty_unavailable_print) > 0:
        if verbose:
            print('No member available for:', l_date_duty_unavailable_print)
            print('of which', l_date_duty_unavailable_notoc_print, 'are not OC')
    if len(l_date_duty_manual_assign) > 0:
        if verbose:
            print('Manually assigned member(s) for:', l_date_duty_manual_assign)
        for date_duty in l_date_duty_manual_assign:
            id_member = d_assign_manual.loc[d_assign_manual['date_duty'] == date_duty, 'id_member'].tolist()[0]
            d_availability.loc[date_duty, id_member] = 1
    # Skip date_duty for which (no one is available, except OC), and not manually assigned
    l_date_duty_skip = [date_duty for date_duty in l_date_duty_unavailable_notoc if not date_duty in l_date_duty_manual_assign]

    # Skip duties in specified date
    l_date_duty = d_date_duty.loc[:, 'date_duty'].tolist()
    l_date_duty_skip_spec = []
    for date_duty_skip_manual in l_date_duty_skip_manual:
        if date_duty_skip_manual.endswith('_'): # if date_duty is e.g. '4_', skip all date_duty's that starts wtih '4_'
            l_date_duty_skip_spec += [date_duty for date_duty in l_date_duty if date_duty.startswith(date_duty_skip_manual)]
        else:
            l_date_duty_skip_spec += [date_duty for date_duty in l_date_duty if date_duty == date_duty_skip_manual]
    if len(l_date_duty_skip_spec) > 0:
        if verbose:
            print('Manually skipped assignment for:', l_date_duty_skip_spec)

    l_date_duty_skip = list(set(l_date_duty_skip + l_date_duty_skip_spec))
    l_date_duty_skip = [date_duty for date_duty in l_date_duty if date_duty in l_date_duty_skip]

    if len(l_date_duty_skip) > 0:
        if verbose:
            print('In total, skipping assignment for:', l_date_duty_skip)

    d_date_duty = d_date_duty.loc[~d_date_duty['date_duty'].isin(l_date_duty_skip),:]
    d_availability = d_availability.loc[~d_availability.index.isin(l_date_duty_skip),:]
    return d_date_duty, d_availability, l_date_duty_unavailable, l_date_duty_unavailable_notoc, l_date_duty_manual_assign, l_date_duty_skip


################################################################################
# Read config/member (native Google Sheet, one tab per month)
################################################################################
def member_sheet_name(year, month):
    """Single source of truth for config/member's per-month tab naming convention (mirrors
    drive_io.py::month_folder_path's role for the Drive folder layout)."""
    return 'member_' + str(year).zfill(4) + str(month).zfill(2)


def read_member(service_drive, service_sheets, id_config, year_plan, month_plan):
    name_sheet = member_sheet_name(year_plan, month_plan)
    # header=0 matches the pandas.read_excel default the old xlsx-based read_member relied on
    # (via drive_io.py::read_excel) -- keeps this function's row offsets below unchanged.
    d_member_src = read_gsheet(service_sheets, service_drive, id_config, 'member', name_sheet, header=0)
    d_member = d_member_src.iloc[3:,:]
    d_member.columns = d_member_src.iloc[2,:].tolist()
    d_member.index = [i for i in range(len(d_member))]
    d_member = d_member.copy()
    d_member.loc[:, 'name_jpn_full'] = d_member.loc[:, 'name_jpn_full'].str.replace('　',' ')

    return d_member


def ensure_member_sheet(service_drive, service_sheets, id_config, year_plan, month_plan):
    """Best-effort: if config/member doesn't yet have a tab for year_plan/month_plan, copy
    forward the nearest prior member_<yyyymm> tab (skipping gaps, same pattern
    script/gui.py::_load_last_month_solver_params uses for solver-parameter audit records) as a
    starting point for that month's per-doctor parameter edits. Never overwrites an existing
    destination tab, never raises -- this is a convenience, not a required step. Prints a
    one-line status regardless of outcome."""
    name_dst = member_sheet_name(year_plan, month_plan)
    try:
        l_sheet = list_gsheet_tabs(service_sheets, service_drive, id_config, 'member')
    except Exception:
        print('[WARNING] Could not read config/member to check/copy this month\'s tab.')
        return

    if name_dst in l_sheet:
        print('member already has a tab for this month (' + name_dst + ').')
        return

    dict_ym_to_sheet = {}
    for name_sheet in l_sheet:
        if name_sheet.startswith('member_') and len(name_sheet) == len('member_') + 6 and name_sheet[7:].isdigit():
            dict_ym_to_sheet[name_sheet[7:]] = name_sheet
    ym_dst = '{:04d}{:02d}'.format(year_plan, month_plan)
    l_ym_before = sorted(ym for ym in dict_ym_to_sheet if ym < ym_dst)
    if not l_ym_before:
        print('[WARNING] No prior member_<yyyymm> tab found to copy forward for ' + name_dst + '. Create it manually.')
        return

    name_src = dict_ym_to_sheet[l_ym_before[-1]]
    result = copy_gsheet_tab(service_sheets, service_drive, id_config, 'member', name_src, name_dst)
    if result == 'copied':
        print('Copied member tab ' + name_src + ' -> ' + name_dst + '.')
    else:
        print('[WARNING] Could not copy member tab ' + name_src + ' -> ' + name_dst + ' (' + result + ').')


################################################################################
# Drive-backed app config (dutyshift/config/config.json) and email templates
# (dutyshift/template/<name>.json)
#
# id_calendar and every notification email's wording used to be hardcoded in
# script/parameter.py. They now live on Drive so an admin can edit them without a code change,
# and every pipeline call reads them fresh (script/form.py::prepare_form,
# script/collect.py::collect_availability, script/notify.py::update_calendar/
# draft_dropin_notification/draft_fixed_notification all call the loaders below on every run --
# nothing is cached across calls). load_drive_config seeds config.json with this codebase's
# original hardcoded content the first time it's read, so an existing installation keeps working
# without a manual migration step; load_email_template has no such fallback -- template wording
# lives on Drive only, and a missing dutyshift/template/<name>.json is an error.
#
# id_template_form/dict_itemid_form/id_item_name/dict_sectionid_title used to live here too (the
# Google Form template "1. Create Form" copied each month, its grid/name-dropdown item IDs, and
# the title_short -> section-item-id routing rebuilt from them). They're gone now that
# script/form.py::prepare_form builds the form from scratch every run (forms.create +
# batchUpdate) instead of copying a template -- every item id it needs is ephemeral, read back
# from that run's own create-items response, so there's nothing stable left to persist on Drive.
################################################################################
_DICT_CONFIG_DEFAULT = {
    'id_calendar': 'ht4svlr03krt7jcqho5guou32c@group.calendar.google.com',
    # Extra recipients (beyond active doctors) Bcc'd on the "draft fixed notification" email --
    # e.g. secretaries or administrators who want the finalized roster but never fill in the
    # availability form. Empty by default; add addresses directly in
    # dutyshift/config/config.json.
    'l_email_extra_fixed': [],
    # Shift-swap request form -- the same link embedded in every calendar event's description
    # (script/notify.py::add_duty) and rendered as a button in the "draft drop-in notification"/
    # "draft fixed notification" emails (script/notify.py::draft_dropin_notification/
    # draft_fixed_notification).
    'url_replace_form': 'https://forms.gle/oxvdt8CNkW6iPPFm6',
}


def load_drive_config(service_drive, id_config):
    """Read dutyshift/config/config.json: id_calendar (target Google Calendar for "4. Notify" ->
    Publish to Calendar), l_email_extra_fixed (extra Bcc recipients for the "draft fixed
    notification" button), and url_replace_form (the shift-swap request form link embedded in
    calendar events and the drop-in/fixed notification emails). Seeded with _DICT_CONFIG_DEFAULT
    the first time it's read. If the file already exists but predates a key later added to
    _DICT_CONFIG_DEFAULT (e.g. an installation that seeded config.json before
    url_replace_form/l_email_extra_fixed existed), that top-level key is backfilled in place --
    without this, a caller reading it would KeyError on a key an admin never had a chance to
    remove."""
    dict_config = read_json(service_drive, id_config, 'config.json', default=None)
    if dict_config is None:
        dict_config = dict(_DICT_CONFIG_DEFAULT)
        write_json(service_drive, id_config, 'config.json', dict_config)
    else:
        dict_missing = {key: value for key, value in _DICT_CONFIG_DEFAULT.items() if key not in dict_config}
        if dict_missing:
            dict_config.update(dict_missing)
            write_json(service_drive, id_config, 'config.json', dict_config)
    return dict_config


# Each dutyshift/template/<name>.json entry is {'subject', 'body', 'button_label', ...}:
# 'subject' and 'body' are str.format() templates. 'button_label'/'button_label_replace' are the
# visible text of the HTML buttons script/parameter.py::str_email_button_html renders in place of
# {button}/{button_replace} -- {button} links to the assignment Google Sheet, {button_replace} to
# the shift-swap request form (dutyshift/config/config.json's url_replace_form). Every caller
# below passes all of {deadline}/{year}/{month}/{button}/{button_replace} regardless of which
# ones its own subject/body actually references, so an admin can freely add/remove any of them on
# Drive without a code change. Wording lives on Drive only -- there is no code-side default or
# seeding; the file must already exist there.
def load_email_template(service_drive, id_template, name):
    """Read one email template (subject/body/button_label) from
    dutyshift/template/<name>.json. Called fresh on every button click (never cached across
    runs), so an admin's edit on Drive takes effect on the very next click. Raises
    FileNotFoundError if the template file doesn't exist on Drive (there is no code-side default
    to fall back to) -- any Drive access error (auth, network) propagates as-is from read_json."""
    dict_template = read_json(service_drive, id_template, name + '.json', default=None)
    if dict_template is None:
        raise FileNotFoundError(
            f"dutyshift/template/{name}.json not found on Drive -- create it there before running this stage.")
    return dict_template


################################################################################
# Load previous month assignment
################################################################################
def prep_assign_previous(dp, year_plan, month_plan):
    l_dir_pastdata = list_month_folders(dp.service_drive, dp.id_root)
    l_dir_pastdata = sorted(l_dir_pastdata)
    dir_current = str(year_plan) + str(month_plan).zfill(2)
    dir_previous = l_dir_pastdata[l_dir_pastdata.index(dir_current) - 1]
    year_previous = int(dir_previous[:4])
    month_previous = int(dir_previous[4:6])

    id_month_previous = dp.cache.get_or_create(dp.service_drive, month_folder_path(year_previous, month_previous))
    d_assign_date_duty = read_csv(dp.service_drive, id_month_previous, 'assign_date_duty.csv')

    if 'cnt' in d_assign_date_duty.columns:
        d_assign_date_duty = d_assign_date_duty[d_assign_date_duty['cnt'] == 1]
    elif 'status' in d_assign_date_duty.columns:
        d_assign_date_duty = d_assign_date_duty[d_assign_date_duty['status'] == 'assigned']
    n_date_duty = d_assign_date_duty.shape[0]
    max_date = d_assign_date_duty['date'].max()
    d_assign_date_duty['date_minus'] = d_assign_date_duty['date'] - max_date
    d_assign_date_duty['date_duty_minus'] = [str(date) + '_' + duty for date, duty in zip(d_assign_date_duty['date_minus'].tolist(), d_assign_date_duty['duty'].tolist())]

    l_member = sorted(list(set(d_assign_date_duty['id_member'].dropna().tolist())))
    l_member = [int(x) for x in l_member]

    d_assign = pd.DataFrame(np.zeros([n_date_duty, len(l_member)]),
                            index=d_assign_date_duty['date_duty_minus'].tolist(), columns=l_member)

    for _, row  in d_assign_date_duty.iterrows():
        date_duty = row['date_duty_minus']
        id_member = row['id_member']
        d_assign.loc[date_duty, id_member] = 1

    return d_assign


################################################################################
# Optimize exact count of assignment
################################################################################
def optimize_count(d_member, s_cnt_class_duty, d_lim_hard, d_score_past, d_score_class,
                   d_grp_score, dict_c_diff_score_current, dict_c_diff_score_total, l_type_score, l_class_duty):

    # Dataframe of variables
    l_member = d_member.loc[d_member['active'], 'id_member'].tolist()
    l_lim_exact = [str(p[0]) + '_' + p[1] for p in itertools.product(l_member, l_class_duty)]
    dict_v_lim_exact = LpVariable.dicts(name='cnt', indices=l_lim_exact, lowBound=0, upBound=None,  cat='Integer')
    #dict_v_lim_exact = LpVariable.dicts(name = 'cnt', indices = l_lim_exact, lowBound = 0, upBound = None,  cat = 'Continuous')
    lv_lim_exact = list(dict_v_lim_exact.values())
    llv_lim_exact = [lv_lim_exact[i:i+len(l_class_duty)] for i in range(0, len(lv_lim_exact), len(l_class_duty))]
    dv_lim_exact = pd.DataFrame(llv_lim_exact, index=l_member, columns=l_class_duty)

    # Initialize count optimization problem
    prob_cnt = LpProblem()

    # Condition on sum of class_duty
    for class_duty in l_class_duty:
        prob_cnt += (lpSum(dv_lim_exact.loc[:,class_duty]) == s_cnt_class_duty[class_duty])

    # Condition using hard limits
    for member in l_member:
        for class_duty in l_class_duty:
            lim_hard = d_lim_hard.loc[member, class_duty]
            if ~np.isnan(lim_hard[0]):
                if lim_hard[0] == lim_hard[1]:
                    prob_cnt += (dv_lim_exact.loc[member, class_duty] == lim_hard[0])
                else:
                    prob_cnt += (dv_lim_exact.loc[member, class_duty] <= lim_hard[1])
                    prob_cnt += (lim_hard[0] <= dv_lim_exact.loc[member, class_duty])

    # Convert variables in dv_lim_exact to dv_score
    dv_score_current = pd.DataFrame(np.array(addvars(len(l_member), len(l_type_score))),
                                    index=l_member, columns=l_type_score)
    dv_score_total = pd.DataFrame(np.array(addvars(len(l_member), len(l_type_score))),
                                  index=l_member, columns=l_type_score)
    for type_score in l_type_score:
        d_score_class_temp = d_score_class.loc[d_score_class['score'] == type_score,:].copy()
        l_class_duty_tmp = d_score_class_temp['class'].tolist()
        l_constant_tmp = d_score_class_temp['constant'].tolist()
        for member in l_member:
            lv_lim_exact_tmp = dv_lim_exact.loc[member, l_class_duty_tmp].tolist()
            # Current score
            prob_cnt += (dv_score_current.loc[member, type_score] == \
                         lpDot(lv_lim_exact_tmp, l_constant_tmp))
            # Current + past score
            if member in d_score_past['id_member'].tolist():
                score_past = d_score_past.loc[d_score_past['id_member'] == member, type_score].values[0]
            else:
                score_past = 0.0
            prob_cnt += (dv_score_total.loc[member, type_score] == \
                         dv_score_current.loc[member, type_score] + \
                         score_past)

    # Calculate sum of score differences
    n_grp_max = d_grp_score.max().max() + 1
    # Sum of inter-member differences of current month scores
    dv_sigma_diff_score_current = pd.DataFrame(np.array(addvars(n_grp_max, len(l_type_score))),
                                               index=range(n_grp_max), columns=l_type_score)
    # Sum of inter-member differences of current + past month score
    dv_sigma_diff_score_total = pd.DataFrame(np.array(addvars(n_grp_max, len(l_type_score))),
                                             index=range(n_grp_max), columns=l_type_score)
    dict_dv_diff_score_current = {}
    dict_dv_diff_score_total = {}
    for type_score in l_type_score:
        dict_dv_diff_score_current[type_score] = pd.DataFrame(np.array(addvars(len(l_member),len(l_member))), index=l_member, columns=l_member)
        dict_dv_diff_score_total[type_score] = pd.DataFrame(np.array(addvars(len(l_member),len(l_member))), index=l_member, columns=l_member)

    for type_score in l_type_score:
        l_grp = [x for x in d_grp_score[type_score].unique() if x is not pd.NA]
        for i_grp in l_grp:
            l_member_grp = d_grp_score.loc[d_grp_score[type_score] == i_grp, :].index.tolist()
            for id_member_0 in l_member_grp:
                for id_member_1 in l_member_grp:
                    prob_cnt += (dict_dv_diff_score_current[type_score].loc[id_member_0, id_member_1] >=\
                                 dv_score_current.loc[id_member_0, type_score] - dv_score_current.loc[id_member_1, type_score])
                    prob_cnt += (dict_dv_diff_score_total[type_score].loc[id_member_0, id_member_1] >=\
                                 dv_score_total.loc[id_member_0, type_score] - dv_score_total.loc[id_member_1, type_score])
            prob_cnt += (dv_sigma_diff_score_current.loc[i_grp, type_score] ==\
                         lpSum(dict_dv_diff_score_current[type_score].loc[l_member_grp, l_member_grp].to_numpy()))
            prob_cnt += (dv_sigma_diff_score_total.loc[i_grp, type_score] ==\
                         lpSum(dict_dv_diff_score_total[type_score].loc[l_member_grp, l_member_grp].to_numpy()))
        l_grp_empty = [x for x in range(n_grp_max) if x not in l_grp]
        for i_grp in l_grp_empty:
            prob_cnt += (dv_sigma_diff_score_current.loc[i_grp, type_score] == 0)
            prob_cnt += (dv_sigma_diff_score_total.loc[i_grp, type_score] == 0)

    # Objective function
    lc_diff_score = [dict_c_diff_score_current[x] for x in l_type_score] \
                    + [dict_c_diff_score_total[x] for x in l_type_score]
    l_sum_diff_score = [lpSum(dv_sigma_diff_score_current[x].to_numpy()) for x in l_type_score] \
                       + [lpSum(dv_sigma_diff_score_total[x].to_numpy()) for x in l_type_score]
    prob_cnt += (lpDot(lc_diff_score, l_sum_diff_score))

    # Solve problem
    prob_cnt.solve()
    str_status = str(LpStatus[prob_cnt.status])
    loss_opt = value(prob_cnt.objective)
    if str_status == 'Optimal':
        status_opt = True
        #print('Solved, ' + str(round(loss_solution, 2)))
        # Extract data
        d_lim_exact = pd.DataFrame(np.vectorize(value)(dv_lim_exact),
                                columns=dv_lim_exact.columns, index=dv_lim_exact.index)
        d_score_current = pd.DataFrame(np.vectorize(value)(dv_score_current),
                                    columns=dv_score_current.columns, index=dv_score_current.index)
        d_score_total = pd.DataFrame(np.vectorize(value)(dv_score_total),
                                    columns=dv_score_total.columns, index=dv_score_total.index)
        d_sigma_diff_score_current = pd.DataFrame(np.vectorize(value)(dv_sigma_diff_score_current),
                                                columns=dv_sigma_diff_score_current.columns, index=dv_sigma_diff_score_current.index)
        d_sigma_diff_score_total = pd.DataFrame(np.vectorize(value)(dv_sigma_diff_score_total),
                                                columns=dv_sigma_diff_score_total.columns, index=dv_sigma_diff_score_total.index)
        return status_opt, loss_opt, d_lim_exact, d_score_current, d_score_total, d_sigma_diff_score_current, d_sigma_diff_score_total
    else:
        print('Failed to solve assignment count optimization')
        status_opt = False
        return [status_opt] + [None] * 6


################################################################################
# Prepare data of member specs and assignment limits
################################################################################
def prep_member2(dp, year_plan, month_plan, year_start, month_start, dict_score_duty):
    l_class_duty = class_duty_names(dict_class_duty)
    l_col_member = ['id_member','name_jpn','name_jpn_full','email','title_jpn',
                    'designation_jpn','ect_asgn_jpn','name','title_short',
                    'designation', 'team', 'ect_leader', 'ect_subleader', 'active']

    # Load source member and assignment limit of the month
    id_config = dp.cache.get_or_create(dp.service_drive, 'dutyshift/config')
    d_src = read_member(dp.service_drive, dp.service_sheets, id_config, year_plan, month_plan)
    d_src = d_src.loc[d_src['active'], ]
    l_col_member = [col for col in l_col_member if col in d_src.columns]
    d_member = d_src[l_col_member]
    d_lim = d_src[l_class_duty].copy()
    d_lim.index = d_member['id_member'].tolist()

    # Calculate past scores
    d_score_past = past_score(dp, d_member, year_plan, month_plan, year_start, month_start, dict_score_duty)

    # Split assignment limit data into hard and soft
    d_lim_hard, d_lim_soft = split_lim(d_lim)

    # Dataframe of score equilization groups
    d_grp_score = d_src[[col for col in d_src.columns if col.startswith('grp_')]].copy()
    d_grp_score.columns = [x[4:] for x in d_grp_score.columns]
    d_grp_score.index = d_member['id_member'].tolist()
    d_grp_score = d_grp_score.replace('-', np.nan)
    d_grp_score = d_grp_score.astype('Int64')

    # Save data
    # member.csv is written only by collect_availability (script/collect.py) -- not here, to
    # avoid two writers disagreeing on its shape. lim_hard/lim_soft/grp_score/score_past below
    # keep id_member as an explicit column (never as the CSV's own row index, which round-trips
    # unreliably) via rename_axis('id_member').reset_index(); the in-memory DataFrames used by
    # the solver are unaffected -- only how they're written to Drive changes.
    for id_folder in [id for id in [dp.id_month, dp.id_data] if id is not None]:
        write_csv(dp.service_drive, id_folder, 'score_past.csv', d_score_past, index=False)
        write_csv(dp.service_drive, id_folder, 'lim_hard.csv', d_lim_hard.rename_axis('id_member').reset_index(), index=False)
        write_csv(dp.service_drive, id_folder, 'lim_soft.csv', d_lim_soft.rename_axis('id_member').reset_index(), index=False)
        write_csv(dp.service_drive, id_folder, 'grp_score.csv', d_grp_score.rename_axis('id_member').reset_index(), index=False)

    return d_member, d_score_past, d_lim_hard, d_lim_soft, d_grp_score


################################################################################
# Extract data from optimized variables
################################################################################
def extract_assignment(dp, year_plan, month_plan, dv_assign, d_date_duty_noskip, l_date_duty_skip):
    # Convert variables to fixed values
    d_assign = pd.DataFrame(np.vectorize(value)(dv_assign),
                            index=dv_assign.index, columns=dv_assign.columns).astype(bool)

    # Assignments with date_duty as row
    d_assign_date_duty = pd.concat([pd.Series(d_assign.index, index=d_assign.index, name='date_duty'),
                                    #pd.Series(d_assign.sum(axis = 1), name = 'cnt'),
                                    pd.Series(d_assign.apply(lambda row: row[row].index.to_list(), axis=1), name='id_member')],
                                    axis=1)
    d_assign_date_duty.index = range(len(d_assign_date_duty))
    d_assign_date_duty['id_member'] = d_assign_date_duty['id_member'].apply(lambda x: x[0] if len(x) > 0 else np.nan)
    d_assign_date_duty = pd.merge(d_date_duty_noskip, d_assign_date_duty, on='date_duty', how='left')
    d_assign_date_duty['year'] = year_plan
    d_assign_date_duty['month'] = month_plan
    d_assign_date_duty['status'] = 'assigned'
    d_assign_date_duty.loc[np.isnan(d_assign_date_duty['id_member']), 'status'] = 'unnecessary'
    d_assign_date_duty.loc[d_assign_date_duty['date_duty'].isin(l_date_duty_skip), 'status'] = 'skipped'
    d_assign_date_duty = d_assign_date_duty.loc[:,['date_duty', 'year', 'month', 'date', 'duty', 'id_member', 'status']]

    for id_folder in [id for id in [dp.id_month, dp.id_data] if id is not None]:
        write_csv(dp.service_drive, id_folder, 'assign_date_duty.csv', d_assign_date_duty, index=False)

    return d_assign_date_duty


def extract_closeduty(dp, dict_dv_closeduty, d_assign_date_duty, d_member, dict_closeduty):

    dict_d_closeduty = {}
    for closeduty in dict_dv_closeduty.keys():
        d_closeduty = pd.DataFrame(np.vectorize(value)(dict_dv_closeduty[closeduty]),
                                   index=dict_dv_closeduty[closeduty].index, columns=dict_dv_closeduty[closeduty].columns)
        dict_d_closeduty[closeduty] = d_closeduty

    # Closeduty
    l_date_duty_close = []
    for closeduty in dict_d_closeduty.keys():
        l_duty_close = dict_closeduty[closeduty]['l_duty']
        for member in d_member['id_member'].tolist():
            if member in dict_d_closeduty[closeduty].columns:
                s_closeduty = dict_d_closeduty[closeduty][member]
                l_date_closeduty = s_closeduty[s_closeduty > 0].index.tolist()
                thr_soft = dict_closeduty[closeduty]['thr_soft']
                for date_start in l_date_closeduty:
                    date_end = date_start + thr_soft - 1
                    l_date_duty_close_member = d_assign_date_duty.loc[(d_assign_date_duty['id_member'] == member)
                                                             & (d_assign_date_duty['date'] >= date_start) & (d_assign_date_duty['date'] <= date_end)
                                                             & (d_assign_date_duty['duty'].isin(l_duty_close)) & (d_assign_date_duty['duty'].isin(l_duty_close)),'date_duty'].tolist()
                    l_date_duty_close += l_date_duty_close_member
                    #l_closeduty.append([closeduty, member, date_start, date_end])
    #d_closeduty = pd.DataFrame(l_closeduty, columns = ['type_duty', 'id_member', 'date_start', 'date_end'])
    #d_closeduty = pd.merge(d_closeduty, d_member[['id_member', 'name_jpn']], on = 'id_member', how = 'left')
    #d_closeduty = d_closeduty[['type_duty', 'id_member', 'name_jpn', 'date_start', 'date_end']]
    l_date_duty_close = list(set(l_date_duty_close))
    d_closeduty = d_assign_date_duty.loc[d_assign_date_duty['date_duty'].isin(l_date_duty_close), ['id_member', 'date_duty']]
    d_closeduty = pd.merge(d_closeduty, d_member[['id_member', 'name_jpn']], on='id_member', how='left')
    d_closeduty['id_member'] = d_closeduty['id_member'].astype('int')
    # Sort 1. by id_member, 2. by date_duty. d_assign_date_duty (and so d_closeduty, filtered
    # from it above) is already in chronological date_duty order, so a stable sort on id_member
    # alone is enough to layer that ordering in as the secondary key.
    d_closeduty = d_closeduty.sort_values('id_member', kind='stable').reset_index(drop=True)
    d_closeduty = d_closeduty[['id_member', 'name_jpn', 'date_duty']]

    for id_folder in [id for id in [dp.id_month, dp.id_data] if id is not None]:
        write_csv(dp.service_drive, id_folder, 'closeduty.csv', d_closeduty, index=False)

    return d_closeduty


################################################################################
# Convert assignment result
################################################################################
def convert_assignment(dp, d_assign_date_duty, d_availability_noskip,
                   d_member, d_date_duty, d_cal, dict_score_duty, d_lim_exact, d_lim_hard):
    l_class_duty = class_duty_names(dict_class_duty)
    # d_assign_date_duty >> d_assign
    d_assign = pd.DataFrame(index=d_availability_noskip.index, columns=d_availability_noskip.columns)
    for id, row in d_assign_date_duty.iterrows():
        date_duty = row['date_duty']
        id_member = row['id_member']
        if ~np.isnan(id_member):
            id_member = int(id_member)
            d_assign.loc[date_duty, id_member] = True
    d_assign = d_assign.fillna(False)

    # d_assign_date_duty >> d_assgin_date_print
    # Assignments with date as row for printing
    d_assign_date_print = d_cal.loc[:,['title_date','date', 'em']].copy()
    d_assign_date_print[['am','pm','night','ocday','ocnight','ect']] = ''
    for _, row in d_assign_date_duty.loc[d_assign_date_duty['status'] != 'unnecessary'].iterrows():
        date = row['date']
        duty = row['duty']
        if row['status'] == 'assigned':
            id_member = int(row['id_member'])
            name_jpn = d_member.loc[d_member['id_member'] == id_member, 'name_jpn'].tolist()[0]
        elif row['status'] == 'skipped':
            name_jpn = '(未定)'
        if duty == 'day':
            d_assign_date_print.loc[d_assign_date_print['date'] == date, 'am'] = name_jpn
            d_assign_date_print.loc[d_assign_date_print['date'] == date, 'pm'] = name_jpn
        elif duty == 'emnight':
            d_assign_date_print.loc[d_assign_date_print['date'] == date, 'night'] = name_jpn
        else:
            d_assign_date_print.loc[d_assign_date_print['date'] == date, duty] = name_jpn

    for date in d_assign_date_print.loc[d_assign_date_print['em'] == True, 'date'].tolist():
        d_assign_date_print.loc[d_assign_date_print['date'] == date, 'night'] += '(救急)'
    d_assign_date_print = d_assign_date_print.loc[:,['title_date','am','pm','night','ocday','ocnight','ect']]
    d_assign_date_print.columns = ['日付', '午前日直', '午後日直', '当直', '日直OC', '当直OC', 'ECT']

    # d_assign, d_availability >> d_assign_member
    # Assignments with member as row
    d_assign_optimal = pd.DataFrame((d_availability_noskip == 2) & d_assign, columns=d_assign.columns, index=d_assign.index)
    d_assign_suboptimal = pd.DataFrame((d_availability_noskip == 1) & d_assign, columns=d_assign.columns, index=d_assign.index)
    #d_assign_error = pd.DataFrame((d_availability == 0) & d_assign, columns = l_member, index = d_assign.index)
    d_assign_member = pd.DataFrame({'id_member': [int(id) for id in d_assign.columns.tolist()],
                                    #'name_jpn': d_member.loc[d_member['id_member'].isin(l_member),'name_jpn'].tolist(),
                                    'duty_all': [', '.join(l) for l in d_assign.apply(lambda col: col[col].index.to_list(), axis=0).values.tolist()],
                                    #'duty_opt': [', '.join(l) for l in d_assign_optimal.apply(lambda col: col[col].index.to_list(), axis = 0).values.tolist()],
                                    #'duty_sub': [', '.join(l) for l in d_assign_suboptimal.apply(lambda col: col[col].index.to_list(), axis = 0).values.tolist()],
                                    'cnt_all': d_assign.sum(axis=0),
                                    'cnt_opt': d_assign_optimal.sum(axis=0),
                                    'cnt_sub': d_assign_suboptimal.sum(axis=0)},
                                    index=d_assign.columns)
    d_assign_member = pd.merge(d_member[['id_member', 'name_jpn']], d_assign_member, on='id_member', how='left')

    # d_assign_date_duty >> d_deviation, d_deviation_summary
    # Prepare deviation results
    #d_deviation = pd.concat([d_member[['id_member', 'name_jpn']], pd.DataFrame(index = d_member.index, columns = l_class_duty)], axis = 1)
    col_deviation = [col + '_exact' for col in l_class_duty] + [col + '_hard' for col in l_class_duty]
    d_deviation = pd.concat([d_member[['id_member', 'name_jpn']], pd.DataFrame(index=d_member.index, columns=col_deviation)], axis=1)
    ll_deviation = []
    for member in d_assign.columns:
        s_assign_class = pd.merge(d_assign_date_duty.loc[d_assign_date_duty['id_member'] == member, :], d_date_duty,
                                  on='date_duty', how='left').sum(axis=0)
        l_assign_class = s_assign_class[['class_' + class_duty for class_duty in l_class_duty]].tolist()
        l_assign_class = [int(class_member) for class_member in l_assign_class]
        l_assign_class_target_exact = d_lim_exact.loc[int(member), l_class_duty].tolist()
        l_assign_class_target_hard = d_lim_hard.loc[int(member), l_class_duty].tolist()
        l_deviation_member_exact, l_deviation_member_hard = [], []
        for value, target_exact, target_hard in zip(l_assign_class, l_assign_class_target_exact, l_assign_class_target_hard):
            # Deviation from exact target
            dev_exact = value - target_exact
            l_deviation_member_exact.append(dev_exact)
            # Deviation from hard limit (target range)
            [target_min, target_max] = target_hard
            if value > target_max:
                dev_hard = value - target_max
            elif value < target_min:
                dev_hard = value - target_min
            else:
                dev_hard = 0
            l_deviation_member_hard.append(dev_hard)
        d_deviation.loc[d_deviation['id_member'] == int(member), [col + '_exact' for col in l_class_duty]] = l_deviation_member_exact
        d_deviation.loc[d_deviation['id_member'] == int(member), [col + '_hard' for col in l_class_duty]] = l_deviation_member_hard
        # Data for summary (only deviant result)
        for class_duty, dev_exact, dev_hard in zip(l_class_duty, l_deviation_member_exact, l_deviation_member_hard):
            if dev_exact > 0 or dev_exact < 0:
                ll_deviation.append([int(member), class_duty, int(dev_exact), int(dev_hard)])

    d_deviation[col_deviation] = d_deviation[col_deviation].fillna(0).astype(int)

    d_deviation_summary = pd.DataFrame(ll_deviation, columns=['id_member', 'class_duty', 'deviation_exact', 'deviation_hard'])
    d_deviation_summary = pd.merge(d_deviation_summary, d_member[['id_member', 'name_jpn']], on='id_member', how='left')
    d_deviation_summary = d_deviation_summary[['id_member', 'name_jpn', 'class_duty', 'deviation_exact', 'deviation_hard']]

    # d_assign_date_duty >> d_score_print, d_score_past, d_score_total
    # Score calculation
    d_score_duty = pd.DataFrame(dict_score_duty)
    l_type_score = [col for col in d_score_duty.columns if col != 'duty']
    d_assign_date_duty = pd.merge(d_assign_date_duty, d_score_duty, on='duty', how='left')
    d_score_current = d_member.copy()
    for id_member in d_score_current['id_member'].tolist():
        d_score_member = d_assign_date_duty.loc[d_assign_date_duty['id_member'] == id_member, l_type_score]
        s_score_member = d_score_member.sum(axis=0)
        d_score_current.loc[d_score_current['id_member'] == id_member, l_type_score] = s_score_member.tolist()

    d_score_current.index = d_score_current['id_member'].tolist()
    d_score_current = d_score_current[['id_member'] + l_type_score]

    d_score_past = read_csv(dp.service_drive, dp.id_month, 'score_past.csv')
    d_score_past = d_score_past.loc[~np.isnan(d_score_past['id_member']), :]
    d_score_past.index = d_score_past['id_member'].tolist()

    d_score_total = d_score_past[l_type_score] + d_score_current[l_type_score]
    #d_score_total = pd.concat([pd.DataFrame({'id_member': d_score_current['id_member'].tolist()},
    #                                        index = d_score_current['id_member'].tolist()),
    #                           d_score_total], axis = 1)
    d_score_total = pd.concat([pd.DataFrame({'id_member': [int(id) for id in d_score_total.index.tolist()]},
                                            index=[int(id) for id in d_score_total.index.tolist()]),
                               d_score_total], axis=1)
    d_score_print = d_member[['id_member', 'name_jpn_full']].copy()
    d_score_print = pd.merge(d_score_print, d_score_current, on='id_member', how='left')
    d_score_print = pd.merge(d_score_print, d_score_total, on='id_member', how='left')
    d_score_print.columns = ['id_member', 'name_jpn'] + ['score_' + col for col in l_type_score] + ['score_sigma_' + col for col in l_type_score]

    for id_folder in [id for id in [dp.id_month, dp.id_data] if id is not None]:
        write_csv(dp.service_drive, id_folder, 'assign.csv', d_assign, index=True)
        write_csv(dp.service_drive, id_folder, 'assign_print.csv', d_assign_date_print, index=False)
        write_csv(dp.service_drive, id_folder, 'assign_member.csv', d_assign_member, index=False)
        write_csv(dp.service_drive, id_folder, 'deviation.csv', d_deviation, index=False)
        write_csv(dp.service_drive, id_folder, 'deviation_summary.csv', d_deviation_summary, index=False)
        write_csv(dp.service_drive, id_folder, 'score_current.csv', d_score_current, index=False)
        write_csv(dp.service_drive, id_folder, 'score_total.csv', d_score_total, index=False)
        write_csv(dp.service_drive, id_folder, 'score_print.csv', d_score_print, index=False)

    return d_assign, d_assign_date_print, d_assign_member, d_deviation, d_deviation_summary, d_score_current, d_score_total, d_score_print


################################################################################
# Prepare data of member availability
################################################################################
'''
def prep_availability(p_month, p_data, d_date_duty, d_cal):
    #d_availability = pd.read_csv(os.path.join(p_month, 'availability_src.csv'))
    #d_availability.set_index('id_member', inplace = True)
    #d_availability.drop(['name_jpn_full'], axis = 1, inplace = True)
    #d_availability = d_availability.T
    #d_availability = pd.concat([pd.DataFrame({'id_member': d_availability.index}), d_availability], axis = 1)
    d_availability = pd.read_csv(os.path.join(p_month, 'availability.csv'), index_col = 0)
    d_availability.columns = [int(col) for col in d_availability.columns]

    d_availability_ratio = pd.DataFrame(index = d_availability.index, columns = ['total','available','ratio'])
    d_availability_ratio['total'] = d_availability.count(axis = 1)
    d_availability_ratio['available'] = d_availability.replace(2,1).sum(axis = 1)
    d_availability_ratio['ratio'] = d_availability_ratio['available'] / d_availability_ratio['total']

    d_availability.fillna(0, inplace = True)
    l_date_ect = d_cal.loc[d_cal['ect'] == True, 'date'].tolist()
    d_availability_ect = d_availability.loc[[str(date_ect) + '_am' for date_ect in l_date_ect], :]
    d_availability_ect.index = ([str(date_ect) + '_ect' for date_ect in l_date_ect])
    d_availability = pd.concat([d_availability, d_availability_ect], axis = 0)
    d_availability = d_availability.loc[d_date_duty['date_duty'],:]
    d_availability = pd.concat([pd.DataFrame({'date_duty': d_availability.index}, index = d_availability.index), d_availability], axis = 1)
    for p_save in [p_month, p_data]:
        #d_availability.to_csv(os.path.join(p_save, 'availability.csv'), index = False)
        d_availability_ratio.to_csv(os.path.join(p_save, 'availability_ratio.csv'), index = False)

    l_member = [col for col in d_availability.columns.to_list() if col != 'date_duty']
    d_availability = d_availability[l_member]

    return d_availability, l_member, d_availability_ratio
'''

################################################################################
# Prepare calendar of the month
################################################################################
def prep_calendar(dp, l_holiday, l_day_ect, l_date_ect_cancel, day_em, l_week_em,
                  year_plan, month_plan, dict_score_duty, dict_class_duty):
    dict_jpnday = {0: '月', 1: '火', 2: '水', 3: '木', 4: '金', 5: '土', 6: '日'}

    # Prepare d_cal (calendar with existence of each duty)
    day_start, date_end = calendar.monthrange(year_plan, month_plan)
    d_cal = pd.DataFrame([[date] for date in range(1, date_end + 1)], columns=['date'])
    d_cal['wday'] = d_cal['date'].apply(lambda x: datetime.date(year_plan, month_plan, x).weekday())
    d_cal['wday_jpn'] = d_cal['wday'].apply(lambda x: dict_jpnday[x])
    d_cal['week'] = d_cal['date'].apply(lambda x: ceil(x/7))
    d_cal['holiday'] = d_cal['wday'].apply(lambda x: x in [5, 6])
    for date in l_holiday:
        d_cal.loc[d_cal['date'] == date, 'holiday'] = True
    d_cal[['em', 'am', 'pm', 'day', 'night', 'emnight', 'ocday', 'ocnight', 'ect']] = False
    d_cal.loc[(d_cal['wday'] == day_em) & (d_cal['week'].isin(l_week_em)) & (d_cal['holiday'] == False), 'em'] = True
    dict_duty_holiday_flag = duty_holiday_flags()
    d_cal.loc[d_cal['holiday'] == False, dict_duty_holiday_flag[False]] = True
    d_cal.loc[d_cal['em'] == True, ['night', 'emnight','ocnight']] = [False, True, False]
    d_cal.loc[d_cal['holiday'] == True, dict_duty_holiday_flag[True]] = True
    d_cal.loc[(d_cal['wday'].isin(l_day_ect)) & (d_cal['holiday'] == False), 'ect'] = True
    d_cal.loc[d_cal['date'].isin(l_date_ect_cancel), 'ect'] = False

    d_cal['holiday_wday'] = ''
    d_cal.loc[(d_cal['holiday'] == True) & (d_cal['wday'].isin([0,1,2,3,4])), 'holiday_wday'] = '・祝'
    d_cal['title_date'] = [str(month_plan) + '/' + str(date) + '(' + wday_jpn + holiday_wday + ')' for [date, wday_jpn, holiday_wday] in zip(d_cal['date'], d_cal['wday_jpn'], d_cal['holiday_wday'])]
    d_cal = d_cal.drop('holiday_wday', axis=1)

    # Prepare s_cnt_duty (necessary assignment counts of each duty)
    s_cnt_duty = d_cal[['am', 'pm', 'day', 'night', 'emnight', 'ocday', 'ocnight', 'ect']].sum(axis=0)

    # Prepare d_date_duty (specs and scores and classifications of each duty in each date)
    ld_date_duty = []
    for duty in ['am', 'pm', 'day', 'night', 'emnight', 'ocday', 'ocnight', 'ect']:
        d_date_duty_append = d_cal.loc[d_cal[duty] == True, ['date', 'holiday','em']]
        d_date_duty_append['duty'] = duty
        d_date_duty_append['date_duty'] = d_date_duty_append['date'].apply(lambda x: str(x) + '_' + duty)
        ld_date_duty.append(d_date_duty_append)
    d_date_duty = pd.concat(ld_date_duty, axis=0)
    d_date_duty = d_date_duty[['date_duty','date','duty','holiday','em']]
    d_date_duty.index = range(len(d_date_duty))

    # Calculate scores
    d_score_duty = pd.DataFrame(dict_score_duty)
    d_score_duty.columns = [d_score_duty.columns.tolist()[0]] + ['score_' + col for col in d_score_duty.columns.tolist()[1:]]
    d_date_duty = pd.merge(d_date_duty, d_score_duty, on='duty', how='left')

    # Calculate class of duty
    d_date_duty, s_cnt_class_duty = date_duty2class(d_date_duty, dict_class_duty)

    d_assign_manual = pd.DataFrame({'date_duty': d_date_duty['date_duty'].to_list(), 'id_member': None})

    # Save data
    for id_folder in [id for id in [dp.id_month, dp.id_data] if id is not None]:
        write_csv(dp.service_drive, id_folder, 'calendar.csv', d_cal, index=False)
        write_csv(dp.service_drive, id_folder, 'date_duty.csv', d_date_duty, index=False)
        write_csv(dp.service_drive, id_folder, 'assign_manual.csv', d_assign_manual, index=False)
        write_csv(dp.service_drive, id_folder, 'cnt_duty.csv', s_cnt_duty, index=True)
        write_csv(dp.service_drive, id_folder, 'cnt_class_duty.csv', s_cnt_class_duty, index=True)

    return d_cal, d_date_duty, s_cnt_duty, s_cnt_class_duty


################################################################################
# Manual assignment (assign_manual.csv) helpers for the '3. Assign' tab's Manual Assignment
# controls, which let the user designate/undesignate members per date_duty from the GUI instead
# of hand-editing assign_manual.csv on Drive. optimize_assign (script/assign.py) then reads
# assign_manual.csv as before -- these helpers only change how it gets populated.
################################################################################
def load_manual_assign_options(config, year_plan, month_plan):
    """Read-only: fetches everything the Manual Assignment controls need to build their
    date/duty/member dropdowns and to show designations already recorded (from a previous GUI
    session, or a direct CSV edit) -- the valid date_duty combinations for the month
    (date_duty.csv, written by prep_calendar/script/form.py::prepare_form), the roster of active
    doctors (id_member -> Japanese full name), and the current contents of assign_manual.csv.
    Raises if date_duty.csv / config/member for this month don't exist yet (i.e. '1. Create
    Form' hasn't been run for year_plan/month_plan) -- the caller reports that as a failure."""
    services = get_services(config, SCOPE_DRIVE_FORMS)
    dp = prep_drive_paths(config, services, year_plan, month_plan, prefix_dir='asgn', make_data_dir=False)

    d_date_duty = read_csv(services.drive, dp.id_month, 'date_duty.csv')
    d_assign_manual = read_csv(services.drive, dp.id_month, 'assign_manual.csv')

    id_config = dp.cache.get_or_create(dp.service_drive, 'dutyshift/config')
    d_member = read_member(dp.service_drive, dp.service_sheets, id_config, year_plan, month_plan)
    d_member = d_member.loc[d_member['active'], ['id_member', 'name_jpn_full']]
    dict_member_name = {int(id_member): name for id_member, name in
                        zip(d_member['id_member'], d_member['name_jpn_full'])}

    l_date_duty = d_date_duty['date_duty'].tolist()

    l_manual = []
    for _, row in d_assign_manual.loc[~d_assign_manual['id_member'].isna(), :].iterrows():
        l_manual.append({'date_duty': row['date_duty'], 'id_member': int(row['id_member'])})

    return l_date_duty, dict_member_name, l_manual


def write_manual_assign(config, year_plan, month_plan, l_manual):
    """Writes l_manual (a list of {'date_duty', 'id_member'} dicts, as edited by the Manual
    Assignment controls) to assign_manual.csv, replacing whatever was there before -- called
    right before 'Run Optimization' so optimize_count_and_assign's read of assign_manual.csv
    picks up the GUI's current designations. Any date_duty not in l_manual is written back with
    an empty id_member, same as prep_calendar's original blank assign_manual.csv."""
    services = get_services(config, SCOPE_DRIVE_FORMS)
    dp = prep_drive_paths(config, services, year_plan, month_plan, prefix_dir='asgn', make_data_dir=False)

    d_date_duty = read_csv(services.drive, dp.id_month, 'date_duty.csv')
    dict_manual = {d['date_duty']: d['id_member'] for d in l_manual}
    l_date_duty = d_date_duty['date_duty'].tolist()
    d_assign_manual = pd.DataFrame({
        'date_duty': l_date_duty,
        'id_member': [dict_manual.get(date_duty) for date_duty in l_date_duty],
    })
    write_csv(dp.service_drive, dp.id_month, 'assign_manual.csv', d_assign_manual, index=False)


################################################################################
# Split assignment limit data into hard and soft
################################################################################
def split_lim(d_lim):
    # Split assignment limit data into hard and soft
    d_lim_hard = pd.DataFrame([[[np.nan]*2]*d_lim.shape[1]]*d_lim.shape[0],
                              index=d_lim.index, columns=d_lim.columns)
    d_lim_soft = pd.DataFrame([[[np.nan]*2]*d_lim.shape[1]]*d_lim.shape[0],
                              index=d_lim.index, columns=d_lim.columns)

    for col in d_lim.columns:
        d_lim[col] = d_lim[col].astype(str)
        for idx in d_lim.index.tolist():

            if '(' in d_lim.loc[idx, col]:
                # If parenthesis exists, its content is hard limit
                d_lim_hard.loc[idx, col][0] = str(d_lim.loc[idx, col]).split('(')[1].split(')')[0]
                d_lim_soft.loc[idx, col][0] = str(d_lim.loc[idx, col]).split('(')[0]
            else:
                # If parenthesis does not exist it's hard limit
                d_lim_hard.loc[idx, col][0] = d_lim.loc[idx, col]
                d_lim_soft.loc[idx, col][0] = '-'

            for d_temp in [d_lim_hard, d_lim_soft]:
                if d_temp.loc[idx, col][0] == '-':
                    # Convert '-' to [np.nan, np.nan]
                    d_temp.loc[idx, col] = [np.nan]*2
                elif '-' in str(d_temp.loc[idx, col][0]):
                    # Convert string 'a-b' to list [a, b]
                    d_temp.loc[idx, col] = [int(x) for x in str(d_temp.loc[idx, col][0]).split('--')]
                else:
                    # Convert string 'a' to list [a, a]
                    d_temp.loc[idx, col] = [int(d_temp.loc[idx, col][0])]*2

    return d_lim_hard, d_lim_soft


################################################################################
# Calculate past scores
################################################################################
def past_score(dp, d_member, year_plan, month_plan, year_start, month_start, dict_score_duty):

    d_score_duty = pd.DataFrame(dict_score_duty)
    l_type_score = [col for col in d_score_duty.columns if col != 'duty']

    # Load Past assignments
    l_dir_pastdata = list_month_folders(dp.service_drive, dp.id_root)
    ym_start = (year_start * 100) + month_start
    ym_plan = (year_plan * 100) + month_plan
    l_dir_pastdata = [dir for dir in l_dir_pastdata if int(dir) >= ym_start]
    l_dir_pastdata = [dir for dir in l_dir_pastdata if int(dir) < ym_plan]
    l_dir_pastdata = sorted(l_dir_pastdata)
    if len(l_dir_pastdata) > 0:
        ld_assign_date_duty = []
        for dir in l_dir_pastdata:
            year_dir = int(dir[:4])
            month_dir = int(dir[4:6])
            id_month_dir = dp.cache.get_or_create(dp.service_drive, month_folder_path(year_dir, month_dir))
            d_assign_date_duty_append = read_csv(dp.service_drive, id_month_dir, 'assign_date_duty.csv')
            d_assign_date_duty_append['year'] = year_dir
            d_assign_date_duty_append['month'] = month_dir
            if 'cnt' in d_assign_date_duty_append.columns:
                d_assign_date_duty_append = d_assign_date_duty_append[d_assign_date_duty_append['cnt'] == 1]
            elif 'status' in d_assign_date_duty_append.columns:
                d_assign_date_duty_append = d_assign_date_duty_append[d_assign_date_duty_append['status'] == 'assigned']
                d_assign_date_duty_append = pd.merge(d_assign_date_duty_append, d_score_duty, how='left', on='duty')
            ld_assign_date_duty.append(d_assign_date_duty_append)
        d_assign_date_duty = pd.concat(ld_assign_date_duty)

        #d_assign_date_duty = d_assign_date_duty[d_assign_date_duty['cnt'] == 1]

    # Calculate past scores of each member

    if len(l_dir_pastdata) > 0:
        d_score_past = d_member.copy()
        for id_member in d_score_past['id_member'].tolist():
            d_score_member = d_assign_date_duty.loc[d_assign_date_duty['id_member'] == id_member, l_type_score]
            s_score_member = d_score_member.sum(axis=0)
            d_score_past.loc[d_score_past['id_member'] == id_member, l_type_score] = s_score_member.tolist()

        d_score_past.index = d_score_past['id_member'].tolist()
        d_score_past = d_score_past[['id_member'] + l_type_score]
    else:
        d_score_past = pd.DataFrame(0, index=range(len(d_member)), columns=['id_member'] + l_type_score)
        d_score_past['id_member'] = d_member['id_member'].tolist()
    return d_score_past


################################################################################
# Convert date_duty to class
################################################################################
def date_duty2class(d_date_duty, dict_class_duty):
    l_class_duty = class_duty_names(dict_class_duty)
    d_class_duty = pd.DataFrame(dict_class_duty)
    d_date_duty[['class_' + class_duty for class_duty in  l_class_duty]] = False

    for class_duty in l_class_duty:
        li_class = []
        d_class_duty_tmp = d_class_duty[d_class_duty['class'] == class_duty]
        for _, row in d_class_duty_tmp.iterrows():
            if row['date'] == 'all':
                li_temp = d_date_duty.loc[d_date_duty['duty'] == row['duty'],:].index.tolist()
            elif row['date'] == 'wd':
                li_temp = d_date_duty.loc[(d_date_duty['holiday'] == False) & (d_date_duty['duty'] == row['duty']),:].index.tolist()
            elif row['date'] == 'hd':
                li_temp =  d_date_duty.loc[(d_date_duty['holiday'] == True) & (d_date_duty['duty'] == row['duty']),:].index.tolist()
            li_class.extend(li_temp)
        li_class = sorted(list(set(li_class)))
        d_date_duty.loc[li_class, 'class_' + class_duty] = True

    s_cnt_class_duty = d_date_duty[['class_' + class_duty for class_duty in  l_class_duty]].sum(axis=0)
    s_cnt_class_duty.index = [id[6:] for id in s_cnt_class_duty.index.tolist()]

    return d_date_duty, s_cnt_class_duty
