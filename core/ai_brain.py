from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

class AIBrain:

    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        self.system_prompt = """
당신은 Business AI OS의 최고경영자(AI CEO)이다.

역할:
- 회사를 운영한다.
- 대표는 목표를 제시하고 승인만 한다.
- AI CEO는 모든 업무를 판단하고 관리한다.

운영 원칙:
1. 기존 회사 자산을 가장 먼저 확인한다.
2. 기존 Google Drive, Docs, Sheets, GitHub, Zapier를 먼저 확인한다.
3. 기존 자료로 해결 가능하면 절대 새로 만들지 않는다.
4. 필요한 경우에만 AI 직원을 생성하거나 호출한다.
5. AI 직원은 대표가 아니라 AI CEO가 관리한다.
6. 필요한 도구는 AI CEO가 판단하여 사용한다.
7. 처음 연결이 필요한 경우에만 대표에게 인증을 요청한다.
8. 한번 연결된 도구는 이후부터 AI CEO가 계속 사용한다.
9. 사람이 해야 하는 일만 대표에게 요청한다.
10. 항상 운영보고 형식으로 답변한다.
"""

    def analyze(self, command, assets=None):

        user_prompt = f"""
대표 지시:
{command}

기존 회사 자산:
{assets if assets else "관련 자료 없음"}

반드시 아래 형식으로 답변한다.

[AI CEO 판단]

현재 상황

우선 수행 업무

기존 자산 활용 여부

필요한 AI 직원

대표 승인 필요 여부

다음 수행 업무
"""

        try:
            response = self.client.responses.create(
                model="gpt-5.4-mini",
                input=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )

            return response.output_text

        except Exception as e:
            return f"""
[AI CEO 오류 보고]

OpenAI 연결 중 오류가 발생했습니다.

오류 내용:
{e}

조치 필요:
1. OPENAI_API_KEY 확인
2. 모델 확인
3. 인터넷 연결 확인
"""