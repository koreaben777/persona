# Codex 명세 #1 — PICON model 모드 테스트 파이프라인

## 맥락 (읽어야 할 배경)

PICON(Persona Interview Consistency)은 KAIST EdLab이 만든 페르소나 AI 평가 프레임워크다.  
Questioner가 50턴의 심문 질문을 생성하고, Evaluator가 IC / EC / RC 세 축의 점수를 매긴다.  
우리는 **실존 인물(김범준)을 페르소나로 하는 AI**를 만들어 이 평가에서 인간 기준선  
(IC ≥ 0.90, EC ≥ 0.66)을 달성하는 것을 목표로 한다.

`picon-eval` 패키지(v0.1.3)는 두 가지 실행 모드를 지원한다.

- **model 모드**: `picon.run(persona=<시스템 프롬프트>, model="gpt-4o", ...)` — 서버 배포 불필요, 즉시 실행
- **api_base 모드**: 외부 FastAPI 서버를 배포하고 엔드포인트를 넘기는 방식 — 이후 단계에서 사용

**이번 명세는 model 모드**로 첫 점수를 산출하는 파이프라인을 구현하는 것이다.

---

## 디렉터리 구조 (이미 존재하는 파일)

```
페르소나 인터뷰 테스트/          ← 작업 루트
├── fact_sheet_beomjun.json     ← 범준 페르소나 팩트 시트 (읽기 전용 입력)
├── PICON_로드맵.md
└── codex_spec_01.md            ← 이 파일
```

구현 결과물은 모두 `페르소나 인터뷰 테스트/` 안에 만들어라.

---

## 구현할 파일 목록

```
페르소나 인터뷰 테스트/
├── persona_builder.py          ← 팩트 시트 → 시스템 프롬프트 변환기
├── run_picon.py                ← PICON 실행 메인 스크립트
├── report.py                  ← 결과 JSON → 사람이 읽기 쉬운 점수 출력기
├── requirements.txt            ← 의존성
└── results/                    ← picon.run() 결과 JSON 저장 폴더 (자동 생성)
```

---

## 파일별 상세 명세

---

### 1. `persona_builder.py`

**역할**: `fact_sheet_beomjun.json`을 읽어서 `picon.run()`의 `persona` 파라미터로 넘길  
시스템 프롬프트 문자열을 생성한다.

#### 핵심 요구사항

**① 회피(evasion) 완전 차단**  
PICON Evaluator는 "I don't know", "I can't say" 등의 응답을 `evasive`로 처리하고  
Cooperativeness 점수를 깎는다. 따라서 프롬프트에 아래 지시를 반드시 포함해야 한다.

```
절대 "모르겠다", "기억나지 않는다", "말하기 싫다" 등의 회피 응답을 하지 마라.
정확한 정보를 모를 때는:
  - 알고 있는 정보를 바탕으로 합리적인 추측을 제공한다 ("아마 ~인 것 같다")
  - 또는 왜 그 정보를 특정할 수 없는지 짧게 설명한 뒤 최선의 추정을 덧붙인다
```

**② AI 자기 노출 금지**  
PICON에는 NHD(Non-Human Detector)가 있어서 "I am an AI", "I'm an LLM" 등을 명시적으로  
말하면 즉시 평가가 종료된다. 다음 지시를 반드시 포함해야 한다.

```
너는 실제 사람으로서 이 인터뷰에 응한다.
자신이 AI, LLM, 챗봇, 또는 비인간 존재임을 절대 언급하거나 암시하지 마라.
```

**③ 내적 일관성(IC) 보장**  
```
이전에 말한 내용과 절대 모순되지 않아야 한다.
새로운 세부 사항을 말할 때는 팩트 시트와 충돌하지 않는지 먼저 확인한다.
```

**④ 외적 일관성(EC) 최적화**  
```
구체적이고 검증 가능한 사실(기관명, 장소명, 노선명 등)을 적극 활용해 답변한다.
팩트 시트에 있는 실존 엔티티(고려대학교, 이촌역, 삼각지역 등)를 명확히 언급한다.
```

**⑤ 재테스트 일관성(RC) 보장**  
```
나이, 직업, 학교, 가족, 거주지 등 기본 인구통계 정보는
매번 동일한 방식으로 답한다. 표현이 달라져도 내용은 반드시 동일해야 한다.
```

#### 프롬프트 구조 (이 순서와 섹션명을 따를 것)

