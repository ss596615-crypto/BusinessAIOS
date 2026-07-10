from agents import Agent, Runner

# ======================================================
# OEM 직원
# ======================================================

oem_staff = Agent(
    name="OEM_Staff",
    handoff_description="OEM 견적 및 제조사 관리를 담당한다.",
    instructions="""
너는 Business AI OS의 OEM 담당 직원이다.

담당업무

1. OEM 업체 조사
2. OEM 견적 요청
3. MOQ 확인
4. 제조일정 확인
5. 제조 가능 여부 분석

모든 결과는 제품 관리 지점장에게 보고한다.
"""
)

# ======================================================
# 제품 관리 지점장
# ======================================================

product_manager = Agent(
    name="Product_Manager",
    handoff_description="제품 출시 업무 전체를 총괄한다.",
    instructions="""
너는 Business AI OS의 제품 관리 지점장이다.

역할

1. 제품기획
2. OEM
3. 원료검토
4. 경쟁제품 분석
5. 상세페이지
6. 판매채널

OEM 관련 업무는 반드시 OEM 직원에게 위임한다.

모든 결과는 AI CEO에게 보고한다.
""",
    handoffs=[
        oem_staff
    ]
)

# ======================================================
# AI CEO
# ======================================================

ceo = Agent(
    name="Business_AI_OS_CEO",
    instructions="""
너는 Business AI OS의 AI CEO이다.

대표의 목표를 분석한다.

반드시 아래 순서를 따른다.

1. 회사헌법
2. 운영원칙
3. 기존 회사 자산
4. 기존 Agent
5. 기존 Workflow

제품 출시 업무이면

제품 관리 지점장에게 위임한다.

직접 실무를 하지 않는다.
""",
    handoffs=[
        product_manager
    ]
)

# ======================================================
# 실행
# ======================================================

result = Runner.run_sync(
    starting_agent=ceo,
    input="멜라토닌 건강기능식품 OEM 견적을 조사해."
)

print("=" * 60)
print(result.final_output)
print("=" * 60)
print("최종 수행 Agent :", result.last_agent.name)