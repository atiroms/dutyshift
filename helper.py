
###############################################################################
# Libraries
###############################################################################
import datetime, calendar, os
import numpy as np, pandas as pd
from math import ceil
from pulp import *
from ortoolpy import addvars, addbinvars


################################################################################
# Optimize exact count of assignment
################################################################################
def optimize_count(d_member, s_cnt_class_duty, d_lim_hard, d_score_past, d_score_class,
                   d_grp_score, dict_c_diff_score_current, dict_c_diff_score_total, l_type_score, l_class_duty):

    # Dataframe of variables
    l_member = d_member['id_member'].tolist()
    l_lim_exact = [str(p[0]) + '_' + p[1] for p in itertools.product(l_member, l_class_duty)]
    dict_v_lim_exact = LpVariable.dicts(name = 'cnt', indices = l_lim_exact, lowBound = 0, upBound = None,  cat = 'Integer')
    lv_lim_exact = list(dict_v_lim_exact.values())
    llv_lim_exact = [lv_lim_exact[i:i+len(l_class_duty)] for i in range(0, len(lv_lim_exact), len(l_class_duty))]
    dv_lim_exact = pd.DataFrame(llv_lim_exact, index = l_member, columns = l_class_duty)

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
                                    index = l_member, columns = l_type_score)
    dv_score_total = pd.DataFrame(np.array(addvars(len(l_member), len(l_type_score))),
                            index = l_member, columns = l_type_score)
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
            prob_cnt += (dv_score_total.loc[member, type_score] == \
                         dv_score_current.loc[member, type_score] + \
                         d_score_past.loc[d_score_past['id_member'] == member, type_score].values[0])

    # Calculate sum of score differences
    n_grp_max = d_grp_score.max().max() + 1
    # Sum of inter-member differences of current month scores
    dv_sigma_diff_score_current = pd.DataFrame(np.array(addvars(n_grp_max, len(l_type_score))),
                                               index = range(n_grp_max), columns = l_type_score)
    # Sum of inter-member differences of current + past month score
    dv_sigma_diff_score_total = pd.DataFrame(np.array(addvars(n_grp_max, len(l_type_score))),
                                             index = range(n_grp_max), columns = l_type_score)
    dict_dv_diff_score_current = {}                    
    dict_dv_diff_score_total = {}
    for type_score in l_type_score:
        dict_dv_diff_score_current[type_score] = pd.DataFrame(np.array(addvars(len(l_member),len(l_member))), index = l_member, columns = l_member)                        
        dict_dv_diff_score_total[type_score] = pd.DataFrame(np.array(addvars(len(l_member),len(l_member))), index = l_member, columns = l_member)                        

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
    v_objective = value(prob_cnt.objective)
    print('Solved: ' + str(LpStatus[prob_cnt.status]) + ', ' + str(round(v_objective, 2)))

    # Extract data
    d_lim_exact = pd.DataFrame(np.vectorize(value)(dv_lim_exact),
                              columns = dv_lim_exact.columns, index = dv_lim_exact.index)
    d_score_current = pd.DataFrame(np.vectorize(value)(dv_score_current),
                                   columns = dv_score_current.columns, index = dv_score_current.index)
    d_score_total = pd.DataFrame(np.vectorize(value)(dv_score_total),
                                 columns = dv_score_total.columns, index = dv_score_total.index)
    d_sigma_diff_score_current = pd.DataFrame(np.vectorize(value)(dv_sigma_diff_score_current),
                                              columns = dv_sigma_diff_score_current.columns, index = dv_sigma_diff_score_current.index)
    d_sigma_diff_score_total = pd.DataFrame(np.vectorize(value)(dv_sigma_diff_score_total),
                                            columns = dv_sigma_diff_score_total.columns, index = dv_sigma_diff_score_total.index)

    return d_lim_exact, d_score_current, d_score_total, d_sigma_diff_score_current, d_sigma_diff_score_total