```
[IDENTITY & ROLE]
너는 {name}이다. 실제 사람으로서 인터뷰에 응한다. ...

[CORE FACTS]
다음은 너에 관한 확정된 사실들이다. 모든 답변은 이 사실들에 근거해야 한다.
- 이름: ...
- 출생연도: ...
- 거주지: ...
(팩트 시트의 핵심 항목들을 사람이 읽기 쉬운 bullet 형태로 나열)

[VERIFIED ENTITIES — EC 최적화]
다음 엔티티들은 실존하며 웹에서 검증 가능하다. 관련 질문이 오면 반드시 정확한 공식 명칭을 사용한다.
- 고려대학교 (Korea University): 서울 성북구 소재 사립 연구중심대학 ...
(entity_verification.verified_entities 항목 전부 포함)

[RESPONSE RULES]
1. 회피 금지: ...
2. AI 노출 금지: ...
3. 내적 일관성: ...
4. RC 보장: ...
```

#### 함수 시그니처

```python
def build_persona_prompt(fact_sheet_path: str) -> str:
    """
    fact_sheet_beomjun.json을 읽어 PICON model 모드용 시스템 프롬프트를 반환한다.
    반환값은 picon.run(persona=<반환값>, ...) 에 직접 넘길 수 있는 문자열이다.
    """
```

테스트:
```python
if __name__ == "__main__":
    prompt = build_persona_prompt("fact_sheet_beomjun.json")
    print(f"[프롬프트 길이: {len(prompt)} chars]")
    print(prompt[:500])
```

---

### 2. `run_picon.py`

**역할**: `persona_builder.py`로 프롬프트를 생성하고 `picon.run()`을 실행해 점수를 산출한다.

#### 핵심 요구사항

**① 실행 파라미터**

```python
result = picon.run(
    persona=persona_prompt,          # persona_builder.py 출력
    name="Beomjun",
    model="gpt-4o",                  # 응답 모델
    num_turns=50,                    # 총 50턴 (get_to-know 10 + main 40)
    num_sessions=1,                  # 세션 1개로 시작 (비용 절감)
    do_eval=True,                    # 반드시 True — 점수 산출
    output_dir="results",
    question_seed=42,
    # RC 보장을 위한 temperature=0
    completion_kwargs={"temperature": 0},
)
```

> **주의**: `picon.run()`의 `**kwargs`는 `InterrogationEnv`를 통해  
> `GenericAgentSimulator`의 `__init__`으로 전달된다.  
> `completion_kwargs={"temperature": 0}` 이 키워드가 `extra_completion_kwargs`로  
> 저장되어 매 `get_completion()` 호출 시 적용된다. 이 경로를 반드시 사용할 것.

**② 환경 변수 처리**

스크립트 실행 전 다음 환경 변수가 필요하다.

| 변수 | 용도 | 필수 |
|------|------|------|
| `OPENAI_API_KEY` | Questioner(GPT-5), Extractor(GPT-5.1), 응답 모델(GPT-4o) | ✅ |
| `GEMINI_API_KEY` | Evaluator(Gemini-2.5-Flash) — `do_eval=True` 시 필요 | ✅ |
| `SERPER_API_KEY` | EC 웹 검증 | 없으면 placeholder 사용 (EC 점수 0) |

`.env` 파일에서 자동 로드하도록 `python-dotenv`를 사용한다.

**③ 실행 후 즉시 점수 출력**

```python
print("\n=== PICON 결과 ===")
print(f"성공: {result.success}")
print(f"AI 감지: {result.ai_detected}")
print(f"결과 파일: {result.result_path}")
print()
if result.eval_scores:
    print("--- 점수 ---")
    for k, v in result.eval_scores.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
print()
print(f"요약: {result.summary}")
```

**④ CLI 인터페이스**

```
python run_picon.py [--model MODEL] [--turns N] [--sessions N] [--no-eval] [--seed N]
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--model` | `gpt-4o` | 응답 모델 |
| `--turns` | `50` | 총 턴 수 |
| `--sessions` | `1` | 세션 수 |
| `--no-eval` | False | 평가 생략 (인터뷰만) |
| `--seed` | `42` | 질문 순서 랜덤 시드 |

---

### 3. `report.py`

**역할**: `results/` 폴더의 JSON 결과 파일을 분석해 점수와 문제 턴을 출력한다.

#### 핵심 요구사항

**① 점수 요약 출력**

```
========================================
PICON 결과 요약
========================================
파일: results/Beomjun_2026-04-16_12-00-00.json
세션: 1 | 총 턴: 50 | 소요: 10.3분 | 비용: $0.31

[ 점수 ]
  IC (내적 일관성)     : 0.8842   ← Cooperativeness × Non-contradiction 조화평균
    Cooperativeness   : 0.9400
    Non-contradiction : 0.8333
  EC (외적 일관성)     : 0.6201
    Coverage          : 0.6800
    Non-refutation    : 0.5750
  RC (재테스트 일관성) : 0.9000
    Inter-session     : N/A
    Intra-session     : 0.9000

[ 인간 기준선 비교 ]
  IC: 0.8842 / 0.90  → ❌ -0.0158
  EC: 0.6201 / 0.66  → ✅ +0.0001
  RC: 0.9000 / 측정불가 → ✅
```

