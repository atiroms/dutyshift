# Create Google drive folder

from googleapiclient.discovery import build
from script.helper import *

# Parameters
year_plan, month_plan, l_holiday  = 2025, 6, []
lp_root = ['/home/atiroms/Documents','D:/atiro','D:/NICT_WS','/Users/smrt']
l_scope = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive.metadata.readonly']

# Prepare credentials and service
p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = None, make_data_dir = None)
creds = prep_api_creds(p_root, l_scope)

# 3. Build the Drive API client:
service = build('drive', 'v3', credentials = creds)

path_new = '/dutyshift/result/' + str(year_plan) + '/' + str(month_plan).zfill(2)
result_folder = create_gdrive_path(service, path_new)
