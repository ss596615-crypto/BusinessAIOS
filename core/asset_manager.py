from pathlib import Path
import json


class AssetManager:

    def __init__(self):
        self.root = Path(r"C:\BusinessAIOS")
        self.asset_file = (
            self.root /
            "00_Company" /
            "04_Company_Assets" /
            "assets.json"
        )


    def scan(self):

        self.asset_file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        assets = []

        for item in self.root.rglob("*"):
            if item.is_file():
                assets.append(
                    str(item.relative_to(self.root))
                )

        self.asset_file.write_text(
            json.dumps(
                assets,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        return assets