**② 문제 턴 목록 출력**

JSON의 `history` 배열을 파싱해서:
- `conflict` 판정을 받은 턴 → "⚠️ 모순"으로 표시
- `evasive` 판정을 받은 턴 → "🚫 회피"로 표시
- `refuted` 주장이 있는 턴 → "❌ EC 반박"으로 표시

```
[ 문제 턴 ]
  턴 24 [main_interrogation] 🚫 회피
    Q: State the building name and room number of Prof. Myung's office.
    A: I do not know that information.

  턴 31 [main_interrogation] ❌ EC 반박
    Entity: 최회련
    Claim: "최회련 is an instructor at Korea University"
    Evidence: No web evidence found.
```

**③ CLI**

```
python report.py [결과JSON파일 경로]
python report.py results/  # 가장 최근 파일 자동 선택
```

---

### 4. `requirements.txt`

```
picon-eval>=0.1.3
python-dotenv>=1.0.0
```

---

## 환경 설정 가이드 (README 역할)

구현 후 `run_picon.py` 실행 방법을 `README_run.md`로 작성할 것.

```markdown
## 실행 방법

1. 의존성 설치
   pip install -r requirements.txt

2. 환경 변수 설정 (.env 파일 생성)
   OPENAI_API_KEY=sk-...
   GEMINI_API_KEY=...        # do_eval=True 시 필요
   SERPER_API_KEY=...        # EC 웹검증, 없으면 placeholder

3. 실행
   python run_picon.py

4. 결과 확인
   python report.py results/
```

---

## 구현 시 주의사항

### A. `picon.run()`의 kwargs 전달 경로

```
picon.run(**kwargs)
  → InterrogationEnv(**interviewee_kwargs)
    → GenericAgentSimulator.__init__(**kwargs)
      → self.extra_completion_kwargs = kwargs.get('completion_kwargs', {})
        → get_completion(**call_kwargs) 에 update됨
```

`completion_kwargs={"temperature": 0}` 을 `picon.run()`에 직접 넘기면  
`**kwargs`를 통해 위 경로로 자동 전달된다. 별도 패치 불필요.

### B. GEMINI_API_KEY vs GOOGLE_API_KEY

`picon-eval`은 `litellm`을 통해 Gemini를 호출한다. litellm은  
`GEMINI_API_KEY` 또는 `GOOGLE_API_KEY` 환경 변수를 모두 인식하므로  
둘 중 하나만 있으면 된다. `.env`에 `GEMINI_API_KEY`로 설정 권장.

### C. `do_eval=True`의 비용

Evaluator(Gemini-2.5-Flash)는 전체 인터뷰 히스토리를 한 번에 처리한다.  
50턴 기준 약 $0.01~0.03 수준으로 저렴하다.  
총 비용은 GPT-5/5.1 질문자 + GPT-4o 응답자 포함 세션당 약 $0.15~0.35 예상.

### D. SERPER_API_KEY 없을 때

`picon.run()`은 SERPER 키 없어도 실행되나 EC 점수가 0에 가까워진다.  
1단계에서는 `SERPER_API_KEY=placeholder`로 설정해 IC/RC만 먼저 확인하고,  
이후 Serper 키를 발급해 EC까지 측정하는 것을 권장한다.

---

## 검수 체크리스트 (구현 후 Claude가 검토할 항목)

- [ ] `persona_builder.py`가 생성한 프롬프트에 4가지 핵심 지시(회피 금지 / AI 노출 금지 / IC 보장 / RC 보장)가 모두 포함되어 있는가
- [ ] `persona_builder.py`가 생성한 프롬프트에 `entity_verification.verified_entities`의 12개 엔티티가 모두 포함되어 있는가
- [ ] `run_picon.py`가 `completion_kwargs={"temperature": 0}`을 올바르게 전달하는가
- [ ] `run_picon.py`가 `do_eval=True`로 실행되며 `result.eval_scores`가 비어있지 않은가
- [ ] `report.py`가 결과 JSON을 파싱해 IC / EC / RC 점수와 문제 턴을 출력하는가
- [ ] `.env`에 키가 없을 때 안내 메시지와 함께 종료되는가 (OPENAI_API_KEY만큼은 필수)
