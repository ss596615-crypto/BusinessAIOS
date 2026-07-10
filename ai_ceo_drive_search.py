from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import pickle

SCOPES = [
    "https://www.googleapis.com/auth/drive"
]

def get_drive_service():
    creds = None

    if os.path.exists("token_drive.pickle"):
        with open("token_drive.pickle", "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            "credentials.json",
            SCOPES
        )
        creds = flow.run_local_server(port=0)

        with open("token_drive.pickle", "wb") as token:
            pickle.dump(creds, token)

    service = build("drive", "v3", credentials=creds)
    return service

def search_drive(keyword):
    service = get_drive_service()

    query = f"name contains '{keyword}' and trashed = false"

    results = service.files().list(
        q=query,
        pageSize=20,
        fields="files(id, name, mimeType, modifiedTime)"
    ).execute()

    files = results.get("files", [])

    print("AI CEO Drive 검색 결과")
    print("============================")
    print(f"검색어: {keyword}")
    print("============================")

    if not files:
        print("검색 결과 없음")
        return

    for file in files:
        print(f"- 이름: {file['name']}")
        print(f"  ID: {file['id']}")
        print(f"  유형: {file['mimeType']}")
        print(f"  수정일: {file.get('modifiedTime', '')}")
        print("----------------------------")

if __name__ == "__main__":
    keyword = input("검색할 Drive 문서 또는 폴더 이름을 입력하세요: ")
    search_drive(keyword)