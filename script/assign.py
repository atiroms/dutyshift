
import numpy as np, pandas as pd
from collections import namedtuple
from pulp import LpProblem, LpVariable, LpStatus, lpSum, lpDot, value
from ortoolpy import addvars, addbinvars
from script.helper import (
    prep_member2, optimize_count, prep_assign_previous, skip_date_duty, extract_assignment,
    convert_assignment, extract_closeduty, print_candidate_replacement,
    class_duty_names, score_class_table, make_solver, warn_if_not_proven_optimal,
)
from script.drive_io import get_services, prep_drive_paths, read_csv, write_csv, read_member_matrix_csv, SCOPE_DRIVE_FORMS
from script.parameter import dict_score_classes


# What build_assign_model returns. `objective` is the real (fairness) objective expression, held
# separately from whatever objective is currently set on `prob`, so the elastic recovery path in
# optimize_count_and_assign can swap objectives on an already-built model instead of paying to
# rebuild it. `dv_unassigned` is empty ({}) unless the model was built with elastic=True.
AssignModel = namedtuple('AssignModel',
                         ['prob', 'dv_assign', 'v_assign_suboptimal', 'v_cnt_deviation',
                          'v_cnt_limit', 'v_closeduty', 'dict_dv_closeduty', 'dv_unassigned',
                          'objective'])


def _forbid_assignment(prob, var):
    """Fix an assignment variable to 0 through its upper bound rather than with an `== 0`
    constraint: a bound costs no constraint row at all and lets CBC's presolve drop the variable
    outright, where thousands of `== 0` rows (one per unavailable member/slot pair) have to be
    built in Python, written to the LP file, and read back by the solver first.

    The one case that cannot be a bound is a variable a manual assignment has already pinned to
    1 -- lowBound=1 with upBound=0 would emit a malformed bound pair -- so that contradiction is
    stated as a real constraint instead, which CBC reports cleanly as Infeasible (which is what
    the old `== 0` formulation did for this case too)."""
    if var.lowBound == 1:
        prob += (var == 0)
    else:
        var.upBound = 0


