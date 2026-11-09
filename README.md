# UniBuddy — Campus AI Assistant & Query Management

UniBuddy is an intelligent university platform that connects students, faculty, campus authority, and management through verified AI-powered responses and seamless query lifecycle management.

---

## 🚀 Quick Start

### 1. Run Frontend & API Proxy (Node.js)
```bash
npm start
# or: node server.js
```
The application will be available at [http://localhost:3000](http://localhost:3000).

`server.js` automatically proxies all `/api/*` calls directly to the FastAPI backend at `http://127.0.0.1:8000`.

### 2. Run Backend (FastAPI + Python 3.12)
```bash
# Activate virtual environment
source backend/.venv/bin/activate

# Run backend API server
python -m uvicorn app.main:app --app-dir backend --port 8000
```
Backend health check: [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health).

---

## 🔑 Authentication

### 1. Google Authentication
- **Primary Authentication Method**: Google Identity Services (GIS).
- Click **"Continue with Google"** on the login screen.
- The browser exchanges the Google ID token with `POST /api/v1/auth/google`, receives an 8-hour UniBuddy session token, and loads the user's role-specific profile via `GET /api/v1/auth/me`.
- If a Google-verified user has no profile yet (403 `no_profile`), the frontend offers a one-click student access request (`POST /api/v1/auth/google/access-request`).
- **Supabase Authentication**: Completely removed from both backend and frontend.

### 2. Email-Based Role Authentication & Demo Accounts
For rapid prototype testing, the application identifies user workspaces automatically by matching registered university email addresses:

| Role | Demo Email | Universal Password | Workspace Capabilities |
| :--- | :--- | :--- | :--- |
| **Student** | `student@unibuddy.demo` | `UniBuddy@123` | AI RAG Chat Assistant, ticket submissions, dashboard, announcements |
| **Faculty** | `faculty@unibuddy.demo` | `UniBuddy@123` | Ticket management queue, document uploads, reply & resolution |
| **Authority** | `authority@unibuddy.demo` | `UniBuddy@123` | University-wide oversight, departmental escalations, documents |
| **Management** | `management@unibuddy.demo` | `UniBuddy@123` | Institutional operations, volume metrics, query analytics |

*Note: Clicking "Use Demo Account" on the login page autofills credentials and logs directly into the corresponding portal in one step.*

---

## 🧩 Architectural Highlights

- **Frontend (`index.html`)**: Beautiful Fraunces serif + Inter sans-serif design, soft lavender/ice surfaces, navy typography, centered login card, role portals, RAG chat with grounded document citations, ticket tracking, and document management.
- **Backend (`backend/`)**: FastAPI application featuring Neon PostgreSQL, Cloudflare R2 object storage for PDFs, Google Gemini AI embeddings & chat, and session authentication.
- **Full Test Coverage**: 240+ automated tests passing in `backend/tests/` (`backend/.venv/bin/pytest backend/tests`).
- **Graceful Fallbacks**: When backend cloud services (Neon, Gemini, R2) are not yet connected, the frontend provides intelligent local fallbacks with full interactivity.
