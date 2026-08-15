
import numpy as np, pandas as pd
import random
from pulp import LpProblem, LpStatus, lpSum, lpDot, value
from ortoolpy import addvars, addbinvars
from script.helper import (
    prep_member2, optimize_count, prep_assign_previous, skip_date_duty, extract_assignment,
    convert_assignment, extract_closeduty, print_candidate_replacement,
)
from script.drive_io import get_services, prep_drive_paths, read_csv, write_csv, SCOPE_DRIVE_FORMS

def optimize_assign(d_date_duty, l_member, d_assign_manual, d_availability, d_member,
                    l_title_fulltime, l_date_duty_fulltime, l_class_duty,
                    d_lim_hard, d_lim_exact, type_limit, d_info, d_assign_previous,
                    dict_closeduty, d_cal, ll_avoid_adjacent,
                    c_assign_suboptimal, c_cnt_deviation, c_closeduty
                    ):
    ###############################################################################
    # Initialize assignment problem and model
    ###############################################################################
    # Initialize model to be optimized
    prob_assign = LpProblem()

    # Binary assignment variables to be optimized
    dv_assign = pd.DataFrame(np.array(addbinvars(len(d_date_duty), len(l_member))),
                            index=d_date_duty['date_duty'].to_list(), columns=l_member)


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
    d_fulltime = pd.merge(d_fulltime, d_member[['id_member', 'title_short']], on='id_member', how='left')
    d_fulltime['fulltime'] = d_fulltime['title_short'].isin(l_title_fulltime)
    l_fulltime = d_fulltime['fulltime'].tolist()
    #l_fulltime = [(title in ['limterm_instr', 'assist']) for title in l_fulltime]
    for date_duty_fulltime in l_date_duty_fulltime:
        if date_duty_fulltime in dv_assign.index:
            prob_assign += (lpSum(lpDot(dv_assign.loc[date_duty_fulltime].to_numpy(), np.array(l_fulltime))) == 1)


    ###############################################################################
    # Penalize limit outliers per member per class_duty
    ###############################################################################
    # Variable dataframe of deviation from target
    dv_deviation_target = pd.DataFrame(np.array(addvars(len(l_member), len(l_class_duty))),
                                    index=l_member, columns=l_class_duty)
    # Variable dataframe of deviation from limit
    dv_deviation_limit = pd.DataFrame(np.array(addvars(len(l_member), len(l_class_duty))),
                                    index=l_member, columns=l_class_duty)

    for member in l_member:
        for class_duty in l_class_duty:
            lim_hard = d_lim_hard.loc[member, class_duty]
            #cnt_min = float(lim_hard[1:-1].split(', ')[0])
            #cnt_max = float(lim_hard[1:-1].split(', ')[1])
            [cnt_min, cnt_max] = lim_hard
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
    # Student twice-assignation availability applied
    ###############################################################################
    for member in l_member:
        assign_twice = d_info.loc[d_info['id_member'] == member, 'assign_twice'].tolist()[0]
        if assign_twice == False:
            prob_assign += (lpSum(dv_assign.loc[:, member]) <= 1)
        elif assign_twice == True:
            prob_assign += (lpSum(dv_assign.loc[:, member]) <= 2)


    ###############################################################################
    # ECT subleader applicability
    ###############################################################################
    l_date_duty_ect = [date_duty for date_duty in d_date_duty['date_duty'].to_list() if date_duty.endswith('_ect')]
    for member in l_member:
        ect_subleader = d_member.loc[d_member['id_member'] == member, 'ect_subleader'].tolist()[0]
        if ect_subleader == False:
            for date_duty in l_date_duty_ect:
                prob_assign += (dv_assign.loc[date_duty, member] == 0)


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
        dict_dv_closeduty[closeduty] = pd.DataFrame(np.array(addvars(len(l_date_start),len(l_member))), index=l_date_start, columns=l_member)
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
        team_leader = d_member.loc[d_member['ect_leader'] == int(wday), 'team'].to_list()[0]
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

    return  prob_assign, dv_assign, v_assign_suboptimal, v_cnt_deviation, v_closeduty, dict_dv_closeduty


