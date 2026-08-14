
import numpy as np, pandas as pd
from script.helper import *
from script.drive_io import get_services, prep_drive_paths, read_csv, write_csv, SCOPE_DRIVE_FORMS
#from script.notify import *


def check_replacement(config, year_plan, month_plan):
    services = get_services(config, SCOPE_DRIVE_FORMS)
    dp = prep_drive_paths(config, services.drive, year_plan, month_plan, prefix_dir = '', make_data_dir = False)


    ###############################################################################
    # Read and convert data
    ###############################################################################
    d_member = read_csv(services.drive, dp.id_month, 'member.csv')
    d_member['name_jpn_full'] = d_member['name_jpn_full'].str.replace('　',' ')
    d_assign_date_duty = read_csv(services.drive, dp.id_month, 'assign_date_duty.csv')


    #sheet_name = "response"
    #d_replace = pd.read_csv(f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}")
    # Static path -- the standing shift-swap request form is not year/month-specific, unlike the
    # monthly availability form, so it's unaffected by that folder-convention change.
    path_form = '/dutyshift/result/replacement/replacement'
    d_replace = read_form_response(services, path_form)

    d_replace = d_replace.sort_values(by = 'Timestamp')
    d_replace = d_replace[['交代する日付','交代する業務','交代後の担当者（敬称略）']]
    d_replace = d_replace.rename(columns={'交代する日付':'ymd','交代する業務':'duty','交代後の担当者（敬称略）':'name_jpn_full'})
    d_replace['year'] = [int(ymd.split('-')[0]) for ymd in d_replace['ymd']]
    d_replace['month'] = [int(ymd.split('-')[1]) for ymd in d_replace['ymd']]
    d_replace['date'] = [int(ymd.split('-')[2]) for ymd in d_replace['ymd']]
    d_replace = d_replace[(d_replace['year'] == year_plan) & (d_replace['month'] == month_plan)]
    d_replace = pd.merge(d_replace, d_member[['name_jpn_full','id_member','name','name_jpn']], on = 'name_jpn_full', how = 'left')
    dict_replace = {'午前日直':'am', '午後日直':'pm', '休日日直':'day', '当直':'night', '日直オンコール':'ocday','当直オンコール':'ocnight','ECT当番':'ect'}
    d_replace['duty'] = [dict_replace[duty] for duty in d_replace['duty']]


    ###############################################################################
    # Check data and delete duplication
    # d_replace_checked as result
    ###############################################################################
    # Delete duplicate data in d_replace
    d_replace_checked = pd.DataFrame(columns = d_replace.columns)
    for id, row in d_replace.iterrows():
        row_duplicate = d_replace_checked.loc[(d_replace_checked['ymd'] == row['ymd']) & (d_replace_checked['duty'] == row['duty']), :]
        if len(row_duplicate) > 0: # Overwirte if duplicate
            d_replace_checked.loc[(d_replace_checked['ymd'] == row['ymd']) & (d_replace_checked['duty'] == row['duty']), :] = row.to_list()
        else:
            d_replace_checked.loc[len(d_replace_checked), :] = row

    # Delete already replaced data
    for id, row in d_replace_checked.iterrows():
        id_member_src = d_assign_date_duty.loc[(d_assign_date_duty['date'] == row['date']) & (d_assign_date_duty['duty'] == row['duty']), 'id_member'].tolist()[0]
        if row['id_member'] == id_member_src: # already replaced
            d_replace_checked = d_replace_checked.drop(id)
        elif np.isnan(row['id_member']) and np.isnan(id_member_src):
            d_replace_checked = d_replace_checked.drop(id)
        else:
            if np.isnan(id_member_src):
                name_jpn_src = np.nan
            else:
                name_jpn_src = d_member.loc[d_member['id_member'] == id_member_src, 'name_jpn'].tolist()[0]
            d_replace_checked.loc[id, 'name_jpn_src'] = name_jpn_src

    d_replace_checked.index = [i for i in range(len(d_replace_checked))]

    if len(d_replace_checked) > 0:
        d_replace_print = d_replace_checked[['month', 'date', 'duty', 'name_jpn_src', 'name_jpn']]
        d_replace_print.columns = ['month', 'date', 'duty', 'before', 'after']

        print('Replacing:')
        print(d_replace_print)
    else:
        print('No new data detected')

    return d_replace_checked


def replace_assignment(config, year_plan, month_plan, dict_score_duty, l_class_duty, d_replace_checked = None):
    services = get_services(config, SCOPE_DRIVE_FORMS)
    dp = prep_drive_paths(config, services.drive, year_plan, month_plan, prefix_dir = 'rplc')

    ###############################################################################
    # Replace data
    # update d_assign_duty according to d_replace_checked
    ###############################################################################

    # OPTIONAL: specify which replacement to execute
    #li_replace = [0, 1]
    #d_replace_checked = d_replace_checked.loc[li_replace, :]

    d_assign_date_duty = read_csv(services.drive, dp.id_month, 'assign_date_duty.csv')

    # TODO: consider desiganation status difference
    if d_replace_checked is not None:
        for id, row in d_replace_checked.iterrows():
            if np.isnan(row['id_member']):
                d_assign_date_duty.loc[(d_assign_date_duty['date'] == row['date']) & (d_assign_date_duty['duty'] == row['duty']), ['id_member', 'status']] = [row['id_member'], 'unnecessary']
            else:
                d_assign_date_duty.loc[(d_assign_date_duty['date'] == row['date']) & (d_assign_date_duty['duty'] == row['duty']), ['id_member', 'status']] = [row['id_member'], 'assigned']

    d_availability_noskip = read_csv(services.drive, dp.id_month, 'availability.csv', index_col = 0)
    d_date_duty = read_csv(services.drive, dp.id_month, 'date_duty.csv')
    d_lim_exact = read_csv(services.drive, dp.id_month, 'lim_exact.csv', index_col = 0)
    d_lim_hard = read_csv(services.drive, dp.id_month, 'lim_hard.csv', index_col = 0)
    for index in d_lim_hard.index:
        for col in d_lim_hard.columns:
            src = d_lim_hard.loc[index, col]
            src_min = float(src[1:-1].split(', ')[0])
            src_max = float(src[1:-1].split(', ')[1])
            dst = [src_min, src_max]
            d_lim_hard.loc[index, col] = dst

    for id_folder in [id for id in [dp.id_month, dp.id_data] if id is not None]:
        # TODO: convert d_assign
        #write_csv(services.drive, id_folder, 'assign.csv', d_assign, index = True)
        write_csv(services.drive, id_folder, 'assign_date_duty.csv', d_assign_date_duty, index = False)

    d_cal = read_csv(services.drive, dp.id_month, 'calendar.csv')
    d_member = read_csv(services.drive, dp.id_month, 'member.csv')
    d_member['name_jpn_full'] = d_member['name_jpn_full'].str.replace('　',' ')

    d_assign, d_assign_date_print, d_assign_member, d_deviation, d_deviation_summary, d_score_current, d_score_total, d_score_print =\
        convert_assignment(dp, d_assign_date_duty, d_availability_noskip,
                        d_member, d_date_duty, d_cal, l_class_duty, dict_score_duty, d_lim_exact, d_lim_hard)

    return d_assign, d_assign_date_print, d_assign_member, d_deviation, d_deviation_summary, d_score_current, d_score_total, d_score_print
