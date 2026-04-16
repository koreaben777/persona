## 실행 방법

1. 의존성 설치
   ```bash
   pip install -r requirements.txt
   ```

2. 환경 변수 설정 (`.env` 파일 생성)
   ```dotenv
   OPENAI_API_KEY=sk-...
   GEMINI_API_KEY=...        # do_eval=True 시 필요 (또는 GOOGLE_API_KEY)
   SERPER_API_KEY=...        # EC 웹검증, 없으면 placeholder 사용
   ```

3. 실행
   ```bash
   python run_picon.py
   ```
   추가 옵션:
   ```bash
   python run_picon.py --model gpt-4o --turns 50 --sessions 1 --seed 42
   python run_picon.py --no-eval
   ```

4. 결과 확인
   ```bash
   python report.py results/
   ```
   특정 파일 지정:
   ```bash
   python report.py results/<result_file>.json
   ```
