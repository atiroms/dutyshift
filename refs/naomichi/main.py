import numpy as np, pandas as pd
from pulp import *
from ortoolpy import addvars, addbinvars
import random
import datetime
import openpyxl
'''
Vは変数を表している
Cは定数を表している
shift.index は[1,,,,,30]
shift.columns は　[Aさん、・・・・Zさん]
1が入れる希望シフトでなおかつ最終的に入る人を示す
０はシフト禁止でなおかつ最終的に入らない人を示す。
'''
# ペナルティの重み定数
C_need_dif = 1000
C_lock = 50
C_3continuous_work = 20
C_2continuous_work = 3
C_average = 10
C_gender = 3
C_experience = 3
C_blank = 1
# ここでExcelのデータを取得
shift = pd.read_excel('1月作成用.xlsx',sheet_name='Shift',index_col=0)
manage = pd.read_excel('1月作成用.xlsx',sheet_name='Manage',index_col=0)
member = pd.read_excel('1月作成用.xlsx',sheet_name='Member',index_col=0)
member = member.T
detail = pd.read_excel('1月作成用.xlsx',sheet_name='Detail',index_col=0)
# Shiftシートのカラムとインデックス
date = shift.index
employee = shift.columns
# 確認用にコピー
shift_show = shift
# 従業員数と月の日数
days, number_employee = shift.shape[0], shift.shape[1]
holidays = play_ground.holiday_list(days)
# 変数作成
var = pd.DataFrame(np.array(addbinvars(days, number_employee)), columns=employee, index=date)
# ０と１を逆転させている
shift_rev = shift[shift.columns].apply(lambda r: 1-r[shift.columns],1)
k = LpProblem()
# 希望していない場所には入らないようにする。
for (_, h),(_, n) in zip(shift_rev.iterrows(),var.iterrows()):
    k += lpDot(h, n) <= 0
# 変数の追加
shift['V_need_dif'] = addvars(days)         # 必要人数に達していない時のペナルティ変数
shift['V_gender_rate'] = addvars(days)      # 女性が少ない時のペナルティ
shift['V_experience'] = addvars(days)       # 新人だけになった時のペナルティ
shift['need'] = manage.need                 # 必要人数
V_3continuous_work = np.array(addbinvars(days-2, number_employee))
V_2continuous_work = np.array(addbinvars(days-1, number_employee))
V_blank = np.array(addbinvars(days-6, number_employee))
V_max = addvars(number_employee)
V_min = addvars(number_employee)
V_lock = addvars(number_employee)
# 足りない人がいれば終了
shortage = []
for index,r in shift[employee].iterrows():
    if sum(r) < int(shift.at[index,'need']):
        shortage.append(index)
    if shortage:
        day = ''
        for i in shortage:
            day += (str(i) + '日足りません')
        print(day)
        sys.exit()

# 必要な人数に対するペナルティーを求める。
for (_, r),(_, d) in zip(shift.iterrows(),var.iterrows()):
    k += r.V_need_dif >= (lpSum(d) - r.need)
    k += r.V_need_dif >= -(lpSum(d) - r.need)
# 連勤に対してペナルティーを求める。
for i in list(range(number_employee)):
    for n,p in enumerate((var.values[:-2,i] + var.values[1:-1,i] + var.values[2:,i]).flat):
        k += p - V_3continuous_work[n][i] <= 2
for i in list(range(number_employee)):
    for n,p in enumerate((var.values[:-1,i] + var.values[1:,i]).flat):
        k += p - V_2continuous_work[n][i] <= 1
# 長く空きすぎるとペナルティ
for i in list(range(number_employee)):
    for n,p in enumerate((var.values[:-6,i] + var.values[1:-5,i] + var.values[2:-4,i] + var.values[3:-3,i]+ var.values[4:-2,i]+ var.values[5:-1,i]+ var.values[6:,i]).flat):
        k += p + V_blank[n][i] >= 1
