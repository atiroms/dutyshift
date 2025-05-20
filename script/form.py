
import os
import pandas as pd
from googleapiclient.discovery import build
from script.helper import *

def prepare_form(lp_root, year_plan, month_plan, l_holiday, l_date_ect_cancel, l_day_ect, day_em, l_week_em,
                 l_class_duty, dict_duty, dict_score_duty, dict_duty_jpn, dict_title_duty, dict_class_duty,
                 id_template_form, dict_itemid_form):

    p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = 'form')

    # Prepare calendar and all duties of the month
    d_cal, d_date_duty, s_cnt_duty, s_cnt_class_duty \
        = prep_calendar(p_root, p_month, p_data, l_class_duty, l_holiday, l_day_ect, l_date_ect_cancel,
                        day_em, l_week_em, year_plan, month_plan, dict_score_duty, dict_class_duty)

    # Prepare calendar for google forms
    d_cal['holiday_wday'] = [a and b for a, b in zip(d_cal['wday'].isin([0, 1, 2, 3, 4]).tolist(), d_cal['holiday'].tolist())]

    l_cal_duty = []
    for duty in dict_duty_jpn.keys():
        d_cal_duty = d_cal.loc[d_cal[duty] == True, ['date', 'title_date', 'wday', 'holiday_wday']].copy()
        d_cal_duty['duty'] = duty
        l_cal_duty.append(d_cal_duty)
    d_cal_duty = pd.concat(l_cal_duty, axis = 0)
    d_cal_duty['duty_sort'] = d_cal_duty['duty'].map(dict_duty)
    d_cal_duty = d_cal_duty.sort_values(by = ['date', 'duty_sort'])
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
    for p_save in [p_month, p_data]:
        d_cal_duty.to_csv(os.path.join(p_save, 'duty.csv'), index = False)
        d_form.to_csv(os.path.join(p_save, 'form.csv'), index = False)

    # Create Google form
    # Prepare credentials and services
    l_scope = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/forms.body']
    creds = prep_api_creds(p_root, l_scope)
    service_drive = build('drive', 'v3', credentials = creds)
    service_forms = build('forms', 'v1', credentials = creds)

    # Create data folderin Google drive
    result_folder = create_gdrive_path(service_drive, '/dutyshift/result/' + str(year_plan) + '/' + str(month_plan).zfill(2))

    # Copy forms template
    id_folder_data   = result_folder[-1]
    body = {'name':'form_' + str(year_plan) + str(month_plan).zfill(2), 'parents': [id_folder_data]}
    form_copied = service_drive.files().copy(fileId = id_template_form, body = body, fields = 'id, name, parents').execute()

    # Update grid question rows
    id_form_copied = form_copied['id']
    l_request, l_itemid_missing = generate_request_update_question(id_form_copied, service_forms, dict_l_form, dict_itemid_form)
    
    # Delete missing question
    l_request = l_request + generate_request_delete_item(id_form_copied, service_forms, l_itemid_missing)

    # Update form title
    l_request.append({"updateFormInfo": {"info": {"title": f"{year_plan}年{month_plan}月当直希望調査"},"updateMask": "title"}})

    # Execute the update
    result = service_forms.forms().batchUpdate(formId = id_form_copied, body={"requests": l_request}).execute()

    # Print responding URL
    print('Form URL:', service_forms.forms().get(formId = id_form_copied).execute().get('responderUri'))

    return d_cal, d_date_duty, s_cnt_duty, s_cnt_class_duty, d_cal_duty, d_form