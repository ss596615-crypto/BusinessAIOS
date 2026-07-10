from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


def connect_sheets():

    credential_file = os.path.join(
        "config",
        "client_secret_757815373949-uu1nvfetlhepiug3rta7871g8a26908u.apps.googleusercontent.com.json"
    )

    flow = InstalledAppFlow.from_client_secrets_file(
        credential_file,
        SCOPES
    )

    creds = flow.run_local_server(port=0)

    service = build(
        "sheets",
        "v4",
        credentials=creds
    )

    return service