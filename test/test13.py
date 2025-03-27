# Mask collected data with all 'unavailable'

import pandas as pd
import os


#p_data = '/Users/smrt/Library/CloudStorage/Dropbox/dutyshift/202404'
p_data = '/Users/smrt/Library/CloudStorage/Dropbox/dutyshift/202504'

d_availability_src = pd.read_csv(os.path.join(p_data, 'availability.csv'))

l_member_ow = [46, 47, 48, 23, 49, 50, 51, 52]
#l_member_ow = [46, 49, 50, 51, 52]
l_date_ow = [i for i in range(1, 8)]

#l_member_ow = [20]
#l_date_ow = [i for i in range(1, 8)]

l_col = d_availability_src['Unnamed: 0'].tolist()
lc_ow = []
for date in l_date_ow:
    lc_ow += [col for col in l_col if col.startswith(str(date) + '_')]

l_member_ow = [str(member) for member in l_member_ow]

d_availability_dst = d_availability_src.copy()
d_availability_dst.loc[(d_availability_src['Unnamed: 0'].isin(lc_ow)), l_member_ow] = 0.0

d_availability_dst.to_csv(os.path.join(p_data, 'availability.csv'), index = False)