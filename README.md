# MealSnap — AI Smart Nutrition Assistant

MealSnap is a full-stack app that uses receipt OCR, a nutrition database, and meal planning to help users track and improve their diet. Upload receipt photos, review and adjust items, get nutrition analysis, and generate weekly meal plans.

## Features

- **Receipt OCR** — Upload receipt images (JPG/PNG); extract and filter food items
- **Nutrition analysis** — Match items to a food database, compute macros, and flag gaps
- **Meal planning** — Generate 7-day meal plans from confirmed items
- **Dashboard** — Weight and nutrition history, purchase suggestions
- **Auth** — Signup/login with JWT; user-scoped data

## Prerequisites

- **Python 3.10+** (backend: FastAPI, EasyOCR, OpenCV, SQLAlchemy)
- **Node.js 18+** and npm (frontend: React)

## Quick start (after clone)

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
```

**Optional:** Copy `backend/.env.example` to `backend/.env` and set `JWT_SECRET_KEY` for production. For local dev, defaults are used.

From the `backend` directory:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Or: `python main.py`

- DB file `mealsnap.db` and `uploads/` are created automatically on first run.
- EasyOCR may download models on first receipt upload.

### 2. Frontend

```bash
cd frontend
npm install
```

**Optional:** Copy `frontend/.env.example` to `frontend/.env` and set `REACT_APP_API_URL` if the API is not at `http://localhost:8000`.

```bash
npm start
```

Frontend runs at [http://localhost:3000](http://localhost:3000).

## Project layout

```
├── backend/           # FastAPI, OCR, nutrition logic
│   ├── db/            # SQLAlchemy models, DB init
│   ├── meal_plan/     # Meal planning rules and planner
│   ├── ocr/           # EasyOCR-based text extraction
│   ├── utils/         # Food matching, nutrition, image preprocessing
│   ├── main.py        # API entrypoint
│   └── requirements.txt
├── data/
│   └── nutrition_database.csv   # Food names, aliases, macros (required)
├── frontend/          # React app
│   └── src/
└── README.md
```

## Environment variables

| Variable | Where | Purpose |
|----------|-------|---------|
| `JWT_SECRET_KEY` | backend | Signing key for JWTs. **Set in production.** |
| `DATABASE_URL` | backend | DB URL. Default: `sqlite:///./mealsnap.db` |
| `REACT_APP_API_URL` | frontend | API base URL. Default: `http://localhost:8000` |

Use `backend/.env.example` and `frontend/.env.example` as templates. Do not commit `.env` files.

## Not in the repo (see .gitignore)

- `.env` and other secret files
- `backend/mealsnap.db`, `backend/uploads/`, `backend/processed/`
- `frontend/node_modules/`, `frontend/build/`
- Python `__pycache__/`, `venv/`, `.venv/`

**If any of these were already committed,** remove from tracking with  
`git rm -r --cached backend/mealsnap.db backend/uploads backend/processed` and  
`git rm --cached .env backend/.env frontend/.env` (as applicable), then commit.

## API

- **Base URL:** `http://localhost:8000`
- **Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health:** `GET /health`

## License

MIT (or your preferred license).
