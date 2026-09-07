
import base64, traceback
from email.mime.text import MIMEText
import pandas as pd
from script.helper import (
    prep_calendar, build_weekly_pattern_rows,
    generate_request_update_name_choices, generate_request_update_section_nav,
    ensure_member_sheet, read_member, load_email_template,
    duty_order, duty_jpn_labels,
)
from script.parameter import (
    str_email_button_html, dict_duty_info, dict_jpnday,
    l_form_section, l_title_ask_designation, l_title_ask_assign_twice,
)
from script.drive_io import get_services, prep_drive_paths, write_csv, SCOPE_DRIVE_FORMS_GMAIL

# Grid column choices, shared by every availability grid this module creates (weekly-pattern,
# holiday, and per-date-override grids alike) -- matches what script/collect.py parses
# ('不可'/'可'/'希望' -> 0/1/2).
l_availability_choice = ['不可', '可', '希望']


def prepare_form(config, year_plan, month_plan, l_holiday, l_date_ect_cancel, l_day_ect, day_em, l_week_em,
                 dict_score_duty, dict_title_duty, dict_class_duty,
                 str_deadline=None):
    dict_duty = duty_order(dict_duty_info)
    dict_duty_jpn = duty_jpn_labels(dict_duty_info)

    print('[1/3] Preparing calendar and duty list...')
    services = get_services(config, SCOPE_DRIVE_FORMS_GMAIL)
    dp = prep_drive_paths(config, services, year_plan, month_plan, prefix_dir='form')

    # Prepare calendar and all duties of the month
    d_cal, d_date_duty, s_cnt_duty, s_cnt_class_duty \
        = prep_calendar(dp, l_holiday, l_day_ect, l_date_ect_cancel,
                        day_em, l_week_em, year_plan, month_plan, dict_score_duty, dict_class_duty)

    # Prepare calendar for google forms
    d_cal['holiday_wday'] = [a and b for a, b in zip(d_cal['wday'].isin([0, 1, 2, 3, 4]).tolist(), d_cal['holiday'].tolist())]

    l_cal_duty = []
    for duty in dict_duty_jpn.keys():
        d_cal_duty = d_cal.loc[d_cal[duty] == True, ['date', 'title_date', 'wday', 'holiday_wday']].copy()
        d_cal_duty['duty'] = duty
        l_cal_duty.append(d_cal_duty)
    d_cal_duty = pd.concat(l_cal_duty, axis=0)
    d_cal_duty['duty_sort'] = d_cal_duty['duty'].map(dict_duty)
    d_cal_duty = d_cal_duty.sort_values(by=['date', 'duty_sort'])
    d_cal_duty.index = range(len(d_cal_duty))

    d_cal_duty['duty_jpn'] = d_cal_duty['duty'].map(dict_duty_jpn)
    d_cal_duty['title_date_duty'] = d_cal_duty['title_date'] + d_cal_duty['duty_jpn']

    d_cal_duty = d_cal_duty[['date', 'wday', 'duty', 'holiday_wday','title_date_duty']]

    # Per-title date_duty lists (unchanged -- kept purely for duty.csv/form.csv, and independent
    # of how script/parameter.py::l_form_section groups titles into Google Form sections below).
    dict_l_form = {}
    for title in dict_title_duty.keys():
        l_duty_title = dict_title_duty[title]
        l_date_duty_holiday = d_cal_duty.loc[d_cal_duty['duty'].isin(l_duty_title) & d_cal_duty['holiday_wday'], 'title_date_duty'].tolist()
        l_date_duty = d_cal_duty.loc[d_cal_duty['duty'].isin(l_duty_title) & ~d_cal_duty['holiday_wday'], 'title_date_duty'].tolist()
        if len(l_date_duty_holiday) > 0:
            dict_l_form[title + '_holiday'] = l_date_duty_holiday
        if len(l_date_duty) > 0:
            dict_l_form[title + '_others'] = l_date_duty
    d_form = pd.DataFrame(dict([(key, pd.Series(l_form)) for key, l_form in dict_l_form.items() ]))
    # Save data
    for id_folder in dp.l_id_write:
        write_csv(services.drive, id_folder, 'duty.csv', d_cal_duty, index=False)
        write_csv(services.drive, id_folder, 'form.csv', d_form, index=False)

    # Create Google form from scratch (forms.create + batchUpdate) -- no template to copy. Every
    # item id the API hands back is only known after the create batchUpdate executes, and
    # per-section "go to the closing survey section" navigation can only be attached to a choice
    # question's option (there's no unconditional per-section default), so this happens in two
    # passes: create every item first, then wire up navigation once the real item ids exist.
    print('[2/3] Creating Google Form...')
    id_config = dp.id_config

    # Ensure this month's config/member tab exists (best-effort, copying forward the nearest
    # prior tab if missing -- never raises, never overwrites an existing tab) *before* reading
    # it below. This moved up from after form creation (where it ran in the old template-copy
    # flow, harmless there since that flow never read the roster until drafting the email) --
    # the from-scratch name dropdown now needs the roster to already exist at this point.
    try:
        ensure_member_sheet(services.drive, services.sheets, id_config, year_plan, month_plan)
    except Exception:
        print('[WARNING] Could not ensure this month\'s member tab exists:')
        print(traceback.format_exc())

    # config/member is required, not best-effort, here: unlike the old template-copy flow, there
    # is no fallback content for the name dropdown if this fails -- without it the form has no
    # way to route a respondent to their own section, so a read failure should abort form
    # creation rather than silently produce an unusable form.
    d_member = read_member(services.drive, services.sheets, id_config, year_plan, month_plan)

    str_title = f"{year_plan}年{month_plan}月当直希望調査"
    str_description = 'なるべく「不可」を少なくしていただくようにお願いします'
    str_documenttitle = 'form_' + str(year_plan) + str(month_plan).zfill(2)

    # forms.create only accepts info.title/info.documentTitle -- everything else (description,
    # settings, items) has to follow via batchUpdate.
    form_created = services.forms.forms().create(
        body={'info': {'title': str_title, 'documentTitle': str_documenttitle}}).execute()
    id_form = form_created['formId']

    # forms.create can't place the file in a folder -- move it into this month's live Drive
    # folder (dp.id_month, "dutyshift/result/<year>/<month>/") to match where the old
    # copy-a-template flow always created it.
    dict_file = services.drive.files().get(fileId=id_form, fields='parents').execute()
    str_parents_old = ','.join(dict_file.get('parents', []))
    services.drive.files().update(fileId=id_form, addParents=dp.id_month,
                                  removeParents=str_parents_old, fields='id, parents').execute()

    # ---- Pass 1: create every item -----------------------------------------------------------
    l_request1 = [
        {"updateSettings": {"settings": {"emailCollectionType": "RESPONDER_INPUT"},
                            "updateMask": "emailCollectionType"}},
        {"updateFormInfo": {"info": {"description": str_description}, "updateMask": "description"}},
    ]
    dict_reqidx = {}  # semantic key -> index into l_request1, to read the matching reply back
    n_item = [0]       # running item location.index (list so the closure below can mutate it)

    def add_item(key, item):
        dict_reqidx[key] = len(l_request1)
        l_request1.append({"createItem": {"item": item, "location": {"index": n_item[0]}}})
        n_item[0] += 1

    def choice_item(title, choice_type, l_option, required=True):
        return {"title": title, "questionItem": {"question": {
            "required": required,
            "choiceQuestion": {"type": choice_type, "options": [{"value": v} for v in l_option]},
        }}}

    def grid_item(title, l_row):
        return {"title": title, "questionGroupItem": {
            "questions": [{"required": True, "rowQuestion": {"title": row}} for row in l_row],
            "grid": {"columns": {"type": "RADIO",
                                 "options": [{"value": v} for v in l_availability_choice]}},
        }}

    # Name dropdown -- placeholder options for now; script/helper.py::generate_request_update_name_choices
    # replaces them with this month's active roster in pass 2, once every section's item id (each
    # option's goToSectionId target) is known.
    add_item('name', choice_item('お名前（敬称略）', 'DROP_DOWN', ['(準備中)']))

    for str_section, l_title_section in l_form_section:
        add_item(('section', str_section), {"title": str_section, "pageBreakItem": {}})

        if any(title in l_title_ask_designation for title in l_title_section):
            add_item(('designation', str_section),
                     choice_item('指定医の有無', 'DROP_DOWN', ['指定医', '非指定医']))

        if any(title in l_title_ask_assign_twice for title in l_title_section):
            add_item(('assign_twice', str_section),
                     choice_item('月2回ご担当の可否', 'RADIO', ['可', '不可']))

        l_duty_section = sorted(set().union(*[set(dict_title_duty[title]) for title in l_title_section]))
        l_row_weekly = build_weekly_pattern_rows(l_duty_section, dict_duty_info, dict_jpnday)
        if l_row_weekly:
            add_item(('weekly', str_section), grid_item('週間パターン', l_row_weekly))

        l_row_holiday = d_cal_duty.loc[d_cal_duty['duty'].isin(l_duty_section) & d_cal_duty['holiday_wday'], 'title_date_duty'].tolist()
        if l_row_holiday:
            add_item(('holiday', str_section), grid_item('祝日', l_row_holiday))

        l_row_others = d_cal_duty.loc[d_cal_duty['duty'].isin(l_duty_section) & ~d_cal_duty['holiday_wday'], 'title_date_duty'].tolist()
        if l_row_others:
            add_item(('others', str_section), grid_item('日付ごとの指定', l_row_others))

        # Forms has no "after this section, go to X" setting independent of a choice question's
        # option -- this required single-choice question is the only way to send every
        # respondent straight to the closing survey section instead of falling through into the
        # next section. Its one option's goToSectionId is filled in during pass 2.
        add_item(('confirm', str_section),
                 choice_item('以上で入力は完了です。「次へ」を選択して送信ページへ進んでください。', 'RADIO', ['次へ']))

    add_item('survey_pagebreak', {"title": "アンケート",
                                  "description": "今後の改善のためにご協力をお願いします",
                                  "pageBreakItem": {}})
    add_item('survey_text', {"title": "ご意見、ご要望等",
                             "questionItem": {"question": {"textQuestion": {"paragraph": True}}}})

    result1 = services.forms.forms().batchUpdate(formId=id_form, body={"requests": l_request1}).execute()
    l_reply1 = result1.get('replies', [])

    def itemid(key):
        return l_reply1[dict_reqidx[key]]['createItem']['itemId']

    id_item_name = itemid('name')
    id_item_survey = itemid('survey_pagebreak')
    dict_sectionid_title = {title: itemid(('section', str_section))
                            for str_section, l_title_section in l_form_section for title in l_title_section}

    # ---- Pass 2: wire up navigation now that every item id is known --------------------------
    request_name, l_title_unmapped = generate_request_update_name_choices(
        id_form, services.forms, d_member, dict_sectionid_title, id_item_name)
    if l_title_unmapped:
        print('[WARNING] Active doctor(s) with a title_short not covered by l_form_section (excluded from the form\'s name dropdown):', l_title_unmapped)
    l_request2 = [request_name]
    for str_section, l_title_section in l_form_section:
        l_request2.append(generate_request_update_section_nav(
            id_form, services.forms, itemid(('confirm', str_section)), id_item_survey))

    services.forms.forms().batchUpdate(formId=id_form, body={"requests": l_request2}).execute()

    # Print responding URL
    str_responder_uri = services.forms.forms().get(formId=id_form).execute().get('responderUri')
    print('Form URL:', str_responder_uri)

    ###############################################################################
    # Draft (never send) a notification email to active doctors. Best-effort and isolated from
    # everything above -- a Gmail error here (e.g. an insufficient-scope error) must not turn an
    # otherwise-successful form creation into a reported failure.
    ###############################################################################
    print('[3/3] Drafting notification email...')
    try:
        if not str_deadline:
            print('No response deadline set -- skipping notification email draft.')
        else:
            # Reuse the roster read above (used to build the name dropdown) -- nothing between
            # there and here can have changed it.
            d_member_active = d_member.loc[d_member['active'] == True, :]
            l_email_active = [email for email in d_member_active['email'].tolist()
                              if isinstance(email, str) and email.strip()]
            n_missing_email = len(d_member_active) - len(l_email_active)
            if n_missing_email > 0:
                print('[WARNING]', n_missing_email, 'active doctor(s) have no email on file -- excluded from the draft.')

            if len(l_email_active) == 0:
                print('No active doctors with an email on file -- skipping notification email draft.')
            else:
                id_template = dp.cache.get_or_create(services.drive, 'dutyshift/template')
                dict_email = load_email_template(services.drive, id_template, 'announce')
                str_button = str_email_button_html.format(url=str_responder_uri, label=dict_email['button_label'])
                str_body = dict_email['body'].format(button=str_button, deadline=str_deadline)
                message = MIMEText(str_body, 'html')
                message['bcc'] = ', '.join(l_email_active)
                message['subject'] = dict_email['subject'].format(deadline=str_deadline)
                str_raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
                services.gmail.users().drafts().create(userId='me', body={'message': {'raw': str_raw}}).execute()
                print('Drafted notification email to', len(l_email_active), 'active doctor(s) (not sent).')
    except Exception:
        print('[WARNING] Could not draft the notification email:')
        print(traceback.format_exc())

    print('Done')
    return d_cal, d_date_duty, s_cnt_duty, s_cnt_class_duty, d_cal_duty, d_form
