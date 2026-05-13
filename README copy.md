# Stock Analyst Pro — Vercel + Firebase Edition

A full-stack stock analysis platform for NSE, US, MCX & Crypto markets.

## Stack
- **Frontend**: Flask + Jinja2 templates
- **Backend**: Python Flask (serverless on Vercel)
- **Database**: Firebase Firestore (replaces SQLite)
- **Auth**: Flask-Login with Firestore user storage
- **Scheduler**: Vercel Cron Jobs (replaces APScheduler)
- **Deployment**: Vercel

---

## Local Development (macOS)

### 1. Clone and set up
```bash
git clone https://github.com/YOUR_USERNAME/stock-platform.git
cd stock-platform
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Add your Firebase service account
- Go to Firebase Console → Project Settings → Service Accounts
- Click "Generate new private key"
- Save it as `firebase-service-account.json` in the project root
- **This file is in .gitignore — it will never be committed**

### 3. Create a `.env` file (also gitignored)
```
SECRET_KEY=your-super-secret-key-here
DEFAULT_USER=admin
DEFAULT_PASS=yourpassword
```

### 4. Run locally
```bash
python app.py
```
Open http://localhost:5000

---

## Deploy to Vercel

### One-time setup
```bash
npm install -g vercel
vercel login
```

### Set environment variables in Vercel dashboard
Go to: vercel.com → Your Project → Settings → Environment Variables

| Variable | Value |
|---|---|
| `SECRET_KEY` | A long random string |
| `FIREBASE_SERVICE_ACCOUNT` | Paste the **entire content** of your `firebase-service-account.json` |
| `DEFAULT_USER` | `admin` |
| `DEFAULT_PASS` | Your secure password |

### Deploy
```bash
vercel --prod
```

---

## Firebase Setup

1. Go to [console.firebase.google.com](https://console.firebase.google.com)
2. Create a project
3. Enable:
   - **Firestore Database** (production mode)
   - **Authentication** → Email/Password (optional, not required for this app)
4. Go to Project Settings → Service Accounts → Generate new private key
5. Use that JSON as described above

### Firestore Security Rules
In Firebase Console → Firestore → Rules, set:
```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Only server-side access (Admin SDK bypasses these rules)
    match /{document=**} {
      allow read, write: if false;
    }
  }
}
```
Since we use the Admin SDK server-side, client-side rules don't matter — but locking them down is good practice.

---

## Architecture

```
stock_platform/
├── api/
│   └── index.py          ← Vercel entry point
├── modules/
│   ├── firebase_db.py    ← Firestore database layer (replaces database.py)
│   ├── scheduler_tasks.py← Cron logic (replaces scheduler.py + APScheduler)
│   ├── paper_trade.py    ← Updated to use firebase_db
│   ├── data_fetcher.py   ← Unchanged
│   ├── analyzer.py       ← Unchanged
│   ├── recommender.py    ← Unchanged
│   ├── ml_engine.py      ← Unchanged
│   ├── news_engine.py    ← Unchanged
│   └── reports.py        ← Unchanged
├── templates/            ← Unchanged
├── static/               ← Unchanged
├── app.py                ← Updated (Firebase auth, cron routes)
├── config.py             ← Updated (no SQLite path)
├── requirements.txt      ← Updated (firebase-admin added)
├── vercel.json           ← NEW
└── .gitignore            ← NEW (blocks secrets)
```
