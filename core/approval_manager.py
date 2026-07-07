from pathlib import Path
from datetime import datetime


class ApprovalManager:

    def __init__(self):
        self.folder = (
            Path(r"C:\BusinessAIOS")
            / "01_AI_CEO"
            / "05_Approvals"
        )

        self.folder.mkdir(
            parents=True,
            exist_ok=True
        )


    def create_request(self, title, content):

        filename = (
            datetime.now()
            .strftime("%Y%m%d_%H%M%S_")
            + title
            + ".md"
        )

        file = self.folder / filename

        file.write_text(
            content,
            encoding="utf-8"
        )

        return file