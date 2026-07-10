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


    def check(self, command):

        keywords = [
            "계약",
            "구매",
            "투자",
            "제조",
            "비용",
            "결제"
        ]


        for word in keywords:

            if word in command:

                return self.create_request(
                    command
                )


        return "승인 필요 없음"



    def create_request(self, command):

        content = f"""
# AI CEO 승인 요청서


## 대표 지시

{command}


## 승인 사유

외부 비용 또는 의사결정 필요 업무


## 요청 사항

대표 승인 후 실행 진행


## 생성 시간

{datetime.now()}
"""


        filename = (
            datetime.now()
            .strftime("%Y%m%d_%H%M%S")
            + "_approval_request.md"
        )


        file = self.folder / filename

        file.write_text(
            content,
            encoding="utf-8"
        )


        return f"승인 요청 생성: {filename}"