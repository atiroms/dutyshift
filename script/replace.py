
import numpy as np, pandas as pd
import os
from script.helper import *
#from script.notify import *


def check_replacement(lp_root, year_plan, month_plan, sheet_id):
    p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = '', make_data_dir = False)


    ###############################################################################
    # Read and convert data
    ###############################################################################
    d_member = pd.read_csv(os.path.join(p_month, 'member.csv'))
    d_member['name_jpn_full'] = d_member['name_jpn_full'].str.replace('　',' ')
    d_assign_date_duty = pd.read_csv(os.path.join(p_month, 'assign_date_duty.csv'))

    #f_answer = os.listdir(os.path.join(p_month, 'src'))
    #f_answer = [f for f in f_answer if '当直交代申請' in f][0]
    #d_replace = pd.read_csv(os.path.join(p_month, 'src',f_answer))
    sheet_name = "response"
    d_replace = pd.read_csv(f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}")

    d_replace = d_replace[['交代する日付','交代する業務','交代後の担当者（敬称略）']]
    d_replace = d_replace.rename(columns={'交代する日付':'ymd','交代する業務':'duty','交代後の担当者（敬称略）':'name_jpn_full'})
    d_replace['year'] = [int(ymd.split('/')[0]) for ymd in d_replace['ymd']]
    d_replace['month'] = [int(ymd.split('/')[1]) for ymd in d_replace['ymd']]
    d_replace['date'] = [int(ymd.split('/')[2]) for ymd in d_replace['ymd']]
    d_replace = d_replace[(d_replace['year'] == year_plan) & (d_replace['month'] == month_plan)]
    d_replace = pd.merge(d_replace, d_member[['name_jpn_full','id_member','name','name_jpn']], on='name_jpn_full', how='left')
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
        member_src = d_assign_date_duty.loc[(d_assign_date_duty['date'] == row['date']) & (d_assign_date_duty['duty'] == row['duty']), ['id_member', 'name_jpn']]
        if row['id_member'] == member_src['id_member'].tolist()[0]: # already replaced
            d_replace_checked = d_replace_checked.drop(id)
        elif np.isnan(row['id_member']) and np.isnan(member_src['id_member'].tolist()[0]):
            d_replace_checked = d_replace_checked.drop(id)
        else:
            d_replace_checked.loc[id, 'name_jpn_src'] = member_src['name_jpn'].tolist()[0]

    d_replace_checked.index = [i for i in range(len(d_replace_checked))]

    if len(d_replace_checked) > 0:
        d_replace_print = d_replace_checked[['month', 'date', 'duty', 'name_jpn_src', 'name_jpn']]
        d_replace_print.columns = ['month', 'date', 'duty', 'before', 'after']

        print('Replacing:')
        print(d_replace_print)
    else:
        print('No new data detected')

    return d_replace_checked


def replace_assignment(lp_root, year_plan, month_plan, l_type_score, l_class_duty, d_replace_checked = None):
    p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = 'rplc')

    ###############################################################################
    # Replace data
    # update d_assign_duty according to d_replace_checked
    ###############################################################################

    # OPTIONAL: specify which replacement to execute
    #li_replace = [0, 1]
    #d_replace_checked = d_replace_checked.loc[li_replace, :]
                
    d_assign_date_duty = pd.read_csv(os.path.join(p_month, 'assign_date_duty.csv'))

    # TODO: consider desiganation status difference
    if d_replace_checked is not None:
        for id, row in d_replace_checked.iterrows():
            d_assign_date_duty.loc[(d_assign_date_duty['date'] == row['date']) & (d_assign_date_duty['duty'] == row['duty']), ['id_member','name','name_jpn']] = row[['id_member','name','name_jpn']].tolist()

    d_availability = pd.read_csv(os.path.join(p_month, 'availability.csv'), index_col = 0)
    d_date_duty = pd.read_csv(os.path.join(p_month, 'date_duty.csv'))
    d_lim_exact = pd.read_csv(os.path.join(p_month, 'lim_exact.csv'), index_col = 0)
    d_lim_hard = pd.read_csv(os.path.join(p_month, 'lim_hard.csv'), index_col = 0)
    for index in d_lim_hard.index:
        for col in d_lim_hard.columns:
            src = d_lim_hard.loc[index, col]
            src_min = float(src[1:-1].split(', ')[0])
            src_max = float(src[1:-1].split(', ')[1])
            dst = [src_min, src_max]
            d_lim_hard.loc[index, col] = dst

    for p_save in [p_month, p_data]:
        # TODO: convert d_assign
        #d_assign.to_csv(os.path.join(p_save, 'assign.csv'), index = True)
        d_assign_date_duty.to_csv(os.path.join(p_save, 'assign_date_duty.csv'), index = False)

    d_cal = pd.read_csv(os.path.join(p_month, 'calendar.csv'))
    d_member = pd.read_csv(os.path.join(p_month, 'member.csv'))
    d_member['name_jpn_full'] = d_member['name_jpn_full'].str.replace('　',' ')

    d_assign, d_assign_date_print, d_assign_member, d_deviation, d_deviation_summary, d_score_current, d_score_total, d_score_print =\
        convert_result(p_month, p_data, d_assign_date_duty, d_availability, 
                       d_member, d_date_duty, d_cal, l_class_duty, l_type_score, d_lim_exact, d_lim_hard)
    
    return d_assign, d_assign_date_print, d_assign_member, d_deviation, d_deviation_summary, d_score_current, d_score_total, d_score_print
