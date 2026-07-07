from pathlib import Path
from datetime import datetime


class ReportManager:

    def __init__(self):
        self.root = Path(r"C:\BusinessAIOS")

        self.folder = (
            self.root /
            "01_AI_CEO" /
            "04_Reports"
        )

        self.folder.mkdir(
            parents=True,
            exist_ok=True
        )


    def create_operation_report(self, instruction, analysis):

        content = f"""
# AI CEO 운영보고서

## 대표 지시
{instruction}

## 분석 결과
{analysis}

## 상태
업무 분석 완료

## 다음 업무
실행 계획 수립
"""

        filename = (
            datetime.now()
            .strftime("%Y%m%d_%H%M%S")
            + "_operation_report.md"
        )

        file = self.folder / filename

        file.write_text(
            content,
            encoding="utf-8"
        )

        return content