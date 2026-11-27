# LawPilot AI – Setup Guide

This guide takes a fresh Windows or Linux machine to a running LawPilot with all four roles.
It takes about 30 minutes, most of it downloading models.

## 1. Install

| Tool | Version | Why |
| --- | --- | --- |
| Python | 3.10 or newer | Backend |
| Node.js | 20 or newer, with npm | Frontend |
| Docker Desktop | current | PostgreSQL and Qdrant |
| Ollama | current | Runs the Qwen model locally |
| Git | current | |

## 2. Get the code and the model

```bash
git clone https://github.com/jiss05/LawPilot-AI.git
cd LawPilot-AI
ollama pull qwen2.5:7b-instruct
```

## 3. Start the databases

```bash
docker compose up -d postgres qdrant
```

PostgreSQL listens on 5432 and Qdrant on 6333 (dashboard: http://localhost:6333/dashboard).
To run the backend in Docker too, use `docker compose up -d --build` and skip step 4's `uvicorn`.

## 4. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows   (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # Linux/macOS: cp .env.example .env
```

Edit `backend/.env`: set `JWT_SECRET_KEY` (required) and the email settings for OTP codes.
Every setting is explained in `CONFIGURATION.md`.

```bash
alembic upgrade head              # create or update the database tables
python scripts/create_admin.py    # first administrator account
uvicorn app.main:app --port 8000
```

Check it: http://localhost:8000/api/v1/health/ready must say `ready`, and
http://localhost:8000/api/v1/health/llm must report the model as available.
Interactive API docs: http://localhost:8000/docs.

## 5. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Register users for each role (an OTP code is emailed), or sign in
as the admin created above.

## 6. Load legal sources

Sign in as the admin, open **Legal Sources**, and upload Acts and judgments (PDF). Progress is
shown in **Monitoring → Ingestion**. The first upload downloads the OCR and embedding models,
which takes a few minutes. A document is searchable when its version is active.

To load a core set of 18 central Acts (BNS, BNSS, BSA, DPDP, Consumer Protection, IT, NI, CPC, Limitation,
Specific Relief, Transfer of Property, Arbitration, Hindu Marriage, Hindu Succession, Domestic Violence,
POSH, POCSO, RTI) from India Code in one go, run from `backend/`:

```bash
python scripts/import_laws.py --list     # what is missing
python scripts/import_laws.py            # download, chunk, embed and index them
```

The list of Acts is `backend/scripts/law_manifest.json`; add an entry to import another Act.

## 7. Try each role

| Role | Where | Try |
| --- | --- | --- |
| Client | `/client` | Ask a plain legal question; check the sources and the verified badges. |
| Lawyer | `/lawyer`, `/lawyer/drafts` | Research a question; create a matter, add a second lawyer as reviewer, generate a draft, submit it. |
| Lawyer (reviewer) | `/lawyer/drafts` | Approve or send back the submitted draft; the author can then download it. |
| Judge | `/judge` | **Load example case** and prepare a neutral brief; chat with the Judge Support Assistant. |
| Admin | `/admin/monitoring` | Ingestion status, source versions and indexing, evaluation runs, user feedback. |

On the demo PC, `start_demo.bat` starts the backend and frontend and opens these pages.

## 8. Run the tests

```bash
cd backend
pytest                                   # 464 tests, no database needed
TEST_DATABASE_URL=postgresql+psycopg://legal_ai_user:local_dev_password@localhost:5432/legal_ai pytest
python scripts/smoke_test.py --email <admin email> --password <admin password>
python scripts/evaluate_model.py         # model evaluation, a few minutes on CPU
cd ../frontend && npm run lint && npm run build
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Backend stops with `JWT_SECRET_KEY Field required` | Add `JWT_SECRET_KEY` to `backend/.env`. |
| `/health/ready` says the migration is behind | Run `alembic upgrade head`. |
| Answers say the AI assistant is temporarily unavailable | Start Ollama (`ollama serve`) and check `LLM_OLLAMA_BASE_URL`. |
| Answers say the knowledge base could not be searched | Start Qdrant (`docker compose up -d qdrant`). |
| Frontend shows "server could not be reached" | Backend not running, or `VITE_API_BASE_URL` points elsewhere. |
| Browser blocks requests (CORS) | Run the frontend on port 5170–5179, or change the CORS rule (see `CONFIGURATION.md`). |
| Git shows every file as changed (WSL/Linux shell on a Windows checkout) | Line endings only: run git with `-c core.autocrlf=true`. |