def optimize_count_and_assign(config, year_plan, month_plan, year_start, month_start,
                              l_class_duty, dict_c_diff_score_current, dict_c_diff_score_total,
                              l_date_duty_skip_manual, dict_closeduty, ll_avoid_adjacent,
                              l_title_fulltime, l_date_duty_fulltime, type_limit,
                              c_assign_suboptimal, c_cnt_deviation, c_closeduty,
                              dict_score_duty, dict_score_class, dict_class_duty,
                              n_troubleshoot_infeasible_max=10):

    services = get_services(config, SCOPE_DRIVE_FORMS)
    dp = prep_drive_paths(config, services.drive, year_plan, month_plan, prefix_dir='asgn')

    ###############################################################################
    # Optimize exact assignment count
    ###############################################################################
    print('=' * 60 + '\nAssignment count optimization\n' + '-' * 60)

    s_cnt_class_duty = read_csv(services.drive, dp.id_month, 'cnt_class_duty.csv', index_col=0).squeeze(1)

    # Prepare data of member specs and assignment limits
    d_member, d_score_past, d_lim_hard, d_lim_soft, d_grp_score \
        = prep_member2(dp, l_class_duty, year_plan, month_plan, year_start, month_start, dict_score_duty)
    l_member = d_member.index.tolist()

    # TODO: equilize 3 continous holidays assignment count
    d_score_class = pd.DataFrame(dict_score_class)

    # Optimize assignment counts except OC
    status_opt_notoc, loss_opt_notoc,\
    d_lim_exact_notoc, d_score_current_notoc, d_score_total_notoc,\
    d_sigma_diff_score_current_notoc, d_sigma_diff_score_total_notoc = \
        optimize_count(d_member, s_cnt_class_duty, d_lim_hard, d_score_past,
                       d_score_class, d_grp_score, dict_c_diff_score_current, dict_c_diff_score_total,
                       l_type_score=['ampm', 'daynight', 'ampmdaynight', 'ect'],
                       l_class_duty=['ampm', 'daynight_tot', 'night_em', 'ect'])

    # Optimize assignment counts of OC
    ln_daynight = d_lim_exact_notoc['daynight_tot'].tolist()
    #l_designation = d_member.loc[d_member['id_member'].isin(l_member), 'designation'].tolist()
    l_designation = d_member['designation'].tolist()
    n_oc_required = int(sum([x * (y == False) for x, y in zip(ln_daynight, l_designation)]))
    s_cnt_class_duty['oc_tot'] = n_oc_required

    status_opt_oc, loss_opt_oc,\
    d_lim_exact_oc, d_score_current_oc, d_score_total_oc,\
    d_sigma_diff_score_current_oc, d_sigma_diff_score_total_oc = \
        optimize_count(d_member, s_cnt_class_duty, d_lim_hard, d_score_past,
                    d_score_class, d_grp_score, dict_c_diff_score_current, dict_c_diff_score_total,
                    l_type_score=['oc'],
                    l_class_duty=['oc_tot'])

    d_lim_exact = pd.concat([d_lim_exact_notoc, d_lim_exact_oc], axis=1)
    for col in d_lim_hard.columns:
        if not col in d_lim_exact.columns:
            d_lim_exact[col] = [x[0] for x in d_lim_hard[col].tolist()]
    d_lim_exact = d_lim_exact[d_lim_hard.columns]

    d_score_current = pd.concat([d_score_current_notoc, d_score_current_oc], axis=1)
    d_score_total = pd.concat([d_score_total_notoc, d_score_total_oc], axis=1)

    if status_opt_notoc & status_opt_oc:
        print('Done, losses: ' + str(round(loss_opt_notoc, 2)) + '(non-OC), ' + str(round(loss_opt_oc, 2)) + '(OC)')
    else:
        print('Failed assignment count optimization')

    # Save data
    for id_folder in [id for id in [dp.id_month, dp.id_data] if id is not None]:
        write_csv(services.drive, id_folder, 'lim_exact.csv', d_lim_exact, index=True)
        write_csv(services.drive, id_folder, 'score_current_plan.csv', d_score_current, index=True)
        write_csv(services.drive, id_folder, 'score_total_plan.csv', d_score_total, index=True)


    ###############################################################################
    # Load and prepare data for duty assignment
    ###############################################################################
    print('=' * 60 + '\nMember assignment optimization\n' + '-' * 60)
    # Prepare data of member availability
    d_date_duty_noskip = read_csv(services.drive, dp.id_month, 'date_duty.csv')
    d_cal = read_csv(services.drive, dp.id_month, 'calendar.csv')
    d_assign_manual = read_csv(services.drive, dp.id_month, 'assign_manual.csv')
    d_info = read_csv(services.drive, dp.id_month, 'info.csv')
    d_availability_noskip = read_csv(services.drive, dp.id_month, 'availability.csv', index_col=0)
    #l_member = [int(member) for member in d_availability_noskip.columns]
    #d_availability_noskip.columns = l_member
    #print([int(member) for member in d_availability_noskip.columns])
    d_availability_noskip.columns = [int(member) for member in d_availability_noskip.columns]
    d_availability_noskip = d_availability_noskip[l_member]
    d_availability_ratio = read_csv(services.drive, dp.id_month, 'availability_ratio.csv', index_col=0)
    d_assign_previous = prep_assign_previous(dp, year_plan, month_plan)
    d_date_duty, d_availability, l_date_duty_unavailable, l_date_duty_unavailable_notoc, l_date_duty_manual_assign, l_date_duty_skip =\
        skip_date_duty(d_date_duty_noskip, d_availability_noskip, d_availability_ratio, d_assign_manual, l_date_duty_skip_manual, True)
    print('-' * 60)

    ###############################################################################
    # Optimize assignment
    ###############################################################################

    prob_assign, dv_assign, v_assign_suboptimal, v_cnt_deviation, v_closeduty, dict_dv_closeduty =\
        optimize_assign(d_date_duty, l_member, d_assign_manual, d_availability, d_member,
                    l_title_fulltime, l_date_duty_fulltime, l_class_duty,
                    d_lim_hard, d_lim_exact, type_limit, d_info, d_assign_previous,
                    dict_closeduty, d_cal, ll_avoid_adjacent,
                    c_assign_suboptimal, c_cnt_deviation, c_closeduty)

    # When the problem could not be solved, enter troubleshooting mode
    if str(LpStatus[prob_assign.status]) == 'Infeasible':
        if type_limit == 'hard':
            print('[ERROR] Failed to solve. Changing type_limit from "hard" to "soft"')
            type_limit = 'soft'
        else:
            print('[ERROR] Failed to solve.')
        print('[TROUBLESHOOTING] Entering troubleshooting mode to determine which duty caused the failure.')
        l_date_duty_noskip = d_date_duty['date_duty'].tolist()
        #print(l_date_duty_noskip)
        l_date_duty_suspected = l_date_duty_noskip # This includes all culprit

        # Randomly sample a subset of the current suspects to skip and re-solve. A successful
        # (Optimal) solve narrows the suspect set to the tested/skipped subset. An infeasible
        # solve leaves the suspect set -- and so the sample size -- unchanged, so the next
        # iteration tries a differently-sampled subset of the same size. Once
        # n_troubleshoot_infeasible_max differently-sampled subsets of the same size have all
        # come back infeasible in a row (no progress narrowing the suspect set), stop reducing
        # and move on to testing the remaining suspects one by one.
        cnt_iteration = 0
        cnt_infeasible_streak = 0
        while True:
            len_test = int(len(l_date_duty_suspected) * 0.8)
            if len_test == 0:
                # Nothing meaningful left to sample-test -- hand the remaining suspects
                # straight to one-by-one testing.
                break
            cnt_iteration += 1
            l_date_duty_testing = random.sample(l_date_duty_suspected, len_test)
            print('[TROUBLESHOOTING] iteration', cnt_iteration, 'test randomly skipping', len_test, 'duties.')
            l_date_duty_skip_manual_and_test = list(set(l_date_duty_skip_manual) | set(l_date_duty_testing))
            d_date_duty, d_availability, l_date_duty_unavailable, l_date_duty_unavailable_notoc, l_date_duty_manual_assign, l_date_duty_skip =\
                skip_date_duty(d_date_duty_noskip, d_availability_noskip, d_availability_ratio, d_assign_manual, l_date_duty_skip_manual_and_test, False)
            prob_assign, dv_assign, v_assign_suboptimal, v_cnt_deviation, v_closeduty, dict_dv_closeduty =\
                optimize_assign(d_date_duty, l_member, d_assign_manual, d_availability, d_member,l_title_fulltime, l_date_duty_fulltime, l_class_duty,d_lim_hard, d_lim_exact, type_limit, d_info, d_assign_previous, dict_closeduty, d_cal, ll_avoid_adjacent, c_assign_suboptimal, c_cnt_deviation, c_closeduty)
            if str(LpStatus[prob_assign.status]) == 'Optimal':
                # meaning that l_date_duty_testing includes all culprit
                l_date_duty_suspected = l_date_duty_testing
                cnt_infeasible_streak = 0
            else:
                cnt_infeasible_streak += 1
                print('[TROUBLESHOOTING] still infeasible (' + str(cnt_infeasible_streak) + '/' +
                      str(n_troubleshoot_infeasible_max) + ' consecutive infeasible samples of size ' + str(len_test) + ').')
                if cnt_infeasible_streak >= n_troubleshoot_infeasible_max:
                    print('[TROUBLESHOOTING]', n_troubleshoot_infeasible_max, 'differently-sampled subsets of size', len_test,
                          'all infeasible; proceeding to test the', len(l_date_duty_suspected), 'remaining suspected duties one by one.')
                    break

        l_date_duty_reduced = l_date_duty_suspected
        l_date_duty_unassignable = []
        for idx_testing in range(len(l_date_duty_reduced)):
            # Test if l_date_duty_reduced[idx_testing] should be skipped
            cnt_iteration += 1
            l_date_duty_testing = l_date_duty_unassignable
            if idx_testing < len(l_date_duty_reduced) - 1:
                l_date_duty_testing = l_date_duty_testing + l_date_duty_reduced[(idx_testing + 1):]
            l_date_duty_skip_manual_and_test = list(set(l_date_duty_skip_manual) | set(l_date_duty_testing))
            d_date_duty, d_availability, l_date_duty_unavailable, l_date_duty_unavailable_notoc, l_date_duty_manual_assign, l_date_duty_skip =\
                skip_date_duty(d_date_duty_noskip, d_availability_noskip, d_availability_ratio, d_assign_manual, l_date_duty_skip_manual_and_test, False)
            prob_assign, dv_assign, v_assign_suboptimal, v_cnt_deviation, v_closeduty, dict_dv_closeduty =\
                optimize_assign(d_date_duty, l_member, d_assign_manual, d_availability, d_member,l_title_fulltime, l_date_duty_fulltime, l_class_duty,d_lim_hard, d_lim_exact, type_limit, d_info, d_assign_previous, dict_closeduty, d_cal, ll_avoid_adjacent, c_assign_suboptimal, c_cnt_deviation, c_closeduty)
            if str(LpStatus[prob_assign.status]) == 'Optimal':
                # meaning that l_date_duty_testing includes all culprit
                print('[TROUBLESHOOTING] iteration', cnt_iteration, 'solvable,', l_date_duty_reduced[idx_testing], 'can be included.')
                l_date_duty_suspected = l_date_duty_testing
                prob_assign_last_optimal, dv_assign_last_optimal, v_assign_suboptimal_last_optimal, v_cnt_deviation_last_optimal, v_closeduty_last_optimal, dict_dv_closeduty_last_optimal = prob_assign, dv_assign, v_assign_suboptimal, v_cnt_deviation, v_closeduty, dict_dv_closeduty
            else:
                print('[TROUBLESHOOTING] iteration', cnt_iteration, 'unsolvable,', l_date_duty_reduced[idx_testing], 'needs to be skipped.')
                l_date_duty_unassignable.append(l_date_duty_reduced[idx_testing])

        prob_assign, dv_assign, v_assign_suboptimal, v_cnt_deviation, v_closeduty, dict_dv_closeduty = prob_assign_last_optimal, dv_assign_last_optimal, v_assign_suboptimal_last_optimal, v_cnt_deviation_last_optimal, v_closeduty_last_optimal, dict_dv_closeduty_last_optimal
        print('[DONE TROUBLESHOOTING] unassignable duty[ies]:', l_date_duty_unassignable)


    ###############################################################################
    # Result output
    ###############################################################################
    print('=' * 60 + '\nResult\n' + '-' * 60)

    if str(LpStatus[prob_assign.status]) == 'Optimal':
        print('Done, losses: ' + str(round(value(prob_assign.objective), 2)) + ' = ' + str(round(c_assign_suboptimal * value(v_assign_suboptimal), 2)) + ' + '
              + str(round(c_cnt_deviation * value(v_cnt_deviation), 2)) + ' + ' + str(round(c_closeduty * value(v_closeduty), 2)))
        print('(Total = Suboptimality + Count Deviation + Close duty)')
        # Extract data
        #d_assign, d_assign_date_duty =\
        d_assign_date_duty =\
            extract_assignment(dp, year_plan, month_plan, dv_assign, d_date_duty_noskip, l_date_duty_skip)

        d_assign, d_assign_date_print, d_assign_member, d_deviation, d_deviation_summary, d_score_current, d_score_total, d_score_print =\
            convert_assignment(dp, d_assign_date_duty, d_availability_noskip,
                           d_member, d_date_duty, d_cal, l_class_duty, dict_score_duty, d_lim_exact, d_lim_hard)

        d_closeduty = extract_closeduty(dp, dict_dv_closeduty, d_assign_date_duty, d_member, dict_closeduty)

        print('-' * 60 + '\nDeviation from target:\n' + '-' * 60)
        print(d_deviation_summary)
        print('-' * 60 + '\nClose duties:\n' + '-' * 60)
        print(d_closeduty)
        print('-' * 60 + '\nCandidate replacement:\n' + '-' * 60)
        print_candidate_replacement(services.drive, dp.id_month, dict_class_duty, d_deviation_summary, d_assign_date_duty, d_assign_member, d_closeduty)
        print('-' * 60)

        return d_assign, d_assign_date_print, d_assign_member, d_deviation, d_score_print, d_closeduty, d_deviation_summary, d_assign_date_duty
    else:
        print('Failed to solve')

        return [None] * 6
