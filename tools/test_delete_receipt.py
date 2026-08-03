import requests
url='http://127.0.0.1:8000/api/receipts/9'
try:
    r=requests.delete(url)
    print(r.status_code)
    print(r.text)
except Exception as e:
    print('ERR',e)