################################################################################
# Prepare data of member specs and assignment limits
################################################################################
def prep_member2(p_root, p_month, p_data, f_member, l_class_duty, year_plan, month_plan):
    l_col_member = ['id_member','name_jpn','name_jpn_full','email','title_jpn',
                    'designation_jpn','ect_asgn_jpn','name','title_short',
                    'designation', 'team', 'ect_leader', 'ect_subleader']

    # Load source member and assignment limit of the month
    d_src = pd.read_csv(os.path.join(p_month, 'src', f_member))
    l_col_member = [col for col in l_col_member if col in d_src.columns]
    d_member = d_src[l_col_member]
    d_lim = d_src[l_class_duty].copy()
    d_lim.index = d_member['id_member'].tolist()

    # Calculate past scores
    d_score_past = past_score(p_root, d_member, year_plan, month_plan)

    # Split assignment limit data into hard and soft
    d_lim_hard, d_lim_soft = split_lim(d_lim, l_class_duty)

    # Dataframe of score equilization groups
    d_grp_score = d_src[[col for col in d_src.columns if col.startswith('grp_')]].copy()
    d_grp_score.columns = [x[4:] for x in d_grp_score.columns]
    d_grp_score.index = d_member['id_member'].tolist()
    d_grp_score = d_grp_score.replace('-', np.nan)
    d_grp_score = d_grp_score.astype('Int64')

    # Save data
    for p_save in [p_month, p_data]:
        d_member.to_csv(os.path.join(p_save, 'member.csv'), index = False)
        d_score_past.to_csv(os.path.join(p_save, 'score_past.csv'), index = False)
        d_lim_hard.to_csv(os.path.join(p_save, 'lim_hard.csv'), index = False)
        d_lim_soft.to_csv(os.path.join(p_save, 'lim_soft.csv'), index = False)
        d_grp_score.to_csv(os.path.join(p_save, 'grp_score.csv'), index = False)

    return d_member, d_score_past, d_lim_hard, d_lim_soft, d_grp_score


################################################################################
# Extract optimization parameters
################################################################################
def prep_optim(p_dst, dv_outlier_soft,dv_score_sigmadiff, v_assign_suboptimal, c_outlier_soft,
               c_scorediff_ampm, c_scorediff_daynight, c_scorediff_ampmdaynight,
               c_scorediff_oc, c_scorediff_ect, c_assign_suboptimal):
    d_outlier_soft = pd.DataFrame(np.vectorize(value)(dv_outlier_soft),
                        columns = dv_outlier_soft.columns, index = dv_outlier_soft.index).astype(float)
    d_scorediff_sum = pd.DataFrame(np.vectorize(value)(dv_score_sigmadiff),
                        columns = dv_score_sigmadiff.columns, index = dv_score_sigmadiff.index).astype(float)
    v_assign_suboptimal = value(v_assign_suboptimal)

    # Optimization results
    d_optimization = pd.DataFrame([['outlier_soft', c_outlier_soft, d_outlier_soft.sum().sum()],
                                   #['scorediff_ampm',c_scorediff_ampm, d_scorediff_sum['ampm'].sum()],
                                   #['scorediff_daynight',c_scorediff_daynight, d_scorediff_sum['daynight'].sum()],
                                   ['scorediff_ampmdaynight',c_scorediff_ampmdaynight, d_scorediff_sum['ampmdaynight'].sum()],
                                   ['scorediff_oc',c_scorediff_oc, d_scorediff_sum['oc'].sum()],
                                   ['scorediff_ect',c_scorediff_ect, d_scorediff_sum['ect'].sum()],
                                   ['assign_suboptimal', c_assign_suboptimal, v_assign_suboptimal]],
                                   columns = ['term','constant','value'])
    d_optimization['product'] = d_optimization['constant'] * d_optimization['value']
    d_optimization = pd.concat([d_optimization,
                                pd.DataFrame([['total', None, None, d_optimization['product'].sum()]],
                                             columns = d_optimization.columns)],
                                axis = 0)
    
    d_optimization.to_csv(os.path.join(p_dst,'optimizaion.csv'), index = False)

    return d_optimization


