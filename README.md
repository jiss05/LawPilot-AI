# LawPilot AI – Multi-Agent AI Legal Support System

## 1. Project Overview

LawPilot AI is a multi-agent AI-powered legal support system designed to assist users with legal information and document-related queries through specialized AI agents.

The system uses a modular architecture to organize frontend development, backend services, AI agent workflows, document ingestion, and retrieval-augmented generation (RAG).

## 2. Technology Stack

| Component            | Technology      |
| -------------------- | --------------- |
| Frontend             | React.js, Vite  |
| Backend              | Python, FastAPI |
| AI Orchestration     | LangGraph       |
| Large Language Model | Ollama, Qwen    |
| Database             | PostgreSQL      |
| Vector Database      | Qdrant          |
| Containerization     | Docker          |

## 3. Project Structure

```text
LawPilot-AI/
│
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   │   ├── client/
│   │   │   ├── lawyer/
│   │   │   └── judge_support/
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   ├── ingestion/
│   │   ├── models/
│   │   ├── orchestration/
│   │   ├── rag/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── main.py
│   ├── tests/
│   └── requirements.txt
│
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── assets/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── pages/
│   │   ├── routes/
│   │   ├── services/
│   │   ├── App.jsx
│   │   ├── App.css
│   │   ├── index.css
│   │   └── main.jsx
│   └── package.json
│
├── docs/
├── infra/
├── scripts/
├── .env.example
├── .gitignore
└── README.md
```

## 4. Prerequisites

Install the following before running the application:

- Python
- Node.js and npm
- Docker Desktop (for infrastructure services when configured)
- Git

## 5. Backend Setup

Navigate to the backend directory:

```bash
cd backend
```

Create and activate a Python virtual environment:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the FastAPI development server:

```bash
uvicorn app.main:app --reload
```

Backend URL: http://127.0.0.1:8000/

API documentation: http://127.0.0.1:8000/docs

### Run the whole backend stack with Docker (recommended)

From the repository root (Docker Desktop running):

```bash
cp backend/.env.example backend/.env     # then set JWT_SECRET_KEY and the email settings
docker compose up -d --build             # postgres + qdrant + backend
docker compose logs -f backend           # watch migrations, then uploads being processed
```

- API docs: http://localhost:8000/docs
- Readiness: http://localhost:8000/api/v1/health/ready (database, migration, Qdrant)
- The backend container applies migrations (`alembic upgrade head`) and seeds roles on start.
- The first upload downloads the OCR and embedding models (a few minutes) into the `model_cache` volume.

To run only the databases and start the backend yourself with `uvicorn`:

```bash
docker compose up -d postgres qdrant
cd backend && alembic upgrade head && uvicorn app.main:app --reload
```

Create the first administrator with `python scripts/create_admin.py` (from `backend/`).

### Tests

```bash
cd backend
pytest                                   # unit tests, no database needed
# + integration tests against the Docker Postgres (rolled back, leave no data):
TEST_DATABASE_URL=postgresql+psycopg://legal_ai_user:local_dev_password@localhost:5432/legal_ai pytest
# end-to-end check of a running backend (upload -> process -> search -> audit):
python scripts/smoke_test.py --email <admin email> --password <admin password>
```

## 6. Frontend Setup

Open another terminal and navigate to the frontend directory:

```bash
cd frontend
```

Install dependencies:

```bash
npm install
```

Start the development server:

```bash
npm run dev
```

Frontend URL: http://localhost:5173/

## 7. Environment Configuration

The root `.env.example` file provides a template for environment variables used by the application.

Create local environment configuration files as required by individual services.

Never commit actual credentials, passwords, or API keys to version control.

## 8. Development Guidelines

- Keep frontend and backend responsibilities separate.
- Develop application modules independently.
- Follow the established project folder structure.
- Keep reusable frontend components in the components directory.
- Organize backend functionality into appropriate modules.
- Use Git branches for individual development tasks.
- Update documentation when introducing significant changes.

## 9. Project Status

**Current stage:** Sprint 2 complete: centralized knowledge base and retrieval.

| Area | Status | Details |
|---|---|---|
| Authentication and roles (CLIENT, LAWYER, JUDGE, ADMIN) | Done | `backend/app/api/auth_routes.py` |
| Legal source registry and upload (admin only) | Done | `POST /api/v1/knowledge-sources` |
| Text extraction and OCR (PDF, DOCX, TXT, scans) | Done | [`backend/app/ingestion/README.md`](backend/app/ingestion/README.md) |
| Cleaning and legal-structure-aware chunking | Done (SCRUM-14) | same README |
| Embeddings and Qdrant indexing | Done (SCRUM-15) | same README |
| Hybrid retrieval (Qdrant + PostgreSQL full-text, RRF) | Done (SCRUM-16) | [`backend/app/rag/README.md`](backend/app/rag/README.md), `POST /api/v1/research/search` |
| Source versioning, ingestion monitoring, audit trail | Done (SCRUM-18) | `/api/v1/knowledge-sources/{id}/versions`, `/api/v1/admin/*` |
| Docker integration, health checks, smoke test | Done (SCRUM-33) | `docker-compose.yml`, `backend/Dockerfile`, `backend/scripts/smoke_test.py` |
| Ollama/Qwen gateway, agents, frontend screens | Next sprints | BRD phases 3-7 |

Uploading a document starts a background pipeline: extraction → chunking → indexing → activation. When it finishes, the document is searchable.
