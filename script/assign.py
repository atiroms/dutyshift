
import numpy as np, pandas as pd
import os
from pulp import *
from ortoolpy import addbinvars
from script.helper import *

def optimize_count_and_assign(lp_root, year_plan, month_plan, year_start, month_start,
                              l_type_score, l_class_duty, dict_c_diff_score_current, dict_c_diff_score_total,
                              l_date_duty_skip_manual, dict_closeduty, ll_avoid_adjacent,
                              l_title_fulltime, l_date_duty_fulltime, type_limit,
                              c_assign_suboptimal, c_cnt_deviation, c_closeduty, dict_score_duty, dict_score_class):
    
    p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = 'asgn')

    ###############################################################################
    # Optimize exact assignment count
    ###############################################################################

    s_cnt_class_duty = pd.read_csv(os.path.join(p_month, 'cnt_class_duty.csv'), index_col=0).squeeze(1)

    # Prepare data of member specs and assignment limits
    d_member, d_score_past, d_lim_hard, d_lim_soft, d_grp_score \
        = prep_member2(p_root, p_month, p_data, l_class_duty, year_plan, month_plan, year_start, month_start, dict_score_duty)
    
    #print(d_score_past)

    # TODO: equilize 3 continous holidays assignment count
    #d_score_class = pd.read_csv(os.path.join(p_root, 'Dropbox/dutyshift/config/score_class.csv'))
    d_score_class = pd.DataFrame(dict_score_class)

    # Optimize assignment counts except OC
    print('Optimizing assignment count (non-OC)...')
    d_lim_exact_notoc, d_score_current_notoc, d_score_total_notoc,\
    d_sigma_diff_score_current_notoc, d_sigma_diff_score_total_notoc = \
        optimize_count(d_member, s_cnt_class_duty, d_lim_hard, d_score_past,
                       d_score_class, d_grp_score, dict_c_diff_score_current, dict_c_diff_score_total,
                       l_type_score = ['ampm', 'daynight', 'ampmdaynight', 'ect'],
                       l_class_duty = ['ampm', 'daynight_tot', 'night_em', 'ect'])

    # Optimize assignment counts of OC
    print('Optimizing assignment count (OC)...')
    ln_daynight = d_lim_exact_notoc['daynight_tot'].tolist()
    #l_designation = d_member.loc[d_member['id_member'].isin(l_member), 'designation'].tolist()
    l_designation = d_member['designation'].tolist()
    n_oc_required = int(sum([x * (y == False) for x, y in zip(ln_daynight, l_designation)]))
    s_cnt_class_duty['oc_tot'] = n_oc_required

    d_lim_exact_oc, d_score_current_oc, d_score_total_oc,\
    d_sigma_diff_score_current_oc, d_sigma_diff_score_total_oc = \
        optimize_count(d_member, s_cnt_class_duty, d_lim_hard, d_score_past,
                    d_score_class, d_grp_score, dict_c_diff_score_current, dict_c_diff_score_total,
                    l_type_score = ['oc'],
                    l_class_duty = ['oc_tot'])

    d_lim_exact = pd.concat([d_lim_exact_notoc, d_lim_exact_oc], axis = 1)
    for col in d_lim_hard.columns:
        if not col in d_lim_exact.columns:
            d_lim_exact[col] = [x[0] for x in d_lim_hard[col].tolist()]
    d_lim_exact = d_lim_exact[d_lim_hard.columns]

    d_score_current = pd.concat([d_score_current_notoc, d_score_current_oc], axis = 1)
    d_score_total = pd.concat([d_score_total_notoc, d_score_total_oc], axis = 1)

    # Save data
    for p_save in [p_month, p_data]:
        d_lim_exact.to_csv(os.path.join(p_save, 'lim_exact.csv'), index = True)
        d_score_current.to_csv(os.path.join(p_save, 'score_current_plan.csv'), index = True)
        d_score_total.to_csv(os.path.join(p_save, 'score_total_plan.csv'), index = True)


    ###############################################################################
    # Load and prepare data for duty assignment
    ###############################################################################
    # Prepare data of member availability
    d_date_duty = pd.read_csv(os.path.join(p_month, 'date_duty.csv'))
    d_cal = pd.read_csv(os.path.join(p_month, 'calendar.csv'))
    d_member = pd.read_csv(os.path.join(p_month, 'member.csv'), index_col = 0)
    d_lim_exact = pd.read_csv(os.path.join(p_month, 'lim_exact.csv'), index_col = 0)
    d_lim_hard = pd.read_csv(os.path.join(p_month, 'lim_hard.csv'), index_col = 0)
    d_assign_manual = pd.read_csv(os.path.join(p_month, 'assign_manual.csv'))
    d_availability, l_member, d_availability_ratio = prep_availability(p_month, p_data, d_date_duty, d_cal)
    d_assign_previous = prep_assign_previous(p_root, year_plan, month_plan)
    d_date_duty, d_availability, l_date_duty_unavailable, l_date_duty_manual_assign, l_date_duty_skip =\
        skip_date_duty(d_date_duty, d_availability, d_availability_ratio, d_assign_manual, l_date_duty_skip_manual)


    ###############################################################################
    # Initialize assignment problem and model
    ###############################################################################
    print('Optimizing assignment...')
    # Initialize model to be optimized
    prob_assign = LpProblem()

    # Binary assignment variables to be optimized
    dv_assign = pd.DataFrame(np.array(addbinvars(len(d_date_duty), len(l_member))),
                            index = d_date_duty['date_duty'].to_list(), columns = l_member)


    ###############################################################################
    # Manual assignment
    ###############################################################################
    for i_date_duty in d_assign_manual.loc[~d_assign_manual['id_member'].isna(), :].index.to_list():
        date_duty = d_assign_manual.loc[i_date_duty, 'date_duty']
        id_member = d_assign_manual.loc[i_date_duty, 'id_member']
        if date_duty in d_date_duty['date_duty'].tolist():
            prob_assign += (dv_assign.loc[date_duty, id_member] == 1)


    ###############################################################################
    # Availability per member per date_duty
    ###############################################################################
    # Do not assign to a date if not available
    prob_assign += (lpDot((d_availability == 0).to_numpy(), dv_assign.to_numpy()) <= 0)

    # Penalize suboptimal assignment
    v_assign_suboptimal = lpDot((d_availability == 1).to_numpy(), dv_assign.to_numpy())


    ###############################################################################
    # Assignment per date_duty
    ###############################################################################
    # Assign one member per date_duty for ['am', 'pm', 'day', 'night', 'emnight', 'ect']
    for duty in ['am', 'pm', 'day', 'night', 'emnight', 'ect']:
        for date_duty in d_date_duty[d_date_duty['duty'] == duty]['date_duty'].to_list():
            prob_assign += (lpSum(dv_assign.loc[date_duty]) == 1)

    # If non-designated member is assigned to ['day', 'night'] for the same date/time,
    # assign one member per date_duty for ['oc_day', 'oc_night']

    l_designation = []

    for member in l_member:
        l_designation.append(d_member.loc[d_member['id_member'] == member, 'designation'].tolist()[0])
    for duty in ['day', 'night']:
        for date in d_date_duty[d_date_duty['duty'] == duty]['date'].to_list():
            date_duty = str(date) + '_' + duty
            date_duty_oc = str(date) + '_oc' + duty
            if date_duty_oc in d_date_duty['date_duty'].to_list():
                # Sum of dot product of (normal and oc assignments) and (designation)
                # Returns number of 'designated' member assigned in the same date/time, which should be 1
                prob_assign += (lpSum(lpDot(dv_assign.loc[[date_duty, date_duty_oc]].to_numpy(),
                                            np.array([l_designation] * 2))) == 1)


    ###############################################################################
    # Force full-time doctor assignment
    ###############################################################################
    d_fulltime = pd.DataFrame({'id_member': l_member, 'fulltime': False})
    d_fulltime = pd.merge(d_fulltime, d_member[['id_member', 'title_short']], on = 'id_member', how = 'left')
    d_fulltime['fulltime'] = d_fulltime['title_short'].isin(l_title_fulltime)
    l_fulltime = d_fulltime['fulltime'].tolist()
    #l_fulltime = [(title in ['limterm_instr', 'assist']) for title in l_fulltime]
    for date_duty_fulltime in l_date_duty_fulltime:
        prob_assign += (lpSum(lpDot(dv_assign.loc[date_duty_fulltime].to_numpy(),
                                    np.array(l_fulltime))) == 1)


    ###############################################################################
    # Penalize limit outliers per member per class_duty
    ###############################################################################
    # Variable dataframe of deviation from target
    dv_deviation_target = pd.DataFrame(np.array(addvars(len(l_member), len(l_class_duty))),
                                    index = l_member, columns = l_class_duty)
    # Variable dataframe of deviation from limit
    dv_deviation_limit = pd.DataFrame(np.array(addvars(len(l_member), len(l_class_duty))),
                                    index = l_member, columns = l_class_duty)

    for member in l_member:
        for class_duty in l_class_duty:
            lim_hard = d_lim_hard.loc[member, class_duty]
            cnt_min = float(lim_hard[1:-1].split(', ')[0])
            cnt_max = float(lim_hard[1:-1].split(', ')[1])
            cnt_target = d_lim_exact.loc[member, class_duty]
            if type_limit == 'ignore':
                if ~np.isnan(cnt_min): # If limit is specified
                    prob_assign += (dv_deviation_limit.loc[member, class_duty] == 0)
                    # Penalize deviation from target
                    prob_assign += (dv_deviation_target.loc[member, class_duty] >= (lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty]) - cnt_target))
                    prob_assign += (dv_deviation_target.loc[member, class_duty] >= (cnt_target - lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty])))
            elif type_limit == 'hard':
                if ~np.isnan(cnt_min):
                    prob_assign += (dv_deviation_limit.loc[member, class_duty] == 0)
                    if cnt_min == cnt_max:
                        # Exact count
                        prob_assign += (lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty]) == cnt_min)
                        prob_assign += (dv_deviation_target.loc[member, class_duty] == 0)
                    else:
                        # Prohibit outlier from limit
                        prob_assign += (lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty]) >= cnt_min)
                        prob_assign += (lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty]) <= cnt_max)
                        # Penalize deviation from target
                        prob_assign += (dv_deviation_target.loc[member, class_duty] >= (lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty]) - cnt_target))
                        prob_assign += (dv_deviation_target.loc[member, class_duty] >= (cnt_target - lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty])))
            elif type_limit == 'soft':
                if ~np.isnan(cnt_min):
                    # Penalize outlier from limit
                    prob_assign += (dv_deviation_limit.loc[member, class_duty] >= (lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty]) - cnt_max))
                    prob_assign += (dv_deviation_limit.loc[member, class_duty] >= (cnt_min - lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty])))
                    prob_assign += (dv_deviation_limit.loc[member, class_duty] >= 0)
                    # Penalize deviation from target
                    prob_assign += (dv_deviation_target.loc[member, class_duty] >= (lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty]) - cnt_target))
                    prob_assign += (dv_deviation_target.loc[member, class_duty] >= (cnt_target - lpDot(dv_assign.loc[:, member], d_date_duty.loc[:, 'class_' + class_duty])))

    v_cnt_deviation = lpSum([lpSum(dv_deviation_target.to_numpy()), lpSum(dv_deviation_limit.to_numpy())])


    ###############################################################################
    # Avoid overlapping / adjacent / close assignments
    ###############################################################################
    # Avoid ['day', 'ocday', 'night', 'emnight', 'ocnight'] in N(thr_interval_daynight) continuous days
    # Avoid 'ect' in N(thr_interval_ect) continuous days
    # Avoid ['am','pm'] in N(thr_interval_ampm) continuous days

    l_member_missing = [m for m in l_member if m not in d_assign_previous.columns]
    d_assign_previous[l_member_missing] = 0

    # Hard limit of closeness (avoid violence)
    for closeduty in dict_closeduty.keys():
        thr_interval_hard = dict_closeduty[closeduty]['thr_hard'] # 1: avoid within same day, 2: avoid within 2 continuous days
        l_duty = dict_closeduty[closeduty]['l_duty']
        if thr_interval_hard > 0:
            for date_start in [d for d in range(-thr_interval_hard + 2, 1)] + d_cal['date'].tolist():
                # Create list of continuous date_duty's
                l_date_duty_cont = []
                l_date_duty_cont_previous = []
                for date in range(date_start, date_start + thr_interval_hard):
                    for duty in l_duty:
                        date_duty = str(date) + '_' + duty
                        if date_duty in dv_assign.index:
                            l_date_duty_cont.append(date_duty)
                        if date_duty in d_assign_previous.index:
                            l_date_duty_cont_previous.append(date_duty)
                # If the list of continuous date_duty's has more than one item
                if (len(l_date_duty_cont) + len(l_date_duty_cont_previous)) >= 2:
                    for member in l_member:
                        # Assignments within continuous date_duty's should not exceeed 1
                        prob_assign += (lpSum(dv_assign.loc[l_date_duty_cont, member]) +\
                                        sum(d_assign_previous.loc[l_date_duty_cont_previous, member]) <= 1)

    # Soft limit of closeness (penalize violence)
    dict_dv_closeduty = {}
    for closeduty in dict_closeduty.keys():
        thr_interval_soft = dict_closeduty[closeduty]['thr_soft']
        l_duty = dict_closeduty[closeduty]['l_duty']
        l_date_start = [d for d in range(-thr_interval_soft + 2, 1)] + d_cal['date'].tolist()
        # Variable dataframe of count of assignments within continuous date_duty's staring from date_start, per member, per closeduty
        dict_dv_closeduty[closeduty] = pd.DataFrame(np.array(addvars(len(l_date_start),len(l_member))), index = l_date_start, columns = l_member)                        
        for date_start in l_date_start:
            # Create list of continuous date_duty's
            l_date_duty_cont = []
            l_date_duty_cont_previous = []
            for date in range(date_start, date_start + thr_interval_soft):
                for duty in l_duty:
                    date_duty = str(date) + '_' + duty
                    if date_duty in dv_assign.index:
                        l_date_duty_cont.append(date_duty)
                    if date_duty in d_assign_previous.index:
                        l_date_duty_cont_previous.append(date_duty)
            # Check if count of assignment per member per continuous date_duty's > 1 (penalize if so)
            for member in l_member:
                # For each variable in dict_dv_closeduty[closeduty], var >= (count - 1), and var >= 0, and var is minimized
                # resulting in: var = 0 if count = 0, 1 (no penalty); var = count - 1 if count > 1 (penalty)
                prob_assign += (dict_dv_closeduty[closeduty].loc[date_start, member] >=\
                                (lpSum(dv_assign.loc[l_date_duty_cont, member]) + sum(d_assign_previous.loc[l_date_duty_cont_previous, member]) - 1))
                prob_assign += (dict_dv_closeduty[closeduty].loc[date_start, member] >= 0)
    v_closeduty = lpSum([lpSum(dv_closeduty.to_numpy()) for dv_closeduty in dict_dv_closeduty.values()])

    # Avoid overlapping duties:
    #       [same-date 'pm', 'night', 'emnight' and 'ocnight'],
    #   and ['night', 'emnight', 'ocnight' and following-date 'ect','am']
    for date in [0] + d_cal['date'].tolist():
        for l_avoid_adjacent in ll_avoid_adjacent:
            l_avoid = [str(date + avoid[1]) + '_' + avoid[0] for avoid in l_avoid_adjacent]
            # Check if date_duty exists
            l_date_duty_cont = []
            l_date_duty_cont_previous = []
            for date_duty in l_avoid:
                if date_duty in dv_assign.index:
                    l_date_duty_cont.append(date_duty)
                if date_duty in d_assign_previous.index:
                    l_date_duty_cont_previous.append(date_duty)

            if (len(l_date_duty_cont) + len(l_date_duty_cont_previous)) >= 2:
                for member in l_member:
                    prob_assign += (lpSum(dv_assign.loc[l_date_duty_cont, member]) +\
                                    sum(d_assign_previous.loc[l_date_duty_cont_previous, member]) <= 1)

    ###############################################################################
    # Avoid ECT from the leader's team
    ###############################################################################
    l_date_ect = d_date_duty.loc[d_date_duty['duty'] == 'ect', 'date'].tolist()
    #l_date_ect = d_cal.loc[d_cal['ect'] == True, 'date'].to_list()
    #l_date_ect = [date for date in l_date_ect if not date in l_date_skip]
    l_team = sorted(list(set(d_member['team'].to_list())))
    for date in l_date_ect:
        wday = d_cal.loc[d_cal['date'] == date, 'wday'].to_list()[0]
        team_leader = d_member.loc[d_member['ect_leader'] == str(wday), 'team'].to_list()[0]
        if team_leader != '-':
            l_id_member_team = d_member.loc[d_member['team'] == team_leader, 'id_member'].to_list()
            for id_member in l_id_member_team:
                prob_assign += (dv_assign.loc[str(date) + '_ect', id_member] == 0)


    ###############################################################################
    # Define objective function to be minimized
    ###############################################################################
    prob_assign += (c_assign_suboptimal * v_assign_suboptimal
                    + c_cnt_deviation * v_cnt_deviation
                    + c_closeduty * v_closeduty)

            
    ###############################################################################
    # Solve problem
    ###############################################################################
    # Print problem
    #print('Problem: ', problem)

    # Solve problem
    prob_assign.solve()
    v_objective = value(prob_assign.objective)
    print('Solved: ' + str(LpStatus[prob_assign.status]) + ', ' + str(round(v_objective, 2)))


    ###############################################################################
    # Extract data
    ###############################################################################
    d_assign, d_assign_date_duty =\
        extract_assignment(p_month, p_data, year_plan, month_plan, dv_assign, d_member, d_date_duty, dict_score_duty)

    d_closeduty = extract_closeduty(p_month, p_data, dict_dv_closeduty, d_member, dict_closeduty)

    d_assign, d_assign_date_print, d_assign_member, d_deviation, d_deviation_summary, d_score_current, d_score_total, d_score_print =\
        convert_result(p_month, p_data, d_assign_date_duty, d_availability, 
                    d_member, d_date_duty, d_cal, l_class_duty, l_type_score, d_lim_exact)

    #print(d_assign_date_print)
    print('Deviation from target:')
    print(d_deviation_summary)

    return d_assign, d_assign_date_print, d_assign_member, d_deviation, d_score_print, d_closeduty