################################################################################
# Extract data from optimized variables
################################################################################
def prep_assign2(p_data, dv_assign, d_availability, d_member, l_member, d_date_duty, d_cal):
    d_assign = pd.DataFrame(np.vectorize(value)(dv_assign),
                            index = dv_assign.index, columns = dv_assign.columns).astype(bool)

    # Assignments with date_duty as row
    # TODO: em column in assign_date_duty.csv file
    d_assign_date_duty = pd.concat([pd.Series(d_assign.index, index = d_assign.index, name = 'date_duty'),
                               pd.Series(d_assign.sum(axis = 1), name = 'cnt'),
                               pd.Series(d_assign.apply(lambda row: row[row].index.to_list(), axis = 1), name = 'id_member')],
                               axis = 1)
    d_assign_date_duty.index = range(len(d_assign_date_duty))
    d_assign_date_duty['id_member'] = d_assign_date_duty['id_member'].apply(lambda x: x[0] if len(x) > 0 else np.nan)
    d_assign_date_duty = pd.merge(d_assign_date_duty, d_member.loc[:,['id_member','name_jpn','name']], on = 'id_member', how = 'left')
    d_assign_date_duty = pd.merge(d_assign_date_duty, d_date_duty, on = 'date_duty', how = 'left')
    d_assign_date_duty = d_assign_date_duty.loc[:,['date_duty', 'date','duty', 'id_member','name','name_jpn','cnt']]
    d_assign_date_duty.to_csv(os.path.join(p_data, 'assign_date_duty.csv'), index = False)

    # Assignments with date as row for printing
    d_assign_date_print = d_cal.loc[:,['title_date','date', 'em']].copy()
    d_assign_date_print[['am','pm','night','ocday','ocnight','ect']] = ''
    for _, row in d_assign_date_duty.loc[d_assign_date_duty['cnt'] > 0].iterrows():
        date = row['date']
        duty = row['duty']
        name_jpn = row['name_jpn']
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
    d_assign_date_print.to_csv(os.path.join(p_data, 'assign_date.csv'), index = False)

    # Assignments with member as row
    d_assign_optimal = pd.DataFrame((d_availability == 2) & d_assign, columns = l_member, index = d_assign.index)                         
    d_assign_suboptimal = pd.DataFrame((d_availability == 1) & d_assign, columns = l_member, index = d_assign.index)
    #d_assign_error = pd.DataFrame((d_availability == 0) & d_assign, columns = l_member, index = d_assign.index)
    d_assign_member = pd.DataFrame({'id_member': l_member,
                                    'name_jpn': d_member.loc[d_member['id_member'].isin(l_member),'name_jpn'].tolist(),
                                    'duty_all': d_assign.apply(lambda col: col[col].index.to_list(), axis = 0),
                                    'duty_opt': d_assign_optimal.apply(lambda col: col[col].index.to_list(), axis = 0),
                                    'duty_sub': d_assign_suboptimal.apply(lambda col: col[col].index.to_list(), axis = 0),
                                    'cnt_all': d_assign.sum(axis = 0),
                                    'cnt_opt': d_assign_optimal.sum(axis = 0),
                                    'cnt_sub': d_assign_suboptimal.sum(axis = 0)},
                                    index = l_member)
    d_assign_member.to_csv(os.path.join(p_data, 'assign_member.csv'), index = False)

    return d_assign_date_duty, d_assign_date_print, d_assign_member

