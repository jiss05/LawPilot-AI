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

**Current stage:** Initial project structure and development environment foundation.

Frontend and backend project skeletons have been initialized. Further implementation of AI agents, orchestration, database integration, document ingestion, and RAG functionality will be carried out in subsequent development tasks.
