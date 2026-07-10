from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import pickle

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents.readonly"
]

def get_credentials():
    creds = None

    if os.path.exists("token_docs_read.pickle"):
        with open("token_docs_read.pickle", "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            "credentials.json",
            SCOPES
        )
        creds = flow.run_local_server(port=0)

        with open("token_docs_read.pickle", "wb") as token:
            pickle.dump(creds, token)

    return creds

def get_docs_service():
    creds = get_credentials()
    service = build("docs", "v1", credentials=creds)
    return service

def read_google_doc(document_id):
    service = get_docs_service()

    document = service.documents().get(
        documentId=document_id
    ).execute()

    title = document.get("title", "제목 없음")
    body = document.get("body", {}).get("content", [])

    print("AI CEO Google Docs 읽기 결과")
    print("============================")
    print(f"문서 제목: {title}")
    print("============================")

    text = ""

    for element in body:
        paragraph = element.get("paragraph")
        if not paragraph:
            continue

        for item in paragraph.get("elements", []):
            text_run = item.get("textRun")
            if text_run:
                text += text_run.get("content", "")

    if text.strip():
        print(text)
    else:
        print("문서에서 읽을 수 있는 텍스트가 없습니다.")

if __name__ == "__main__":
    document_id = input("읽을 Google Docs 문서 ID를 입력하세요: ")
    read_google_doc(document_id)