def prep_assign(p_dst, dv_assign, dv_score, d_score_history,
                d_availability, d_member, l_member, d_date_duty, d_cal):
    d_assign = pd.DataFrame(np.vectorize(value)(dv_assign),
                            index = dv_assign.index, columns = dv_assign.columns).astype(bool)
    d_score_sigma = pd.DataFrame(np.vectorize(value)(dv_score),
                                 index = dv_score.index, columns = dv_score.columns).astype(float)

    # Assignments with date_duty as row
    # TODO: em column in assign_date_duty.csv file
    d_assign_date_duty = pd.concat([pd.Series(d_assign.index, index = d_assign.index, name = 'date_duty'),
                               pd.Series(d_assign.sum(axis = 1), name = 'cnt'),
                               pd.Series(d_assign.apply(lambda row: row[row].index.to_list(), axis = 1), name = 'id_member')],
                               axis = 1)
    d_assign_date_duty.index = range(len(d_assign_date_duty))
    d_assign_date_duty['id_member'] = d_assign_date_duty['id_member'].apply(lambda x: x[0] if len(x) > 0 else np.nan)
    d_assign_date_duty = pd.merge(d_assign_date_duty, d_member.loc[:,['id_member','name_jpn','name']], on = 'id_member', how = 'left')
    d_assign_date_duty = pd.merge(d_assign_date_duty, d_date_duty, on = 'date_duty', how = 'left')
    d_assign_date_duty = d_assign_date_duty.loc[:,['date_duty', 'date','duty', 'id_member','name','name_jpn','cnt']]
    d_assign_date_duty.to_csv(os.path.join(p_dst, 'assign_date_duty.csv'), index = False)

    # Assignments with date as row for printing
    d_assign_date_print = d_cal.loc[:,['title_date','date','em']].copy()
    d_assign_date_print[['am','pm','night','ocday','ocnight','ect']] = ''
    for _, row in d_assign_date_duty.loc[d_assign_date_duty['cnt'] > 0].iterrows():
        date = row['date']
        duty = row['duty']
        name_jpn = row['name_jpn']
        if duty == 'day':
            d_assign_date_print.loc[d_assign_date_print['date'] == date, 'am'] = name_jpn
            d_assign_date_print.loc[d_assign_date_print['date'] == date, 'pm'] = name_jpn
        else:
            d_assign_date_print.loc[d_assign_date_print['date'] == date, duty] = name_jpn
    for date in d_assign_date_print.loc[d_assign_date_print['em'] == True, 'date'].tolist():
        d_assign_date_print.loc[d_assign_date_print['date'] == date, 'night'] += '(救急)'
    d_assign_date_print = d_assign_date_print.loc[:,['title_date','am','pm','night','ocday','ocnight','ect']]
    d_assign_date_print.columns = ['日付', '午前日直', '午後日直', '当直', '日直OC', '当直OC', 'ECT']
    d_assign_date_print.to_csv(os.path.join(p_dst, 'assign_date.csv'), index = False)

    # Assignments with member as row
    d_assign_optimal = pd.DataFrame((d_availability == 2) & d_assign, columns = l_member, index = d_assign.index)                         
    d_assign_suboptimal = pd.DataFrame((d_availability == 1) & d_assign, columns = l_member, index = d_assign.index)
    #d_assign_error = pd.DataFrame((d_availability == 0) & d_assign, columns = l_member, index = d_assign.index)
    d_assign_member = pd.DataFrame({'id_member': l_member,
                                    'name_jpn': d_member.loc[d_member['id_member'].isin(l_member),'name_jpn'].tolist(),
                                    'duty_all': d_assign.apply(lambda col: col[col].index.to_list(), axis = 0),
                                    'duty_opt': d_assign_optimal.apply(lambda col: col[col].index.to_list(), axis = 0),
                                    'duty_sub': d_assign_suboptimal.apply(lambda col: col[col].index.to_list(), axis = 0),
                                    'cnt_all': d_assign.sum(axis = 0),
                                    'cnt_opt': d_assign_optimal.sum(axis = 0),
                                    'cnt_sub': d_assign_suboptimal.sum(axis = 0)},
                                    index = l_member)
    d_assign_member.to_csv(os.path.join(p_dst, 'assign_member.csv'), index = False)

    d_score_history.index = d_score_history['id_member']
    d_score_history = d_score_history.loc[d_assign_member['id_member'],['score_ampm','score_daynight','score_ampmdaynight','score_oc','score_ect']]
    d_score_sigma.columns = ['score_' + col for col in d_score_sigma.columns]
    d_score_current = d_score_sigma - d_score_history
    d_score_sigma.columns = ['sigma_' + col for col in d_score_sigma.columns]
    d_score = pd.concat([d_assign_member[['id_member', 'name_jpn']], d_score_current, d_score_sigma], axis = 1)
    d_score.to_csv(os.path.join(p_dst, 'score.csv'), index = False)

    return d_assign_date_duty, d_assign_date_print, d_assign_member, d_score


