# Persona Agent Submission Notes

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Run Server

```bash
.venv/bin/python template_server.py --fact-sheet data/persona_worker.json --host 0.0.0.0 --port 8001 --name PersonaAgent
```

## Health Check

```bash
curl http://127.0.0.1:8001/health
```

## Demo Endpoint Format

Use `http://<host>:<port>/v1` as the OpenAI-compatible `api_base`.
Example chat completions endpoint: `http://127.0.0.1:8001/v1/chat/completions`

## Stable Deploy on Vercel

This repo can deploy to Vercel without Render.

1. Put this folder in a public Git repository.
2. Import the repository into Vercel.
3. If the app is under a subfolder, set the project Root Directory to persona.
4. Vercel will use app.py as the ASGI entrypoint and keep the existing /health and /v1/chat/completions routes.
5. After deploy, use https://<your-vercel-domain>/v1 as the PICon endpoint.

## Stable Deploy on Render

This repo includes `render.yaml` for a single web service deployment.

1. Put this folder in a public Git repository.
2. In Render, create a new Blueprint and point it at that repository.
   If the repository keeps this app under a subfolder, select that Blueprint file path explicitly.
   Example for `https://github.com/irukatakashi-lab/-` with this app under `persona/`:
   - repo: `https://github.com/irukatakashi-lab/-`
   - branch: `main`
   - Blueprint file: `persona/render.yaml`
3. Render will use:
   - build command: `pip install -r requirements.txt`
   - start command: `python template_server.py --fact-sheet data/persona_worker.json --host 0.0.0.0 --port $PORT --name PersonaAgent`
4. After deploy, use `https://<your-render-domain>/v1` as the PICon endpoint.

## Evaluation Note

`picon.run(api_base=..., do_eval=False)` passes locally.
`do_eval=True` can fail even when the agent works correctly, because the default PICON evaluator path may call Gemini-backed evaluation components. In that case, an additional valid Gemini/Google evaluator API key is required; an OpenAI key alone is not always sufficient.