def build_assign_model(d_date_duty, l_member, d_assign_manual, d_availability, d_member,
                       l_title_fulltime, l_date_duty_fulltime, dict_class_duty,
                       d_lim_hard, d_lim_exact, type_limit, d_info, d_assign_previous,
                       dict_closeduty, d_cal, ll_avoid_adjacent,
                       c_assign_suboptimal, c_cnt_deviation, c_cnt_limit, c_closeduty,
                       elastic=False):
    """Build (but do not solve) the Stage-2 assignment MILP.

    elastic=True additionally gives every must-fill duty slot an "unassigned" binary, letting the
    model express "this slot cannot be filled by anyone" instead of simply being infeasible. Used
    only by optimize_count_and_assign's recovery path -- see the comment there."""
    l_class_duty = class_duty_names(dict_class_duty)
    l_date_duty = d_date_duty['date_duty'].tolist()
    set_date_duty = set(l_date_duty)

    # Row/column order of d_availability is relied on positionally below (and by lpDot, which
    # zips values). Align it to the decision-variable frame explicitly rather than trusting the
    # caller to have built both in the same order. A slot/member pair with no availability
    # recorded at all is treated as unavailable, the safe direction.
    d_availability = d_availability.reindex(index=l_date_duty, columns=l_member).fillna(0)

    ###############################################################################
    # Initialize assignment problem and model
    ###############################################################################
    prob_assign = LpProblem()

    # Binary assignment variables to be optimized
    dv_assign = pd.DataFrame(np.array(addbinvars(len(d_date_duty), len(l_member))),
                            index=l_date_duty, columns=l_member)
    a_assign = dv_assign.to_numpy()


    ###############################################################################
    # Manual assignment
    ###############################################################################
    # Applied before the availability bounds below so that _forbid_assignment can recognise a
    # manually-pinned variable and keep the resulting contradiction well-formed.
    l_date_duty_manual = []
    for i_date_duty in d_assign_manual.loc[~d_assign_manual['id_member'].isna(), :].index.to_list():
        date_duty = d_assign_manual.loc[i_date_duty, 'date_duty']
        id_member = d_assign_manual.loc[i_date_duty, 'id_member']
        if date_duty in set_date_duty:
            var = dv_assign.loc[date_duty, id_member]
            var.lowBound, var.upBound = 1, 1
            l_date_duty_manual.append(date_duty)


    ###############################################################################
    # Availability per member per date_duty
    ###############################################################################
    # Do not assign to a date if not available. Expressed as variable bounds rather than as the
    # single dense `lpDot(unavailable, assignments) <= 0` row this used to be -- that one row
    # carried n_date_duty * n_member terms (~10k) and had to be assembled term by term in Python.
    a_unavailable = (d_availability.to_numpy() == 0)
    for i_date_duty, i_member in zip(*np.nonzero(a_unavailable)):
        _forbid_assignment(prob_assign, a_assign[i_date_duty, i_member])

    # Penalize suboptimal assignment. All coefficients are 1, so this is a plain sum over the
    # masked variables rather than a dot product over the whole matrix.
    v_assign_suboptimal = lpSum(a_assign[d_availability.to_numpy() == 1])


    ###############################################################################
    # Assignment per date_duty
    ###############################################################################
    # Assign one member per date_duty for ['am', 'pm', 'day', 'night', 'emnight', 'ect'].
    l_date_duty_fill = d_date_duty.loc[d_date_duty['duty'].isin(['am', 'pm', 'day', 'night', 'emnight', 'ect']),
                                       'date_duty'].tolist()

    # Elastic slack: 1 when the slot is left unfilled. Absent (and so the constraints below stay
    # plain equalities) unless elastic=True.
    dv_unassigned = {}
    if elastic:
        dv_unassigned = {date_duty: LpVariable('unassigned_' + date_duty, cat='Binary')
                         for date_duty in l_date_duty_fill}

    for date_duty in l_date_duty_fill:
        if date_duty in dv_unassigned:
            prob_assign += (lpSum(dv_assign.loc[date_duty]) + dv_unassigned[date_duty] == 1)
        else:
            prob_assign += (lpSum(dv_assign.loc[date_duty]) == 1)

    # Cap each OC slot at one member. 'ocday'/'ocnight' are deliberately not in the exactly-one
    # group above -- an OC slot is needed only when the primary day/night member is not a
    # designated physician, so an empty OC slot is a valid (and expected) outcome. But without
    # this cap nothing stopped a *second*, non-designated member being piled onto an OC slot
    # alongside the designated one: the designation constraint below only counts designated
    # members, so extra non-designated ones were unconstrained and only indirectly discouraged
    # by the count-deviation penalty.
    for date_duty in d_date_duty.loc[d_date_duty['duty'].isin(['ocday', 'ocnight']), 'date_duty'].tolist():
        prob_assign += (lpSum(dv_assign.loc[date_duty]) <= 1)

    # If non-designated member is assigned to ['day', 'night'] for the same date/time,
    # assign one designated member per date_duty for ['ocday', 'ocnight']
    s_member = d_member.set_index('id_member')
    l_designation = s_member['designation'].reindex(l_member).tolist()
    a_designation = np.array([l_designation] * 2)

    for duty in ['day', 'night']:
        for date in d_date_duty[d_date_duty['duty'] == duty]['date'].to_list():
            date_duty = str(date) + '_' + duty
            date_duty_oc = str(date) + '_oc' + duty
            if date_duty_oc in set_date_duty:
                # Sum of dot product of (normal and oc assignments) and (designation)
                # Returns number of 'designated' member assigned in the same date/time, which should be 1
                v_designated = lpSum(lpDot(dv_assign.loc[[date_duty, date_duty_oc]].to_numpy(), a_designation))
                if date_duty in dv_unassigned:
                    # ... unless the primary slot could not be filled at all, in which case there
                    # is nobody for an OC member to cover for either.
                    prob_assign += (v_designated + dv_unassigned[date_duty] == 1)
                else:
                    prob_assign += (v_designated == 1)


    ###############################################################################
    # Force full-time doctor assignment
    ###############################################################################
    a_fulltime = s_member['title_short'].reindex(l_member).isin(l_title_fulltime).to_numpy()
    for date_duty_fulltime in l_date_duty_fulltime:
        if date_duty_fulltime in set_date_duty:
            v_fulltime = lpSum(lpDot(dv_assign.loc[date_duty_fulltime].to_numpy(), a_fulltime))
            if date_duty_fulltime in dv_unassigned:
                prob_assign += (v_fulltime + dv_unassigned[date_duty_fulltime] == 1)
            else:
                prob_assign += (v_fulltime == 1)


    ###############################################################################
    # Penalize limit outliers per member per class_duty
    ###############################################################################
    # Variable dataframe of deviation from target
    dv_deviation_target = pd.DataFrame(np.array(addvars(len(l_member), len(l_class_duty))),
                                    index=l_member, columns=l_class_duty)
    # Variable dataframe of deviation from limit
    dv_deviation_limit = pd.DataFrame(np.array(addvars(len(l_member), len(l_class_duty))),
                                    index=l_member, columns=l_class_duty)

    # Which date_duty rows count toward each class_duty. The class_ columns are boolean masks, so
    # a member's count for a class is a plain sum over the selected variables -- no dot product,
    # and no zero terms for the rows outside the class.
    dict_mask_class = {class_duty: np.asarray(d_date_duty['class_' + class_duty].to_numpy()) != 0
                       for class_duty in l_class_duty}

    for i_member, member in enumerate(l_member):
        for class_duty in l_class_duty:
            lim_hard = d_lim_hard.loc[member, class_duty]
            [cnt_min, cnt_max] = lim_hard
            cnt_target = d_lim_exact.loc[member, class_duty]
            if np.isnan(cnt_min): # No limit specified for this member/class_duty
                continue
            # Built once per (member, class_duty) and reused by all 2-4 constraints below that
            # reference it. This loop used to rebuild the equivalent lpDot inside every one of
            # those constraints, re-walking all ~180 date_duty rows up to four times per pair.
            cnt_assigned = lpSum(a_assign[dict_mask_class[class_duty], i_member])
            if type_limit == 'ignore':
                prob_assign += (dv_deviation_limit.loc[member, class_duty] == 0)
                # Penalize deviation from target
                prob_assign += (dv_deviation_target.loc[member, class_duty] >= (cnt_assigned - cnt_target))
                prob_assign += (dv_deviation_target.loc[member, class_duty] >= (cnt_target - cnt_assigned))
            elif type_limit == 'hard':
                prob_assign += (dv_deviation_limit.loc[member, class_duty] == 0)
                if cnt_min == cnt_max:
                    # Exact count
                    prob_assign += (cnt_assigned == cnt_min)
                    prob_assign += (dv_deviation_target.loc[member, class_duty] == 0)
                else:
                    # Prohibit outlier from limit
                    prob_assign += (cnt_assigned >= cnt_min)
                    prob_assign += (cnt_assigned <= cnt_max)
                    # Penalize deviation from target
                    prob_assign += (dv_deviation_target.loc[member, class_duty] >= (cnt_assigned - cnt_target))
                    prob_assign += (dv_deviation_target.loc[member, class_duty] >= (cnt_target - cnt_assigned))
            elif type_limit == 'soft':
                # Penalize outlier from limit. dv_deviation_limit is already >= 0 (ortoolpy's
                # addvars defaults to lowBound=0), so no explicit non-negativity row is needed.
                prob_assign += (dv_deviation_limit.loc[member, class_duty] >= (cnt_assigned - cnt_max))
                prob_assign += (dv_deviation_limit.loc[member, class_duty] >= (cnt_min - cnt_assigned))
                # Penalize deviation from target
                prob_assign += (dv_deviation_target.loc[member, class_duty] >= (cnt_assigned - cnt_target))
                prob_assign += (dv_deviation_target.loc[member, class_duty] >= (cnt_target - cnt_assigned))

    # Kept as two separate objective terms with their own weights: overshooting a member's hard
    # min/max range (dv_deviation_limit, only reachable under type_limit='soft') is a much worse
    # outcome than missing their target count by the same amount (dv_deviation_target), and
    # summing both under one coefficient -- as this used to -- priced them identically.
    v_cnt_deviation = lpSum(dv_deviation_target.to_numpy())
    v_cnt_limit = lpSum(dv_deviation_limit.to_numpy())


    ###############################################################################
    # Student twice-assignation availability applied
    ###############################################################################
    s_assign_twice = d_info.set_index('id_member')['assign_twice'].reindex(l_member)
    for member in l_member:
        assign_twice = s_assign_twice[member]
        if assign_twice == False:
            prob_assign += (lpSum(dv_assign.loc[:, member]) <= 1)
        elif assign_twice == True:
            prob_assign += (lpSum(dv_assign.loc[:, member]) <= 2)


    ###############################################################################
    # ECT subleader applicability
    ###############################################################################
    l_date_duty_ect = d_date_duty.loc[d_date_duty['duty'] == 'ect', 'date_duty'].tolist()
    s_ect_subleader = s_member['ect_subleader'].reindex(l_member)
    for member in l_member:
        if s_ect_subleader[member] == False:
            for date_duty in l_date_duty_ect:
                _forbid_assignment(prob_assign, dv_assign.loc[date_duty, member])


    ###############################################################################
    # Avoid overlapping / adjacent / close assignments
    ###############################################################################
    # Avoid ['day', 'ocday', 'night', 'emnight', 'ocnight'] in N(thr_interval_daynight) continuous days
    # Avoid 'ect' in N(thr_interval_ect) continuous days
    # Avoid ['am','pm'] in N(thr_interval_ampm) continuous days

    # Copied before the missing-member columns are filled in: this used to mutate the caller's
    # DataFrame in place, and the caller reuses it across model builds.
    d_assign_previous = d_assign_previous.copy()
    l_member_missing = [m for m in l_member if m not in d_assign_previous.columns]
    if l_member_missing:
        d_assign_previous[l_member_missing] = 0

    def _continuous_date_duty(date_start, thr_interval, l_duty):
        """The date_duty's of l_duty falling in [date_start, date_start + thr_interval), split
        into the ones this month's model decides and the ones already fixed last month."""
        l_cont, l_cont_previous = [], []
        for date in range(date_start, date_start + thr_interval):
            for duty in l_duty:
                date_duty = str(date) + '_' + duty
                if date_duty in set_date_duty:
                    l_cont.append(date_duty)
                if date_duty in d_assign_previous.index:
                    l_cont_previous.append(date_duty)
        return l_cont, l_cont_previous

    def _is_manual_override(l_date_duty_cont):
        """Whether 2+ of a group's date_duty's are themselves manually designated
        (assign_manual.csv). A deliberate manual override between two manually-fixed slots should
        not be second-guessed by a closeness/adjacency rule. A single manual slot paired with an
        open one is unaffected -- the rule still keeps other members away from being close to it."""
        return sum(date_duty in l_date_duty_manual for date_duty in l_date_duty_cont) >= 2

    # Hard limit of closeness (avoid violence)
    for closeduty in dict_closeduty.keys():
        thr_interval_hard = dict_closeduty[closeduty]['thr_hard'] # 1: avoid within same day, 2: avoid within 2 continuous days
        l_duty = dict_closeduty[closeduty]['l_duty']
        if thr_interval_hard > 0:
            for date_start in [d for d in range(-thr_interval_hard + 2, 1)] + d_cal['date'].tolist():
                l_date_duty_cont, l_date_duty_cont_previous = _continuous_date_duty(date_start, thr_interval_hard, l_duty)
                if _is_manual_override(l_date_duty_cont):
                    continue
                # If the list of continuous date_duty's has more than one item
                if (len(l_date_duty_cont) + len(l_date_duty_cont_previous)) >= 2:
                    for i_member, member in enumerate(l_member):
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
            l_date_duty_cont, l_date_duty_cont_previous = _continuous_date_duty(date_start, thr_interval_soft, l_duty)
            # Same manual-override exemption the hard limit above applies. Without it a pair of
            # slots the operator deliberately gave to the same member kept charging the objective
            # a penalty they could do nothing about, which then displaced genuine trade-offs
            # elsewhere in the month. The variables stay in place (at 0) so that the reporting in
            # helper.py::extract_closeduty still sees a full grid.
            if _is_manual_override(l_date_duty_cont):
                continue
            if (len(l_date_duty_cont) + len(l_date_duty_cont_previous)) < 2:
                continue
            # Check if count of assignment per member per continuous date_duty's > 1 (penalize if so)
            for member in l_member:
                # var >= (count - 1), and var >= 0 (ortoolpy's addvars defaults to lowBound=0),
                # and var is minimized, resulting in: var = 0 if count = 0, 1 (no penalty);
                # var = count - 1 if count > 1 (penalty)
                prob_assign += (dict_dv_closeduty[closeduty].loc[date_start, member] >=\
                                (lpSum(dv_assign.loc[l_date_duty_cont, member]) + sum(d_assign_previous.loc[l_date_duty_cont_previous, member]) - 1))
    v_closeduty = lpSum([lpSum(dv_closeduty.to_numpy()) for dv_closeduty in dict_dv_closeduty.values()])

    # Avoid overlapping duties:
    #       [same-date 'pm', 'night', 'emnight' and 'ocnight'],
    #   and ['night', 'emnight', 'ocnight' and following-date 'ect','am']
    for date in [0] + d_cal['date'].tolist():
        for l_avoid_adjacent in ll_avoid_adjacent:
            l_avoid = [str(date + avoid[1]) + '_' + avoid[0] for avoid in l_avoid_adjacent]
            # Check if date_duty exists
            l_date_duty_cont = [date_duty for date_duty in l_avoid if date_duty in set_date_duty]
            l_date_duty_cont_previous = [date_duty for date_duty in l_avoid if date_duty in d_assign_previous.index]

            if _is_manual_override(l_date_duty_cont):
                continue

            if (len(l_date_duty_cont) + len(l_date_duty_cont_previous)) >= 2:
                for member in l_member:
                    prob_assign += (lpSum(dv_assign.loc[l_date_duty_cont, member]) +\
                                    sum(d_assign_previous.loc[l_date_duty_cont_previous, member]) <= 1)

    ###############################################################################
    # Avoid ECT from the leader's team
    ###############################################################################
    l_date_ect = d_date_duty.loc[d_date_duty['duty'] == 'ect', 'date'].tolist()
    for date in l_date_ect:
        wday = d_cal.loc[d_cal['date'] == date, 'wday'].to_list()[0]
        # No ECT leader registered for this weekday means there is no team to exclude. Indexing
        # [0] unconditionally here used to raise IndexError instead of leaving the slot open.
        l_team_leader = d_member.loc[d_member['ect_leader'] == int(wday), 'team'].to_list()
        if len(l_team_leader) == 0 or l_team_leader[0] == '-':
            continue
        l_id_member_team = d_member.loc[d_member['team'] == l_team_leader[0], 'id_member'].to_list()
        for id_member in l_id_member_team:
            if id_member in dv_assign.columns:
                _forbid_assignment(prob_assign, dv_assign.loc[str(date) + '_ect', id_member])


    ###############################################################################
    # Define objective function to be minimized
    ###############################################################################
    objective = (c_assign_suboptimal * v_assign_suboptimal
                 + c_cnt_deviation * v_cnt_deviation
                 + c_cnt_limit * v_cnt_limit
                 + c_closeduty * v_closeduty)
    prob_assign += objective

    return AssignModel(prob_assign, dv_assign, v_assign_suboptimal, v_cnt_deviation, v_cnt_limit,
                       v_closeduty, dict_dv_closeduty, dv_unassigned, objective)