################################################################################
# Prepare calendar for google forms
################################################################################
def prep_forms(p_month, p_data, d_cal, dict_duty):
    #l_duty = ['am', 'pm', 'day', 'ocday', 'night', 'ocnight']
    dict_duty_jpn = {'am': '午前日直', 'pm': '午後日直', 'day': '日直', 'ocday': '日直OC', 'night': '当直', 'emnight': '救急当直', 'ocnight': '当直OC'}
    
    l_cal_duty = []
    for duty in dict_duty_jpn.keys():
        d_cal_duty = d_cal.loc[d_cal[duty] == True, ['date', 'title_date']].copy()
        d_cal_duty['duty'] = duty
        l_cal_duty.append(d_cal_duty)
    d_cal_duty = pd.concat(l_cal_duty, axis = 0)
    d_cal_duty['duty_sort'] = d_cal_duty['duty'].map(dict_duty)
    d_cal_duty = d_cal_duty.sort_values(by = ['date', 'duty_sort'])
    d_cal_duty.index = range(len(d_cal_duty))

    d_cal_duty['duty_jpn'] = d_cal_duty['duty'].map(dict_duty_jpn)
    d_cal_duty['title_dateduty'] = d_cal_duty['title_date'] + d_cal_duty['duty_jpn']

    d_cal_duty = d_cal_duty[['date','duty','title_dateduty']]

    # Dictionary of title and duty
    dict_title_duty = {'assoc': ['ocday', 'ocnight'],
                       'instr': ['am','pm','ocday','ocnight'],
                       'assist_leader': ['am','pm','day','night','emnight','ocday','ocnight'],
                       'assist_subleader': ['am','pm','day','night','emnight'],
                       'limtermclin': ['am','pm','day','night'],
                       'stud': ['day','night']}

    dict_l_form = {}
    for title in dict_title_duty.keys():
        l_duty_title = dict_title_duty[title]
        l_duty_title_ampm = [duty for duty in l_duty_title if duty in ['am','pm']]
        l_duty_title_daynight = [duty for duty in l_duty_title if duty not in ['am','pm']]
        if len(l_duty_title_ampm) > 0:
            col = title + '_ampm'
            dict_l_form[col] = d_cal_duty.loc[d_cal_duty['duty'].isin(l_duty_title_ampm), 'title_dateduty'].tolist()
        if len(l_duty_title_daynight) > 0:
            col = title + '_daynight'
            dict_l_form[col] = d_cal_duty.loc[d_cal_duty['duty'].isin(l_duty_title_daynight), 'title_dateduty'].tolist()
    d_form = pd.DataFrame(dict([(key, pd.Series(l_form)) for key, l_form in dict_l_form.items() ]))

    # Save data
    for p_save in [p_month, p_data]:
        d_cal_duty.to_csv(os.path.join(p_save, 'duty.csv'), index = False)
        d_form.to_csv(os.path.join(p_save, 'form.csv'), index = False)

    return d_cal_duty, d_form


################################################################################
# Prepare data of member availability
################################################################################
def prep_availability(p_month, p_data, f_availability, d_date_duty, d_cal, d_member):
    d_availability = pd.read_csv(os.path.join(p_month, 'src', f_availability))
    
    d_availability = pd.merge(d_member[['id_member', 'name_jpn']], d_availability, on='name_jpn')
    d_availability.set_index('id_member', inplace=True)
    d_availability.drop(['name_jpn'], axis = 1, inplace = True)
    d_availability = d_availability.T
    l_date_ect = d_cal.loc[d_cal['ect'] == True, 'date'].tolist()
    d_availability_ect = d_availability.loc[[str(date_ect) + '_am' for date_ect in l_date_ect], :]
    d_availability_ect.index = ([str(date_ect) + '_ect' for date_ect in l_date_ect])
    d_availability = pd.concat([d_availability, d_availability_ect], axis = 0)
    d_availability = d_availability.loc[d_date_duty['date_duty'],:]
    d_availability.to_csv(os.path.join(p_data, 'availability.csv'))
    l_member = d_availability.columns.to_list()
    
    return d_availability, l_member


