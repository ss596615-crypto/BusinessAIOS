"""
Business AI OS
company_assets.py
"""

from pathlib import Path
import json

ROOT = Path(__file__).parent
ASSET_FILE = ROOT / "00_Company" / "04_Company_Assets" / "assets.json"

class CompanyAssets:

    def __init__(self):
        ASSET_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not ASSET_FILE.exists():
            ASSET_FILE.write_text("[]", encoding="utf-8")

    def load(self):
        return json.loads(ASSET_FILE.read_text(encoding="utf-8"))

    def save(self, data):
        ASSET_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def add(self, asset_type, name, location):
        data = self.load()
        data.append({
            "type": asset_type,
            "name": name,
            "location": location
        })
        self.save(data)

    def list(self):
        for item in self.load():
            print(f"{item['type']} | {item['name']} | {item['location']}")

if __name__ == "__main__":
    assets = CompanyAssets()
    assets.add("Project", "Business AI OS", "04_Projects")
    assets.list()