# ある程度の入る量を調整
amount_more_user_list = member[member['amount'].isin([0])].index
amount_normal_user_list = member[member['amount'].isin([1])].index
amount_less_user_list = member[member['amount'].isin([2])].index
amount_zero_user_list = member[member['amount'].isin([3])].index
amount_lock_user_list = member[member['amount'].isin([4])].index
# 入りすぎ、入らなすぎにペナルティを与える変数
V_shift_max = pd.DataFrame(V_max,index=employee).T
V_shift_min = pd.DataFrame(V_min,index=employee).T
V_shift_lock = pd.DataFrame(V_lock,index=employee).T
# Excelから取得したデータをもとに
amount_more_setting = {'max': detail.at['max','more'], 'min': detail.at['min','more']}
amount_normal_setting = {'max': detail.at['max','normal'], 'min': detail.at['min','normal']}
amount_less_setting = {'max': detail.at['max','less'], 'min': detail.at['min','less']}
# 制約
for name, r in var[amount_more_user_list].iteritems():
    k += lpSum(r) + V_shift_max.at[0,name] >= amount_more_setting['min']
    k += lpSum(r) - V_shift_min.at[0,name] <= amount_more_setting['max']
for name, r in var[amount_normal_user_list].iteritems():
    k += lpSum(r) + V_shift_max.at[0,name] >= amount_normal_setting['min']
    k += lpSum(r) - V_shift_min.at[0,name] <= amount_normal_setting['max']
for name, r in var[amount_less_user_list].iteritems():
    k += lpSum(r) + V_shift_max.at[0,name] >= amount_less_setting['min']
    k += lpSum(r) - V_shift_min.at[0,name] <= amount_less_setting['max']
for (_, h),(name, n) in zip(shift[amount_lock_user_list].iteritems(),var[amount_lock_user_list].iteritems()):
    k += lpSum(n) + V_shift_lock.at[0,name] >= lpSum(h)
    k += lpSum(n) - V_shift_lock.at[0,name] <= lpSum(h)
# 男女偏り、新人のみにならない
woman_list = member[member['sex'].isin([1])].index
veteran_list = member[member['rank'].isin([1])].index
for (_,r),(_,d) in zip(shift.iterrows(),var[woman_list].iterrows()):
    if r.need == 0:
        pass
    else:
        k += (r.V_gender_rate + lpSum(d)) >= 2

for (_,r),(_,d) in zip(shift.iterrows(),var[veteran_list].iterrows()):
    if r.need == 0:
        pass
    else:
        k += (r.V_experience + lpSum(d)) >= 1
# 目的関数決定
k += C_need_dif * lpSum(shift.V_need_dif) \
    + C_3continuous_work * lpSum(V_3continuous_work) \
    + C_2continuous_work * lpSum(V_2continuous_work) \
    + C_average * lpSum(V_max) \
    + C_average * lpSum(V_min) \
    + C_gender * lpSum(shift.V_gender_rate) \
    + C_experience * lpSum(shift.V_experience) \
    + C_lock * lpSum(V_lock) \
    + C_blank * lpSum(V_blank)

k.solve()
result = np.vectorize(value)(var).astype(int)
R_continuous_work = np.vectorize(value)(V_2continuous_work).astype(int)
print('目的関数', value(k.objective))
print(result)
continuous_work_list = []
for i in np.sum(R_continuous_work,axis=0):
    if i >= 1:
        continuous_work_list.append('有')
    else:
        continuous_work_list.append('無')
fi = []
for cou,r in enumerate(result):
    fi.append([])
    for i,j in zip(r,shift.columns):
        if i*j != '':
            fi[cou].append(i*j)
            amount = []
            member_rev = member.T
        for name, r in member_rev.iteritems():
            if r.amount == 0:
                amount.append("多め")
            elif r.amount == 1:
                amount.append("普通")
            elif r.amount == 2:
                amount.append("少なめ")
            elif r.amount == 3:
                amount.append("無し")
            elif r.amount == 4:
                amount.append("固定")
count = np.sum(result, axis=0)
evaluation = pd.DataFrame([amount,count,continuous_work_list],
index=['シフト希望量', '入る量', '連勤'],columns=employee)
print(evaluation)
# ここで目視用のシートを作る
result_show_color = pd.DataFrame(result,index=date,columns=employee)
for index,i in result_show_color.iterrows():
for column, c in i.iteritems():
if c == 1: # 実際入ってる人
pass
elif c == 0 and shift.at[index,column] == 1: # 入る希望はあったが入らない人
pass
else:
result_show_color.at[index,column] = 2 # 入るつもりがない人
shift_member = fi
for values in shift_member:
random.shuffle(values)
shift_result = pd.DataFrame(shift_member,index=date)
with pd.ExcelWriter('1月.xlsx') as writer:
shift_result.to_excel(writer, sheet_name='Result')
evaluation.to_excel(writer, sheet_name='Evaluation')
result_show_color.to_excel(writer,sheet_name="show")