################################################################################
# Prepare data of member specs and assignment limits
################################################################################
def prep_member(p_src, f_member, l_class_duty):
    l_col_member = ['id_member','name_jpn','name_jpn_full','email','title_jpn','designation_jpn','ect_asgn_jpn','name','title_short','designation', 'team', 'ect_leader', 'ect_subleader']

    d_src = pd.read_csv(os.path.join(p_src, f_member))
    l_col_member = [col for col in l_col_member if col in d_src.columns]
    d_member = d_src[l_col_member]
    d_lim = d_src[l_class_duty].copy()
    d_lim.index = d_member['id_member'].tolist()

    # Split assignment limit data into hard and soft
    d_lim_hard = pd.DataFrame([[[np.nan]*2]*d_lim.shape[1]]*d_lim.shape[0],
                              index = d_member['id_member'].tolist(), columns = d_lim.columns)
    d_lim_soft = pd.DataFrame([[[np.nan]*2]*d_lim.shape[1]]*d_lim.shape[0],
                              index = d_member['id_member'].tolist(), columns = d_lim.columns)
    for col in l_class_duty:
        d_lim[col] = d_lim[col].astype(str)
        for idx in d_member['id_member'].tolist():
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
    
    return d_member, d_lim_hard, d_lim_soft


################################################################################
# Prepare calendar of the month
################################################################################
def prep_calendar(p_root, p_month, p_data, l_class_duty, l_holiday, l_day_ect, l_date_ect_cancel, day_em, l_week_em,
                  year_plan, month_plan):
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
    d_cal.loc[d_cal['holiday'] == False, ['am', 'pm', 'night', 'ocnight']] = True
    d_cal.loc[d_cal['em'] == True, ['night', 'emnight','ocnight']] = [False, True, False]
    d_cal.loc[d_cal['holiday'] == True, ['day', 'night', 'ocday', 'ocnight']] = True
    d_cal.loc[(d_cal['wday'].isin(l_day_ect)) & (d_cal['holiday'] == False), 'ect'] = True
    d_cal.loc[d_cal['date'].isin(l_date_ect_cancel), 'ect'] = False

    d_cal['holiday_wday'] = ''
    d_cal.loc[(d_cal['holiday'] == True) & (d_cal['wday'].isin([0,1,2,3,4])), 'holiday_wday'] = '・祝'
    d_cal['title_date'] = [str(month_plan) + '/' + str(date) + '(' + wday_jpn + holiday_wday + ')' for [date, wday_jpn, holiday_wday] in zip(d_cal['date'], d_cal['wday_jpn'], d_cal['holiday_wday'])]
    d_cal = d_cal.drop('holiday_wday', axis = 1)

    # Prepare s_cnt_duty (necessary assignment counts of each duty)
    s_cnt_duty = d_cal[['am', 'pm', 'day', 'night', 'emnight', 'ocday', 'ocnight', 'ect']].sum(axis=0)

    # Prepare d_date_duty (specs and scores and classifications of each duty in each date)
    ld_date_duty = []
    for duty in ['am', 'pm', 'day', 'night', 'emnight', 'ocday', 'ocnight', 'ect']:
        d_date_duty_append = d_cal.loc[d_cal[duty] == True, ['date', 'holiday','em']]
        d_date_duty_append['duty'] = duty
        d_date_duty_append['date_duty'] = d_date_duty_append['date'].apply(lambda x: str(x) + '_' + duty)
        ld_date_duty.append(d_date_duty_append)
    d_date_duty = pd.concat(ld_date_duty, axis = 0)
    d_date_duty = d_date_duty[['date_duty','date','duty','holiday','em']]
    d_date_duty.index = range(len(d_date_duty))

    # Calculate scores
    d_score_duty = pd.read_csv(os.path.join(p_root, 'Dropbox/dutyshift/config/score_duty.csv'))
    d_score_duty.columns = [d_score_duty.columns.tolist()[0]] + ['score_' + col for col in d_score_duty.columns.tolist()[1:]]
    d_date_duty = pd.merge(d_date_duty, d_score_duty, on = 'duty', how = 'left')

    # Calculate class of duty
    d_date_duty, s_cnt_class_duty = date_duty2class(p_root, d_date_duty, l_class_duty)

    # Save data
    for p_save in [p_month, p_data]:
        d_cal.to_csv(os.path.join(p_save, 'calendar.csv'), index = False)
        d_date_duty.to_csv(os.path.join(p_save, 'date_duty.csv'), index = False)
        s_cnt_duty.to_csv(os.path.join(p_save, 'cnt_duty.csv'), index = False)
        s_cnt_class_duty.to_csv(os.path.join(p_save, 'cnt_class_duty.csv'), index = False)

    return d_cal, d_date_duty, s_cnt_duty, s_cnt_class_duty


