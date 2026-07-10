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

def test_drive_connection():
    service = get_drive_service()

    results = service.files().list(
        pageSize=10,
        fields="files(id, name, mimeType)"
    ).execute()

    files = results.get("files", [])

    print("Google Drive 연결 성공")
    print("============================")

    if not files:
        print("Drive에서 파일을 찾지 못했습니다.")
    else:
        print("최근 파일 목록:")
        for file in files:
            print(f"- {file['name']} | {file['id']} | {file['mimeType']}")

if __name__ == "__main__":
    test_drive_connection()