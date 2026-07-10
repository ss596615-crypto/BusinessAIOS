from pathlib import Path
from datetime import datetime


class ReportManager:

    def __init__(self):

        self.folder = (
            Path(r"C:\BusinessAIOS")
            / "01_AI_CEO"
            / "04_Reports"
        )

        self.folder.mkdir(
            parents=True,
            exist_ok=True
        )


    def create_operation_report(self, instruction, analysis):

        report = f"""
# AI CEO 운영보고서


## 1. 대표 지시

{instruction}


## 2. 업무 분석

{analysis}


## 3. 실행 결과

{analysis}


## 4. 현재 판단

기존 회사 자산을 우선 검토하고
필요한 AI 직원을 활용하여 업무를 수행함.


## 5. 대표 승인 필요사항

추가 비용 발생,
외부 계약,
신규 자동화 구축 시 승인 필요.


## 6. 다음 수행 업무

업무 결과 검토 후 다음 실행 단계 진행.
"""


        filename = (
            datetime.now()
            .strftime("%Y%m%d_%H%M%S")
            + "_AI_CEO_Report.md"
        )


        file = self.folder / filename

        file.write_text(
            report,
            encoding="utf-8"
        )

        return report