################################################################################
# Split assignment limit data into hard and soft
################################################################################
def split_lim(d_lim, l_class_duty):
    # Split assignment limit data into hard and soft
    d_lim_hard = pd.DataFrame([[[np.nan]*2]*d_lim.shape[1]]*d_lim.shape[0],
                              index = d_lim.index, columns = d_lim.columns)
    d_lim_soft = pd.DataFrame([[[np.nan]*2]*d_lim.shape[1]]*d_lim.shape[0],
                              index = d_lim.index, columns = d_lim.columns)

    for col in l_class_duty:
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
def past_score(p_root, d_member, year_plan, month_plan):
    # Load Past assignments
    l_dir_pastdata = os.listdir(os.path.join(p_root, 'Dropbox/dutyshift'))
    l_dir_pastdata = [dir for dir in l_dir_pastdata if dir.startswith('20')]
    ld_assign_date_duty = []
    for dir in l_dir_pastdata:
        year_dir = int(dir[:4])
        month_dir = int(dir[4:6])
        if year_dir < year_plan or (year_dir == year_plan and month_dir < month_plan):
            d_assign_date_duty_append = pd.read_csv(os.path.join(p_root, 'Dropbox/dutyshift', dir, 'assign_date_duty.csv'))
            d_assign_date_duty_append['year'] = year_dir
            d_assign_date_duty_append['month'] = month_dir
            ld_assign_date_duty.append(d_assign_date_duty_append)
    d_assign_date_duty = pd.concat(ld_assign_date_duty)

    d_assign_date_duty = d_assign_date_duty[d_assign_date_duty['cnt'] == 1]

    # Calculate past scores
    d_score_duty = pd.read_csv(os.path.join(p_root, 'Dropbox/dutyshift/config/score_duty.csv'))
    l_type_score = [col for col in d_score_duty.columns if col != 'duty']
    d_assign_date_duty = pd.merge(d_assign_date_duty, d_score_duty, on = 'duty', how = 'left')

    d_score_past = d_member.copy()
    for id_member in d_score_past['id_member'].tolist():
        d_score_member = d_assign_date_duty.loc[d_assign_date_duty['id_member'] == id_member,
                                                l_type_score]
        s_score_member = d_score_member.sum(axis = 0)
        d_score_past.loc[d_score_past['id_member'] == id_member,
                    l_type_score] = s_score_member.tolist()

    d_score_past.index = d_score_past['id_member'].tolist()
    d_score_past = d_score_past[['id_member'] + l_type_score]

    return d_score_past


################################################################################
# Convert date_duty to class
################################################################################
def date_duty2class(p_root, d_date_duty, l_class_duty):
    # Load class data
    d_class_duty = pd.read_csv(os.path.join(p_root, 'Dropbox/dutyshift/config/class_duty.csv'))
    #l_class_duty = sorted(list(set(d_class_duty['class'].tolist())))
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

    s_cnt_class_duty = d_date_duty[['class_' + class_duty for class_duty in  l_class_duty]].sum(axis = 0)
    s_cnt_class_duty.index = [id[6:] for id in s_cnt_class_duty.index.tolist()]

    return d_date_duty, s_cnt_class_duty

