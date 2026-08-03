import requests
url='http://127.0.0.1:8000/api/dispatches/3'
body={'qty_mt':2.5}
try:
    r=requests.patch(url,json=body)
    print(r.status_code)
    print(r.text)
except Exception as e:
    print('ERR',e)
