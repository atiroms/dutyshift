
import numpy as np, pandas as pd
import os, datetime
from script.helper import *
from script.check import *

def collect_availability(lp_root, year_plan, month_plan, id_sheet_response, dict_jpnday, dict_duty_jpn):

    p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = 'clct')

    # Read data
    #sheet_id = address_response.split('/')[5]
    name_sheet = "FormResponses1"
    d_availability_src = pd.read_csv(f"https://docs.google.com/spreadsheets/d/{id_sheet_response}/gviz/tq?tqx=out:csv&sheet={name_sheet}")
    d_member = read_member(p_root, year_plan, month_plan)

    # Check missing members
    l_member_ans = list(set(d_availability_src['お名前（敬称略）'].tolist()))
    l_member_active = d_member.loc[d_member['active'] == True, 'name_jpn_full'].tolist()
    l_member_missing = [m for m in l_member_active if m not in l_member_ans]
    str_member_missing = ', '.join(l_member_missing)
    l_mail_missing = d_member[d_member['name_jpn_full'].isin(l_member_missing)]['email'].tolist()
    str_mail_missing = ', '.join(l_mail_missing)

    # Format answer
    d_cal_duty = pd.read_csv(os.path.join(p_month, 'duty.csv'))
    l_col = d_availability_src.columns.tolist()

    # Collect weekly pattern
    dict_l_weekly = {}
    for key_day, item_day in dict_jpnday.items():
        for key_duty, item_duty in dict_duty_jpn.items():
            col_dayduty = item_day + '　' + item_duty
            l_col_dayduty = [col for col in l_col if ('[' + col_dayduty + ']') in col]
            if len(l_col_dayduty) > 0:
                l_availability = [np.nan] * d_availability_src.shape[0]
                for col in l_col_dayduty: # Iterate over columns of specific date_duty in columns of d_availability_src
                    l_availbility_src = d_availability_src[col].tolist()
                    for idx, availability_src in enumerate(l_availbility_src):
                        if availability_src == '不可':
                            l_availability[idx] = 0
                        elif availability_src == '可':
                            l_availability[idx] = 1
                        elif availability_src == '希望':
                            l_availability[idx] = 2
                dict_l_weekly[str(key_day) + '_' + key_duty] = l_availability
    d_weekly = pd.DataFrame(dict_l_weekly)

    # Apply weekly pattern to list of date_duty
    dict_l_availability = {}
    for idx, row in d_cal_duty.iterrows(): # Iterate over date_duty's
        title_dateduty = row['title_dateduty']
        dateduty = str(row['date']) + '_' + row['duty']
        l_col_dateduty = [col for col in l_col if ('[' + title_dateduty + ']') in col]
        day = row['wday']
        duty = row['duty']
        holiday_wday = row['holiday_wday']
        # Apply weekly pattern
        if not holiday_wday:
            l_availability = d_weekly[str(day) + '_' + duty].tolist()
        else:
            l_availability = [np.nan] * d_availability_src.shape[0]
        # Apply irregular pattern
        for col in l_col_dateduty: # Iterate over columns of specific date_duty in columns of d_availability_src
            l_availbility_src = d_availability_src[col].tolist()
            for idx, availability_src in enumerate(l_availbility_src):
                if availability_src == '不可':
                    l_availability[idx] = 0
                elif availability_src == '可':
                    l_availability[idx] = 1
                elif availability_src == '希望':
                    l_availability[idx] = 2
        dict_l_availability[dateduty] = l_availability

    d_availability = pd.DataFrame(dict_l_availability)
    #d_availability = d_availability.fillna(0)

    d_availability_head = d_availability_src[['お名前（敬称略）', 'Timestamp']].copy()
    d_availability_head.columns = ['name_jpn_full', 'timestamp']
    #d_availability_head = pd.merge(d_availability_head, d_member[['name_jpn_full', 'id_member']], on = 'name_jpn_full')
    d_availability_head['unixtime'] = d_availability_head['timestamp'].apply(lambda x: datetime.datetime.strptime(x, '%m/%d/%Y %H:%M:%S').timestamp())

    # Designation
    l_designation = [np.nan] * d_availability_src.shape[0]
    for col in [col for col in l_col if '指定医' in col]:
        l_designation_src = d_availability_src[col].tolist()
        for idx, designation_src in enumerate(l_designation_src):
            if designation_src == '指定医':
                l_designation[idx] = True
            elif designation_src == '非指定医':
                l_designation[idx] = False
    d_availability_head['designation'] = l_designation

    # Two assignments per month
    l_assign_twice = [np.nan] * d_availability_src.shape[0]
    col = [col for col in l_col if '月2回' in col][0]
    l_assign_twice_src = d_availability_src[col].tolist()
    for idx, assign_twice_src in enumerate(l_assign_twice_src):
        if assign_twice_src == '可':
            l_assign_twice[idx] = True
        elif assign_twice_src == '不可':
            l_assign_twice[idx] = False
    d_availability_head['assign_twice'] = l_assign_twice

    # Request
    col = [col for col in l_col if 'ご要望' in col][0]
    l_request = d_availability_src[col].tolist()
    d_availability_head['request'] = l_request

    # Concatenate
    d_availability = pd.concat([d_availability_head, d_availability], axis = 1)
    d_availability = pd.merge(d_availability, d_member[['name_jpn_full', 'id_member']], on = 'name_jpn_full')

    # Pick up newest of each member
    l_id_member = sorted(list(set(d_availability['id_member'].tolist())))
    l_d_availability = []
    for id_member in l_id_member:
        d_availability_member = d_availability[d_availability['id_member'] == id_member]
        d_availability_member = d_availability_member.sort_values(by = ['unixtime'], ascending = False)
        d_availability_member = d_availability_member.iloc[0]
        l_d_availability.append(d_availability_member)
    d_availability = pd.DataFrame(l_d_availability)

    # Index
    d_availability.index = d_availability['id_member'].tolist()
    d_info = d_availability[['id_member','name_jpn_full','designation','assign_twice','request']].copy()
    d_availability = d_availability[['id_member','name_jpn_full'] + list(dict_l_availability.keys())]

    # Print missing
    if len(l_member_missing) > 0:
        print('Missing members and emails:')
        print(str_member_missing)
        print(str_mail_missing)

    # Print info
    d_info_print = d_info.loc[~d_info['request'].isna(), :]
    if len(d_info_print) > 0:
        print('Requests:')
        for index, row in d_info_print.iterrows():
            print(row['name_jpn_full'], row['request'])

    # Print designation inconsistency
    for member in d_info['id_member'].tolist():
        designation_form = d_info.loc[d_info['id_member'] == member, 'designation'].tolist()[0]
        if ~np.isnan(designation_form):
            designation_src = d_member.loc[d_member['id_member'] == member, 'designation'].tolist()[0]
            if designation_form != designation_src:
                print('Inconsistent designation status, ID:', member, designation_form, designation_src)

    #d_availability = pd.read_csv(os.path.join(p_month, 'availability_src.csv'))
    d_availability.set_index('id_member', inplace = True)
    d_availability.drop(['name_jpn_full'], axis = 1, inplace = True)
    d_availability = d_availability.T

    d_availability_duty = check_availability_duty(d_member, d_availability)
    d_availability_member = check_availability_member(d_member, d_availability)

    for p_save in [p_month, p_data]:
        #d_availability.to_csv(os.path.join(p_save, 'availability_src.csv'), index = False)
        d_availability.to_csv(os.path.join(p_save, 'availability.csv'), index = True)
        d_info.to_csv(os.path.join(p_save, 'info.csv'), index = False)
        d_member.to_csv(os.path.join(p_save, 'member.csv'), index = False)
        d_availability_duty.to_csv(os.path.join(p_save, 'availability_duty.csv'), index = True)
        d_availability_member.to_csv(os.path.join(p_save, 'availability_member.csv'), index = False)

    return str_member_missing, str_mail_missing, d_availability, d_info, d_member