def optimize_assign(*args, solver=None, **kwargs):
    """Build and solve the Stage-2 assignment MILP; returns the solved AssignModel."""
    model = build_assign_model(*args, **kwargs)
    model.prob.solve(solver if solver is not None else make_solver())
    return model


def optimize_count_and_assign(config, year_plan, month_plan, year_start, month_start,
                              dict_c_diff_score_current, dict_c_diff_score_total,
                              l_date_duty_skip_manual, dict_closeduty, ll_avoid_adjacent,
                              l_title_fulltime, l_date_duty_fulltime, type_limit,
                              c_assign_suboptimal, c_cnt_deviation, c_cnt_limit, c_closeduty,
                              dict_score_duty, dict_class_duty):

    services = get_services(config, SCOPE_DRIVE_FORMS)
    dp = prep_drive_paths(config, services, year_plan, month_plan, prefix_dir='asgn')
    solver = make_solver()

    ###############################################################################
    # Optimize exact assignment count
    ###############################################################################
    print('[1/4] Optimizing assignment counts...')

    s_cnt_class_duty = read_csv(services.drive, dp.id_month, 'cnt_class_duty.csv', index_col=0).squeeze(1)

    # Prepare data of member specs and assignment limits
    d_member, d_score_past, d_lim_hard, d_lim_soft, d_grp_score \
        = prep_member2(dp, year_plan, month_plan, year_start, month_start, dict_score_duty)
    # id_member, not d_member's row index: d_member carries a plain 0..n-1 index (assigned in
    # helper.py::read_member) while d_lim_hard, d_availability and assign_manual.csv are all keyed
    # by id_member. The two only coincided as long as every id_member happened to equal its own
    # row number in the config/member sheet.
    l_member = d_member['id_member'].tolist()

    # TODO: equilize 3 continous holidays assignment count
    dict_score_class = score_class_table(dict_score_duty, dict_class_duty, dict_score_classes)
    d_score_class = pd.DataFrame(dict_score_class)

    # Optimize assignment counts except OC
    status_opt_notoc, loss_opt_notoc,\
    d_lim_exact_notoc, d_score_current_notoc, d_score_total_notoc,\
    d_sigma_diff_score_current_notoc, d_sigma_diff_score_total_notoc = \
        optimize_count(d_member, s_cnt_class_duty, d_lim_hard, d_score_past,
                       d_score_class, d_grp_score, dict_c_diff_score_current, dict_c_diff_score_total,
                       l_type_score=['ampm', 'daynight', 'ampmdaynight', 'ect'],
                       l_class_duty=['ampm', 'daynight_tot', 'night_em', 'ect'],
                       solver=solver)
    if not status_opt_notoc:
        print('  [ERROR] Assignment count optimization failed (non-OC)')
        return [None] * 8

    # Optimize assignment counts of OC
    ln_daynight = d_lim_exact_notoc['daynight_tot'].tolist()
    l_designation = d_member['designation'].tolist()
    # round(), not int(): these counts come back from CBC as floats, so a count that solved to
    # 2.9999999 used to be truncated to 2 and quietly shifted the whole month's OC target by one.
    n_oc_required = int(round(sum([x * (y == False) for x, y in zip(ln_daynight, l_designation)])))
    s_cnt_class_duty['oc_tot'] = n_oc_required

    status_opt_oc, loss_opt_oc,\
    d_lim_exact_oc, d_score_current_oc, d_score_total_oc,\
    d_sigma_diff_score_current_oc, d_sigma_diff_score_total_oc = \
        optimize_count(d_member, s_cnt_class_duty, d_lim_hard, d_score_past,
                    d_score_class, d_grp_score, dict_c_diff_score_current, dict_c_diff_score_total,
                    l_type_score=['oc'],
                    l_class_duty=['oc_tot'],
                    solver=solver)

    if not status_opt_oc:
        print('  [ERROR] Assignment count optimization failed (OC)')
        return [None] * 8

    d_lim_exact = pd.concat([d_lim_exact_notoc, d_lim_exact_oc], axis=1)
    for col in d_lim_hard.columns:
        if not col in d_lim_exact.columns:
            d_lim_exact[col] = [x[0] for x in d_lim_hard[col].tolist()]
    d_lim_exact = d_lim_exact[d_lim_hard.columns]

    d_score_current = pd.concat([d_score_current_notoc, d_score_current_oc], axis=1)
    d_score_total = pd.concat([d_score_total_notoc, d_score_total_oc], axis=1)

    print('  Done (losses: ' + str(round(loss_opt_notoc, 2)) + ' non-OC, ' + str(round(loss_opt_oc, 2)) + ' OC)')

    ###############################################################################
    # Load and prepare data for duty assignment
    ###############################################################################
    print('[2/4] Preparing assignment data...')
    # Prepare data of member availability
    d_date_duty_noskip = read_csv(services.drive, dp.id_month, 'date_duty.csv')
    d_cal = read_csv(services.drive, dp.id_month, 'calendar.csv')
    d_assign_manual = read_csv(services.drive, dp.id_month, 'assign_manual.csv')
    d_info = read_csv(services.drive, dp.id_month, 'info.csv')
    d_availability_noskip = read_member_matrix_csv(services.drive, dp.id_month, 'availability.csv')
    d_availability_noskip = d_availability_noskip[l_member]
    d_availability_ratio = read_csv(services.drive, dp.id_month, 'availability_ratio.csv', index_col=0)
    d_assign_previous = prep_assign_previous(dp, year_plan, month_plan)
    d_date_duty, d_availability, l_date_duty_unavailable, l_date_duty_unavailable_notoc, l_date_duty_manual_assign, l_date_duty_skip =\
        skip_date_duty(d_date_duty_noskip, d_availability_noskip, d_availability_ratio, d_assign_manual, l_date_duty_skip_manual, True)

    ###############################################################################
    # Optimize assignment
    ###############################################################################
    print('[3/4] Solving member assignment...')

    def _build(elastic=False):
        return build_assign_model(d_date_duty, l_member, d_assign_manual, d_availability, d_member,
                                  l_title_fulltime, l_date_duty_fulltime, dict_class_duty,
                                  d_lim_hard, d_lim_exact, type_limit, d_info, d_assign_previous,
                                  dict_closeduty, d_cal, ll_avoid_adjacent,
                                  c_assign_suboptimal, c_cnt_deviation, c_cnt_limit, c_closeduty,
                                  elastic=elastic)

    model = _build()
    model.prob.solve(solver)

    # A per-member count limit that cannot be met is by far the most common cause of
    # infeasibility, and demoting it from a constraint to a penalty is almost always what the
    # operator wants -- so try that before the more drastic recovery below.
    if LpStatus[model.prob.status] == 'Infeasible' and type_limit == 'hard':
        print('  [WARNING] Infeasible with type_limit="hard". Retrying with "soft".')
        type_limit = 'soft'
        model = _build()
        model.prob.solve(solver)

    l_date_duty_unassignable = []
    if LpStatus[model.prob.status] == 'Infeasible':
        # Elastic recovery: give every must-fill slot an "unassigned" binary and let the solver
        # name the slots that cannot be filled, instead of searching for them by trial and error.
        #
        # This replaces a troubleshooting loop that re-solved the whole model once per candidate
        # duty -- a random-subset reduction phase followed by a one-by-one phase, up to roughly
        # len(date_duty) full solves of a ~10k-variable model. Besides the cost, that loop could
        # finish holding a solution that did not correspond to the skip set it reported (the
        # retained solution came from whichever iteration last solved, which also skipped duties
        # later found to be assignable), and it raised NameError outright if no iteration ever
        # solved.
        #
        # Two passes rather than one big-M penalty term: pass 1 minimises only the number of
        # unfilled slots, pass 2 re-optimises the real objective subject to that minimum. That is
        # exactly lexicographic, so no penalty weight has to be calibrated against the other
        # objective terms -- and a big-M picked even slightly too small would silently drop
        # duties that could in fact have been filled.
        print('  [RECOVERY] Infeasible. Identifying the smallest set of duties that cannot be filled...')
        model = _build(elastic=True)
        v_unassigned = lpSum(list(model.dv_unassigned.values()))
        model.prob.setObjective(v_unassigned)
        model.prob.solve(solver)
        if LpStatus[model.prob.status] != 'Optimal':
            print('  [ERROR] Still infeasible even with every duty slot allowed to go unfilled.')
            print('          The cause lies outside the per-slot assignment constraints -- check')
            print('          assign_manual.csv, the full-time-required slots, and the closeness')
            print('          thresholds for a direct contradiction.')
            return [None] * 8
        n_unassignable = int(round(value(v_unassigned)))
        # Pass 2: hold the number of unfilled slots at that minimum, optimise the real objective.
        # addConstraint, not `+=`: AssignModel is a namedtuple, so `model.prob += ...` would be an
        # assignment back into an immutable field rather than an in-place model update.
        model.prob.addConstraint(v_unassigned <= n_unassignable)
        model.prob.setObjective(model.objective)
        model.prob.solve(solver)
        l_date_duty_ordered = d_date_duty_noskip['date_duty'].tolist()
        l_date_duty_unassignable = sorted([date_duty for date_duty, v in model.dv_unassigned.items()
                                           if round(value(v) or 0) == 1],
                                          key=l_date_duty_ordered.index)
        # Folded into the skip list the same way the manually/automatically skipped duties are, so
        # extract_assignment marks them 'skipped' rather than 'unnecessary'. Ordered against
        # d_date_duty_noskip, not d_date_duty -- the latter has already had the originally-skipped
        # duties removed from it, so they would drop straight back out of the list here.
        set_skip = set(l_date_duty_skip) | set(l_date_duty_unassignable)
        l_date_duty_skip = [date_duty for date_duty in l_date_duty_ordered if date_duty in set_skip]
        print('  [RECOVERY] Unfillable duty[ies]:', l_date_duty_unassignable)


    ###############################################################################
    # Result output
    ###############################################################################
    print('[4/4] Extracting and saving results...')

    if str(LpStatus[model.prob.status]) == 'Optimal':
        warn_if_not_proven_optimal(model.prob, 'member assignment')
        print('  Done (losses: total=' + str(round(value(model.prob.objective), 2)) + ' = suboptimality '
              + str(round(c_assign_suboptimal * value(model.v_assign_suboptimal), 2)) + ' + count deviation '
              + str(round(c_cnt_deviation * value(model.v_cnt_deviation), 2)) + ' + count limit '
              + str(round(c_cnt_limit * value(model.v_cnt_limit), 2)) + ' + close duty '
              + str(round(c_closeduty * value(model.v_closeduty), 2)) + ')')

        # Save Stage-1 (count optimization) outputs. Deferred to here -- once the whole
        # two-stage solve has actually succeeded -- rather than saved right after Stage 1
        # finished: a vestige of when count-optimization and assignment were separate,
        # independently-run/saved steps. A Stage 2 failure used to still leave these on Drive
        # despite the run failing overall; now every write this function makes lands together in
        # one place. id_member is kept as an explicit column (never as the CSV's own row index --
        # see script/helper.py::prep_member2 for the same convention); in-memory shapes above are
        # unchanged.
        for id_folder in dp.l_id_write:
            write_csv(services.drive, id_folder, 'lim_exact.csv', d_lim_exact.rename_axis('id_member').reset_index(), index=False)
            write_csv(services.drive, id_folder, 'score_current_plan.csv', d_score_current.rename_axis('id_member').reset_index(), index=False)
            write_csv(services.drive, id_folder, 'score_total_plan.csv', d_score_total.rename_axis('id_member').reset_index(), index=False)

        # Extract data
        d_assign_date_duty =\
            extract_assignment(dp, year_plan, month_plan, model.dv_assign, d_date_duty_noskip, l_date_duty_skip)

        d_assign, d_assign_date_print, d_assign_member, d_deviation, d_deviation_summary, d_score_current, d_score_total, d_score_print =\
            convert_assignment(dp, d_assign_date_duty, d_availability_noskip,
                           d_member, d_date_duty, d_cal, dict_score_duty, d_lim_exact, d_lim_hard)

        d_closeduty = extract_closeduty(dp, model.dict_dv_closeduty, d_assign_date_duty, d_member, dict_closeduty)

        print()
        print('Deviation from target:')
        print(d_deviation_summary.to_string(index=False) if len(d_deviation_summary) > 0 else '  (none)')
        print()
        print('Close duties:')
        print(d_closeduty.to_string(index=False) if len(d_closeduty) > 0 else '  (none)')
        print()
        print('Candidate replacement:')
        print_candidate_replacement(services.drive, dp.id_month, dict_class_duty, d_deviation_summary, d_assign_date_duty, d_assign_member, d_closeduty)
        print()
        print('Done')

        return d_assign, d_assign_date_print, d_assign_member, d_deviation, d_score_print, d_closeduty, d_deviation_summary, d_assign_date_duty
    else:
        print('  [ERROR] Failed to solve (' + str(LpStatus[model.prob.status]) + ')')

        return [None] * 8
