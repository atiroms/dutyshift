# test reading Google spreadsheet using Google API

import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pandas as pd


p_root = '/Users/smrt'
l_scope = ['https://www.googleapis.com/auth/spreadsheets.readonly']

# Handle Credentials and token
p_token = os.path.join(p_root, 'Dropbox/dutyshift/config/credentials/token.json')
p_cred = os.path.join(p_root, 'Dropbox/dutyshift/config/credentials/credentials.json')

flow = InstalledAppFlow.from_client_secrets_file(p_cred, l_scope)
creds = flow.run_local_server(port = 0)
#print('credentials.json used.')
# Save the credentials for the next run
with open(p_token, 'w') as token:
    token.write(creds.to_json())

#service = build('calendar', 'v3', credentials = creds)
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

