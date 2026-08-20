
import base64, traceback
from email.mime.text import MIMEText
import pandas as pd
from script.helper import (
    prep_calendar, generate_request_update_question, generate_request_delete_item,
    ensure_member_sheet, read_member, load_drive_config, load_email_template,
)
from script.parameter import str_email_button_html
from script.drive_io import get_services, prep_drive_paths, write_csv, SCOPE_DRIVE_FORMS_GMAIL

def prepare_form(config, year_plan, month_plan, l_holiday, l_date_ect_cancel, l_day_ect, day_em, l_week_em,
                 l_class_duty, dict_duty, dict_score_duty, dict_duty_jpn, dict_title_duty, dict_class_duty,
                 str_deadline=None):

    print('[1/4] Preparing calendar and duty list...')
    services = get_services(config, SCOPE_DRIVE_FORMS_GMAIL)
    dp = prep_drive_paths(config, services, year_plan, month_plan, prefix_dir='form')

    # Prepare calendar and all duties of the month
    d_cal, d_date_duty, s_cnt_duty, s_cnt_class_duty \
        = prep_calendar(dp, l_class_duty, l_holiday, l_day_ect, l_date_ect_cancel,
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
    d_cal_duty['title_dateduty'] = d_cal_duty['title_date'] + d_cal_duty['duty_jpn']

    d_cal_duty = d_cal_duty[['date', 'wday', 'duty', 'holiday_wday','title_dateduty']]

    dict_l_form = {}
    for title in dict_title_duty.keys():
        l_duty_title = dict_title_duty[title]
        l_dateduty_holiday = d_cal_duty.loc[d_cal_duty['duty'].isin(l_duty_title) & d_cal_duty['holiday_wday'], 'title_dateduty'].tolist()
        l_dateduty = d_cal_duty.loc[d_cal_duty['duty'].isin(l_duty_title) & ~d_cal_duty['holiday_wday'], 'title_dateduty'].tolist()
        if len(l_dateduty_holiday) > 0:
            dict_l_form[title + '_holiday'] = l_dateduty_holiday
        if len(l_dateduty) > 0:
            dict_l_form[title + '_others'] = l_dateduty
    d_form = pd.DataFrame(dict([(key, pd.Series(l_form)) for key, l_form in dict_l_form.items() ]))
    # Save data
    for id_folder in [id for id in [dp.id_month, dp.id_data] if id is not None]:
        write_csv(services.drive, id_folder, 'duty.csv', d_cal_duty, index=False)
        write_csv(services.drive, id_folder, 'form.csv', d_form, index=False)

    # Create Google form
    # The month's live Drive folder (dp.id_month, "dutyshift/result/<year>/<month>/") is where
    # the form's supporting data already lives -- the form artifact itself is created directly
    # inside it.
    print('[2/4] Creating Google Form...')
    # id_template_form (the Google Form template to copy) and dict_itemid_form (that template's
    # grid-question item IDs) live on Drive (dutyshift/config/config.json), not in code -- see
    # script/helper.py::load_drive_config.
    id_config = dp.cache.get_or_create(services.drive, 'dutyshift/config')
    dict_drive_config = load_drive_config(services.drive, id_config)
    id_template_form = dict_drive_config['id_template_form']
    dict_itemid_form = dict_drive_config['dict_itemid_form']

    id_folder_data = dp.id_month
    body = {'name':'form_' + str(year_plan) + str(month_plan).zfill(2), 'parents': [id_folder_data]}
    form_copied = services.drive.files().copy(fileId=id_template_form, body=body, fields='id, name, parents').execute()

    # Update grid question rows
    id_form_copied = form_copied['id']
    l_request, l_itemid_missing = generate_request_update_question(id_form_copied, services.forms, dict_l_form, dict_itemid_form)

    # Delete missing question
    l_request = l_request + generate_request_delete_item(id_form_copied, services.forms, l_itemid_missing)

    # Update form title
    str_title = f"{year_plan}年{month_plan}月当直希望調査"
    l_request.append({"updateFormInfo": {"info": {"title": str_title},"updateMask": "title"}})

    # Execute the update
    result = services.forms.forms().batchUpdate(formId=id_form_copied, body={"requests": l_request}).execute()

    # Print responding URL
    str_responder_uri = services.forms.forms().get(formId=id_form_copied).execute().get('responderUri')
    print('Form URL:', str_responder_uri)

    ###############################################################################
    # Copy forward next month's member tab, then draft (never send) a notification email to
    # active doctors. Both best-effort and independently guarded: a failure in either must not
    # turn an otherwise-successful form creation into a reported failure, AND must not be
    # misattributed to the other step -- they use different Drive/Gmail scopes and can fail
    # for unrelated reasons (e.g. Gmail's drafts.create failing with an insufficient-scope error
    # has nothing to do with whether the member tab copy above it succeeded).
    ###############################################################################
    print('[3/4] Copying forward next month\'s roster...')
    try:
        ensure_member_sheet(services.drive, services.sheets, id_config, year_plan, month_plan)
    except Exception:
        print('[WARNING] Could not copy forward next month\'s member tab:')
        print(traceback.format_exc())

    print('[4/4] Drafting notification email...')
    try:
        if not str_deadline:
            print('No response deadline set -- skipping notification email draft.')
        else:
            d_member = read_member(services.drive, services.sheets, id_config, year_plan, month_plan)
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
