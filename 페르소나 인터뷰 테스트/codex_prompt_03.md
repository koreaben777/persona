# Codex 프롬프트 #3 — GitHub Push, Render 배포, 스모크 테스트

아래 텍스트를 그대로 Codex에 붙여 넣으세요.

---

## [Codex에 붙여넣을 텍스트 시작]

You are a senior DevOps engineer. Execute the following three tasks in order for the repository at:

**Local path**: `/Users/june_kim/Documents/서울대학교KDT/AI응용특강/persona`  
**GitHub repo**: `https://github.com/irukatakashi-lab/persona`

---

## Task 1 — Git commit and push

Stage and push the following files. Do NOT stage any other files.

**New files to add:**
```
llm_server.py
app_llm.py
persona_builder.py
fact_sheet_beomjun.json
```

**Modified files to add:**
```
api/index.py
render.yaml
requirements.txt
vercel.json
.gitignore
```

Run these exact commands:
```bash
cd /Users/june_kim/Documents/서울대학교KDT/AI응용특강/persona

git add llm_server.py app_llm.py persona_builder.py fact_sheet_beomjun.json
git add api/index.py render.yaml requirements.txt vercel.json .gitignore

git commit -m "feat: LLM-based persona server (Beomjun) for PICON evaluation

- Add llm_server.py: stateless GPT-4o server, temperature=0, system prompt injected per request
- Add persona_builder.py: builds PICON-optimised system prompt from fact sheet
- Add fact_sheet_beomjun.json: verified persona data (Korea University student)
- Add app_llm.py: Vercel entry point
- Update api/index.py: switch import to app_llm
- Update render.yaml: startCommand -> llm_server.py, add OPENAI_API_KEY env
- Update requirements.txt: add openai>=1.0.0, python-dotenv>=1.0.0, bump picon-eval>=0.1.3
- Update .gitignore: exclude .env and results/"

git push origin main
```

**Success condition**: `git push` exits with code 0 and the commit appears on GitHub.  
**On failure**: Report the exact error message and stop.

---

## Task 2 — Verify Render auto-deployment

After the push, Render should automatically detect the change and redeploy.

**Step 2-1**: Wait up to **3 minutes** for Render to finish deploying.  
Check the deployment status by polling the health endpoint every 20 seconds:

```bash
for i in $(seq 1 9); do
  echo "Attempt $i / 9 — $(date)"
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://persona-jinsikkims-projects.vercel.app/health 2>/dev/null || echo "000")
  BODY=$(curl -s https://persona-jinsikkims-projects.vercel.app/health 2>/dev/null || echo "unreachable")
  echo "  HTTP $STATUS — $BODY"
  if [ "$STATUS" = "200" ]; then
    echo "✅ Deployment confirmed live"
    break
  fi
  sleep 20
done
```

> **Note on the URL**: The existing deployment URL is `https://persona-jinsikkims-projects.vercel.app`.  
> If you know a different Render URL for this service, use that instead.  
> If neither URL is known, skip the polling and proceed to Step 2-2.

**Step 2-2**: If polling never returns HTTP 200 after 9 attempts, output:
```
⚠️  Auto-deployment not confirmed. Manual check required:
    - Render dashboard: https://dashboard.render.com
    - Check that OPENAI_API_KEY environment variable is set for the service
    - Trigger manual redeploy if needed
```
Then continue to Task 3 regardless.

---

## Task 3 — Smoke test

Once the server is confirmed live (or manually deployed), run the following two curl tests against the deployment URL.

**Test A — Health check**:
```bash
curl -s https://<DEPLOYMENT_URL>/health | python3 -m json.tool
```
Expected response:
```json
{"status": "ok", "agent": "Beomjun"}
```

**Test B — Single-turn response test**:
```bash
curl -s -X POST https://<DEPLOYMENT_URL>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is your year of birth?"}]}' \
  | python3 -m json.tool
```
Expected: The `choices[0].message.content` field contains `"2002"`.

**Test C — Multi-turn consistency test**:
```bash
curl -s -X POST https://<DEPLOYMENT_URL>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "What is your year of birth?"},
      {"role": "assistant", "content": "I was born in 2002."},
      {"role": "user", "content": "And what university do you attend?"}
    ]
  }' | python3 -m json.tool
```
Expected: The response content mentions `"Korea University"` or `"고려대학교"`.

**Report format** — after all three tests, output:
```
=== Smoke Test Results ===
Deployment URL : https://...
Test A (health)         : ✅ PASS / ❌ FAIL — <actual response>
Test B (birth year)     : ✅ PASS / ❌ FAIL — <actual content>
Test C (university)     : ✅ PASS / ❌ FAIL — <actual content>

Next step: Submit this URL to PICON evaluation at https://kaist-edlab.github.io/picon/research/
```

---

## Important notes

- The deployment platform is **Render** (persistent server, not serverless). The service name in `render.yaml` is `persona-agent`.
- `OPENAI_API_KEY` must be set as an environment variable in the Render service. If it is not set, the `/v1/chat/completions` endpoint will return HTTP 500.
- Do NOT run `pip install` or modify any files — this task is push + verify only.
- If the Render URL is different from the Vercel URL shown above, use the correct Render URL for all curl tests.

## [Codex에 붙여넣을 텍스트 끝]
