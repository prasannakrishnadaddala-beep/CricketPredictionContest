# 🏆 Smart Predictor League

A **skill-based prediction contest platform** (Dream11-style) built with Flask + PostgreSQL + React.  
Legal in India under the "game of skill" category.

---

## 🚀 Quick Deploy (GitHub + Railway)

### Prerequisites
```bash
# Install GitHub CLI
https://cli.github.com/

# Install Railway CLI
npm install -g @railway/cli
# OR
curl -fsSL https://railway.app/install.sh | sh
```

### One-command deploy
```bash
python deploy.py --github-user YOUR_GITHUB_USERNAME --repo smart-predictor-league
```

This will:
1. Init a Git repo
2. Create a public GitHub repo
3. Push all code
4. Log you into Railway and deploy

---

## ⚙️ Manual Setup

### 1. Clone / setup
```bash
git clone https://github.com/YOUR_USERNAME/smart-predictor-league
cd smart-predictor-league
pip install -r requirements.txt
cp .env.example .env   # fill in your values
```

### 2. Run locally
```bash
python app.py
# Open http://localhost:5000
```

### 3. Deploy to Railway

1. Go to https://railway.app → **New Project** → **Deploy from GitHub Repo**
2. Select your repo
3. Click **+ New Service** → **PostgreSQL** (Railway auto-sets `DATABASE_URL`)
4. Go to your Flask service → **Variables** → add:

| Variable | Value |
|---|---|
| `SECRET_KEY` | Random long string |
| `RAZORPAY_KEY_ID` | From Razorpay dashboard |
| `RAZORPAY_KEY_SECRET` | From Razorpay dashboard |
| `ADMIN_TOKEN` | Your secret admin password |

5. Railway auto-deploys on every `git push`

---

## 🎮 How It Works

| Step | What Happens |
|---|---|
| User registers | Mobile + password (no OTP needed for MVP) |
| Picks a contest | Sees entry fee, prize pool, countdown |
| Pays via Razorpay | UPI / cards / netbanking |
| Submits predictions | Locked before match starts |
| Admin sets answers | Via CLI or API after match |
| Scores computed | Points assigned per correct prediction |
| Leaderboard updates | Top scorer wins prize |

---

## 🔌 Admin CLI

```bash
# List all contests
python admin_cli.py list-contests --base-url https://YOUR-APP.railway.app --token YOUR_ADMIN_TOKEN

# Create a new contest (interactive)
python admin_cli.py create-contest --base-url https://YOUR-APP.railway.app --token YOUR_ADMIN_TOKEN

# Set correct answers after match (triggers scoring)
python admin_cli.py set-answers --contest-id 1 --base-url https://YOUR-APP.railway.app --token YOUR_ADMIN_TOKEN
```

---

## 🔌 Key API Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/register` | — | Register user |
| POST | `/api/login` | — | Login |
| GET | `/api/contests` | — | List contests |
| GET | `/api/contests/:id` | — | Contest + questions |
| POST | `/api/payment/create-order` | User | Create Razorpay order |
| POST | `/api/payment/verify` | User | Verify payment |
| POST | `/api/contests/:id/submit` | User | Submit predictions |
| GET | `/api/contests/:id/leaderboard` | — | Leaderboard |
| POST | `/api/admin/contests` | Admin | Create contest |
| POST | `/api/admin/contests/:id/set-answers` | Admin | Set answers + score |

---

## 💰 Revenue Model

- Platform keeps **18%** of every entry fee
- Rest goes into prize pool
- 5,000 users × ₹99 = ₹4,95,000 pool → you keep ~₹89,100 per contest

---

## ⚖️ Legal Compliance

- Winners decided by **skill (accuracy + knowledge)**, not chance
- Compliant with *Varun Gumber vs UT Chandigarh* ruling
- Terms of Service must include: *"This is a skill-based contest. Winners are determined based on performance and not by chance."*
- **Avoid** words: betting, gambling, lucky draw, lottery

---

## 🏗️ Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python / Flask |
| Database | PostgreSQL (Railway managed) |
| Frontend | React 18 (inline, no build step) |
| Payments | Razorpay |
| Hosting | Railway.app |
| ORM | Flask-SQLAlchemy |
