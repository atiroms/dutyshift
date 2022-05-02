import numpy as np, pandas as pd
from pulp import *
from ortoolpy import addvars, addbinvars
from io import StringIO

a = pd.read_table(StringIO("""\
曜日\t月\t月\t月\t火\t火\t火\t水\t水\t水\t木\t木\t木\t金\t金\t金\t土\t土\t土\t日\t日\t日
時間帯\t朝\t昼\t夜\t朝\t昼\t夜\t朝\t昼\t夜\t朝\t昼\t夜\t朝\t昼\t夜\t朝\t昼\t夜\t朝\t昼\t夜
必要人数\t2\t3\t3\t2\t3\t3\t2\t3\t3\t1\t2\t2\t2\t3\t3\t2\t4\t4\t2\t4\t4
従業員0\t○\t\t\t○\t\t\t○\t\t\t○\t\t\t○\t\t\t○\t\t\t○\t\t
従業員1\t○\t○\t○\t\t\t\t○\t○\t○\t\t\t\t○\t○\t○\t\t\t\t\t\t
従業員2\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t○\t○\t○\t○\t○\t○
従業員3\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○
従業員4\t\t\t○\t\t\t○\t\t\t○\t\t\t○\t\t\t○\t\t\t○\t\t\t○
従業員5\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t\t\t\t\t\t
従業員6\t\t\t\t\t\t\t\t\t\t\t\t\t○\t○\t○\t○\t○\t○\t○\t○\t○
従業員7\t\t○\t\t\t○\t\t\t○\t\t\t○\t\t\t○\t\t\t○\t\t\t○\t
従業員8\t\t\t○\t\t\t○\t\t\t○\t\t\t○\t\t\t○\t\t\t○\t\t\t○
従業員9\t\t\t\t\t\t\t\t\t\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○\t○""")).T
a,a.columns = a.iloc[1:],a.iloc[0].tolist()
a.必要人数 = a.必要人数.astype(int)
a.iloc[:,2:] = ~a.iloc[:,2:].isnull()
a.insert(0, '曜日', a.index.str[0])
a.reset_index(drop=True, inplace=True)
a = a.iloc[:,list(range(3,a.shape[1]))+[0,1,2]]
print(a[:3]) # 最初の3行表示

####

Nコマ,N従業員 = a.shape[0],a.shape[1]-3
L従業員 = list(range(N従業員))
L管理者 = [3,5,9] # 管理者は従業員3, 5, 9
C必要人数差 = 10
C希望不可 = 100
C最低コマ数 = 1
C管理者不足 = 100
C1日2コマ = 10
m = LpProblem() # 数理モデル
V割当 = np.array(addbinvars(Nコマ, N従業員))
a['V必要人数差'] = addvars(Nコマ)
V最低コマ数 = addvars(N従業員)
a['V管理者不足'] = addvars(Nコマ)
V1日2コマ = addvars(N従業員)
m += (C必要人数差 * lpSum(a.V必要人数差)
    + C希望不可 * lpSum(a.apply(lambda r: lpDot(1-r[L従業員],V割当[r.name]), 1))
    + C最低コマ数 * lpSum(V最低コマ数)
    + C管理者不足 * lpSum(a.V管理者不足)
    + C1日2コマ * lpSum(V1日2コマ)) # 目的関数
for _,r in a.iterrows():
    m += r.V必要人数差 >=  (lpSum(V割当[r.name]) - r.必要人数)
    m += r.V必要人数差 >= -(lpSum(V割当[r.name]) - r.必要人数)
    m += lpSum(V割当[r.name,L管理者]) + r.V管理者不足 >= 1
for j,n in enumerate((a.iloc[:,L従業員].sum(0)+1)//2):
    m += lpSum(V割当[:,j]) + V最低コマ数[j] >= n # 希望の半分以上
for _,v in a.groupby('曜日'):
    for j in range(N従業員):
        m += lpSum(V割当[v.index,j]) - V1日2コマ[j] <= 2 # 各曜日で2コマまで

%time m.solve()
R結果 = np.vectorize(value)(V割当).astype(int)
a['結果'] = [''.join(i*j for i,j in zip(r,a.columns)) for r in R結果]
print('目的関数', value(m.objective))
print(a[['曜日','時間帯','結果']])