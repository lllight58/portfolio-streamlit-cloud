from __future__ import annotations

import time


HIGH_KEYWORDS = [
    "10-K",
    "10-Q",
    "8-K",
    "사업보고서",
    "반기보고서",
    "분기보고서",
    "주요사항보고서",
    "실적",
    "earnings",
    "merger",
    "acquisition",
    "CEO",
    "CFO",
    "증자",
    "전환사채",
    "신주인수권",
    "자기주식",
    "배당",
    "공급계약",
    "소송",
    "영업정지",
    "상장폐지",
    "파산",
    "회계",
    "최대주주",
]
LOW_KEYWORDS = ["정정", "안내", "기재정정", "첨부정정"]


def classify_disclosure_importance(market: str, form_type: str, title: str) -> str:
    text = f"{market} {form_type} {title}".lower()
    if any(keyword.lower() in text for keyword in HIGH_KEYWORDS):
        return "높음"
    if any(keyword.lower() in text for keyword in LOW_KEYWORDS):
        return "낮음"
    return "보통"


def summarize_disclosure(
    market: str,
    form_type: str,
    title: str,
    filing_date: str,
    url: str,
    openai_api_key: str = "",
    model: str = "gpt-4o-mini",
) -> str:
    return rule_based_summary(market, form_type, title, filing_date)


def disabled_ai_summary() -> str:
    return "AI 요약 비활성화 상태입니다. 공시 제목, 유형, 날짜, 원문 링크를 기준으로 표시합니다."


def rule_based_summary(market: str, form_type: str, title: str, filing_date: str) -> str:
    form = str(form_type or "")
    if market == "US" and form in {"10-K", "10-Q"}:
        return f"[{form}] {filing_date} 제출된 정기보고서입니다. 대형 보고서라 주요 재무 수치 자동 추출은 제한적이며, 원문에서 매출, 이익, EPS, 현금흐름, 부채와 리스크 변화를 확인하세요."
    if market == "US" and form == "8-K":
        return f"[8-K] {title}. 실적, 경영진 변경, 자금조달, 배당, 계약, 소송 등 주요 이벤트 여부를 원문에서 확인하세요."
    if market == "KR" and form in {"사업보고서", "반기보고서", "분기보고서"}:
        return f"[{form}] {filing_date} 공시입니다. 본문 자동 요약은 추후 지원 예정이며, 원문에서 매출, 영업이익, 순이익, 자산/부채, 현금흐름과 배당 내용을 확인하세요."
    return f"[{form or '공시'}] {filing_date} 공시: {title}. 자동 AI 요약을 사용하려면 설정에서 OpenAI API Key를 입력해주세요."


def summarize_with_openai(
    market: str,
    form_type: str,
    title: str,
    filing_date: str,
    url: str,
    api_key: str,
    model: str,
) -> str:
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        prompt = (
            "투자자 관점에서 다음 공시를 3문장 이내로 요약하세요. "
            "원문 전문을 제공받지 못한 경우에는 공시 제목과 유형 기준으로 확인해야 할 핵심 항목을 짚어주세요.\n\n"
            f"시장: {market}\n공시유형: {form_type}\n공시일: {filing_date}\n공시제목: {title}\n원문URL: {url}"
        )
        response = client.chat.completions.create(
            model=model or "gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=300,
        )
        return str(response.choices[0].message.content or "").strip()
    except Exception:
        return ""


def classify_openai_error(exc: Exception) -> tuple[str, str]:
    text = str(exc)
    lowered = text.lower()
    if "insufficient_quota" in lowered or "you exceeded your current quota" in lowered or "check your plan and billing details" in lowered:
        return (
            "insufficient_quota",
            "OpenAI API Key 형식은 인식되었지만, 현재 API 사용 가능 쿼터가 없습니다. OpenAI Platform의 Billing, Usage, Limits 설정을 확인해주세요. AI 요약 기능은 비활성화하고 공시 목록 조회는 계속 진행합니다.",
        )
    if "401" in text or "invalid_api_key" in lowered or "incorrect_api_key" in lowered:
        return "invalid_api_key", "OpenAI API Key가 유효하지 않습니다. 키가 정확한지 확인해주세요."
    if "model_not_found" in lowered or "invalid model" in lowered:
        return "model_error", "요약 모델명을 확인해주세요. 현재 설정된 모델을 사용할 수 없습니다."
    if "rate_limit" in lowered or "429" in text:
        return "rate_limit", "OpenAI API 요청 한도에 일시적으로 도달했습니다. 잠시 후 다시 시도해주세요."
    return "unknown", f"OpenAI API 요청에 실패했습니다. ({text})"


def test_openai_api_key(api_key: str, model: str = "gpt-4o-mini") -> tuple[bool, str, str]:
    if not str(api_key or "").strip():
        return False, "missing", "OpenAI API Key가 입력되지 않았습니다. AI 요약만 비활성화됩니다."
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = None
        for attempt in range(3):
            try:
                response = client.chat.completions.create(
                    model=model or "gpt-4o-mini",
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=5,
                )
                break
            except Exception as exc:
                error_type, _ = classify_openai_error(exc)
                if error_type == "rate_limit" and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise
        if response.choices:
            return True, "ok", "성공"
        return False, "empty_response", "응답은 받았지만 결과가 비어 있습니다."
    except Exception as exc:
        error_type, message = classify_openai_error(exc)
        return False, error_type, message
