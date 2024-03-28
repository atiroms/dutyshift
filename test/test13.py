# Mask collected data with all 'unavailable'

import pandas as pd
import os


p_data = '/Users/smrt/Library/CloudStorage/Dropbox/dutyshift/202404'

d_availability_src = pd.read_csv(os.path.join(p_data, 'availability_src.csv'))

#l_member_ow = [41, 42, 43, 44]
#l_date_ow = [i for i in range(1, 15)]

l_member_ow = [20]
l_date_ow = [i for i in range(1, 8)]

l_col = d_availability_src.columns
lc_ow = []
for date in l_date_ow:
    lc_ow += [col for col in l_col if col.startswith(str(date) + '_')]

d_availability_dst = d_availability_src.copy()
d_availability_dst.loc[(d_availability_src['id_member'].isin(l_member_ow)), lc_ow] = 0.0

d_availability_dst.to_csv(os.path.join(p_data, 'availability_src.csv'), index = False)