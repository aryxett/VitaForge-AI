import requests

BASE_URL = 'http://localhost:8080'
session = requests.Session()

# 1. Register a test user
register_data = {
    'name': 'API Tester',
    'email': 'api_tester@example.com',
    'password': 'password123',
    'confirm_password': 'password123'
}
res_reg = session.post(f"{BASE_URL}/register", data=register_data)
# We expect redirect to login or dashboard so status 200/302 is fine.

# 2. Login the user
login_data = {
    'email': 'api_tester@example.com',
    'password': 'password123'
}
res_login = session.post(f"{BASE_URL}/login", data=login_data)

# 3. Upload the resume
with open('test_resume.docx', 'rb') as f:
    files = {'resume': ('test_resume.docx', f, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')}
    data = {'job_role': 'software_engineer', 'job_description': '', 'custom_role': ''}
    res_upload = session.post(f"{BASE_URL}/api/upload", files=files, data=data)

if res_upload.status_code == 200:
    results = res_upload.json()
    print("E2E Test Successful! Here are the extracted keys:")
    print(list(results.keys()))
    print("Identity present:", "identity" in results)
    print("Sections present:", "sections" in results)
else:
    print("E2E Test Failed!")
    print("Status Code:", res_upload.status_code)
    try:
        print("Response:", res_upload.json())
    except:
        print("Raw Response:", res_upload.text)
