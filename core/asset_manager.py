from pathlib import Path

from config.google_drive import connect_drive


class AssetManager:

    def __init__(self):
        self.root = Path(r"C:\BusinessAIOS")

    def scan(self):

        assets = []

        # ------------------------
        # Local
        # ------------------------

        if self.root.exists():

            for item in self.root.rglob("*"):

                if item.is_file():

                    assets.append(
                        f"[LOCAL] {item.relative_to(self.root)}"
                    )

        # ------------------------
        # Google Drive
        # ------------------------

        try:

            service = connect_drive()

            results = service.files().list(
                pageSize=100,
                fields="files(id,name,mimeType)"
            ).execute()

            files = results.get("files", [])

            for file in files:

                assets.append(
                    f"[DRIVE] {file['name']}"
                )

        except Exception as e:

            assets.append(
                f"[Google Drive 오류] {e}"
            )

        return assets

    def search(self, keyword=""):

        assets = self.scan()

        if keyword == "":
            return assets

        results = []

        for asset in assets:

            if keyword.lower() in asset.lower():

                results.append(asset)

        return results