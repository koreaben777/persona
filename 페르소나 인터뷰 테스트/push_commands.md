# GitHub Push 커맨드 (순서대로 실행)

## 1. 레포 디렉터리로 이동
```bash
cd /Users/june_kim/Documents/서울대학교KDT/AI응용특강/persona
```

## 2. 변경 사항 확인
```bash
git status
git diff --name-only
```

## 3. 전체 스테이징 및 커밋
```bash
git add llm_server.py app_llm.py persona_builder.py fact_sheet_beomjun.json
git add api/index.py render.yaml requirements.txt vercel.json .gitignore
git commit -m "feat: LLM-based persona server (Beomjun) for PICON evaluation

- Add llm_server.py: GPT-4o based server with persona system prompt
- Add persona_builder.py: builds system prompt from fact sheet
- Add fact_sheet_beomjun.json: persona data for PICON interview
- Add app_llm.py: Vercel entry point for new server
- Update api/index.py: switch to app_llm
- Update render.yaml: start llm_server.py, add OPENAI_API_KEY env
- Update requirements.txt: add openai, python-dotenv, bump picon-eval"
```

## 4. Push
```bash
git push origin main
```

## 5. Render 배포 확인 (push 후 약 2~3분 대기)
```bash
curl https://<your-render-url>/health
# 예상 응답: {"status": "ok", "agent": "Beomjun"}
```

---

## Render 환경변수 설정 (최초 1회)

Render 대시보드 → persona-agent 서비스 → Environment → Add Environment Variable:
- Key: `OPENAI_API_KEY`
- Value: `sk-...` (실제 키)

설정 후 Manual Deploy 또는 자동 redeploy 대기.

---

## 배포 후 로컬 스모크 테스트

```bash
# health 확인
curl https://<render-url>/health

# 단일 턴 응답 테스트
curl -s -X POST https://<render-url>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is your year of birth?"}]}' \
  | python3 -m json.tool

# 예상 응답 내 content: "2002" 포함 여부 확인
```
