# test reading Google spreadsheet using Google API

from googleapiclient.discovery import build
import pandas as pd
from script.helper import *

# Parameters
year_plan, month_plan, l_holiday  = 2025, 6, []
lp_root = ['/home/atiroms/Documents','D:/atiro','D:/NICT_WS','/Users/smrt']
l_scope = ['https://www.googleapis.com/auth/spreadsheets.readonly']

# Prepare credentials and service
p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = None, make_data_dir = None)
creds = prep_api_creds(p_root, l_scope)
service = build('sheets', 'v4', credentials = creds)

# Call the Sheets API
# Replace with your actual spreadsheet ID
#SPREADSHEET_ID = '1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms'
SPREADSHEET_ID = '1dG3v6nLVHo239wMUQvDTa4n1zALiW6erWZ9O9jE3Vac'

#RANGE_NAME = 'Sheet1!A1:E10'  # Adjust range as needed
RANGE_NAME = 'response'  # Adjust range as needed

# Reading data
result = service.spreadsheets().values().get(
    spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
values = result.get('values', [])

d_replacement = pd.DataFrame(values)