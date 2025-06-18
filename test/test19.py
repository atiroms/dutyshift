# Test directly reading Google forms response

import pandas as pd
from googleapiclient.discovery import build
from script.helper import *

# Parameters
year_plan, month_plan, l_holiday  = 2025, 6, []
lp_root = ['/home/atiroms/Documents','D:/atiro','D:/NICT_WS','/Users/smrt']
l_scope = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/forms.body']

# Prepare credentials and service
p_root, p_month, p_data = prep_dirs(lp_root, year_plan, month_plan, prefix_dir = None, make_data_dir = None)
creds = prep_api_creds(p_root, l_scope)
service_drive = build('drive', 'v3', credentials = creds)
service_forms = build('forms', 'v1', credentials = creds)

# Check if form exists
path_form = '/dutyshift/result/' + str(year_plan) + '/' + str(month_plan).zfill(2) + '/form_' +  str(year_plan) + str(month_plan).zfill(2)
id_form = check_form_exists(service_drive, path_form)

# 3. Fetch the form metadata (to map questionId → question title)
form = service_forms.forms().get(formId = id_form).execute()
# Build a mapping of questionId → title
qid2title = {}
for item in form.get('items', []):
    if 'questionItem' in item:
        q = item['questionItem']['question']
        qid = q.get('questionId')
        title = item.get('title','')
        if qid:
            qid2title[qid] = title
    elif 'questionGroupItem' in item:
        questions = item['questionGroupItem']['questions']
        title = item.get('title','')
        for q in questions:
            qid = q.get('questionId')
            title_2 = q['rowQuestion'].get('title', '')
            if qid:
                qid2title[qid] = title + '[' + title_2 + ']'

# 4. Pull all responses
l_response = []
l_timestamp = []
page_token = None
while True:
    resp = service_forms.forms().responses().list(
        formId = id_form,
        pageToken = page_token,
        pageSize = 100  # up to 5000 max
    ).execute()
    for r in resp.get('responses', []):
        timestamp = r['lastSubmittedTime']
        # each answer is keyed by questionId
        ans = {}
        for qid, answer in r['answers'].items():
            # textAnswers vs choiceAnswers:
            if 'textAnswers' in answer:
                # concatenate multiple text answers if any
                vals = [t['value'] for t in answer['textAnswers']['answers']]
                ans[qid] = ' | '.join(vals)
            elif 'choiceAnswers' in answer:
                ans[qid] = answer['choiceAnswers']
            else:
                # other types (e.g. fileUpload), fallback to raw
                ans[qid] = str(answer)
        l_response.append(ans)
        l_timestamp.append(timestamp)
    page_token = resp.get('nextPageToken')
    if not page_token:
        break

# 5. Build DataFrame
d_availability_src = pd.concat([pd.DataFrame(columns = qid2title.keys()), pd.DataFrame.from_records(l_response)], axis = 0)
d_availability_src.columns = qid2title.values()
