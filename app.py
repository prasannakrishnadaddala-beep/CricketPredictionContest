"""
Smart Predictor League - Flask + PostgreSQL + React (Single File)
Author: Chennai / VEWIT-style architecture
"""

import os
import hmac
import hashlib
import logging
import razorpay
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import Flask, request, jsonify, render_template_string, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# ─────────────────────────── CONFIG ────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/predictor"
).replace("postgres://", "postgresql://")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

RAZORPAY_KEY_ID     = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
PLATFORM_COMMISSION = 0.18   # 18 % kept by platform

db = SQLAlchemy(app)

# ─────────────────────────── MODELS ────────────────────────────

class User(db.Model):
    __tablename__ = "users"
    id             = db.Column(db.BigInteger, primary_key=True)
    name           = db.Column(db.String(120))
    mobile         = db.Column(db.String(15), unique=True, nullable=False)
    email          = db.Column(db.String(200))
    password_hash  = db.Column(db.String(256))
    wallet_balance = db.Column(db.Numeric(10, 2), default=0)
    is_verified    = db.Column(db.Boolean, default=False)
    created_at     = db.Column(db.DateTime, default=lambda: datetime.now(IST))

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    def to_dict(self):
        return dict(id=self.id, name=self.name, mobile=self.mobile,
                    email=self.email, wallet=float(self.wallet_balance or 0))


class Contest(db.Model):
    __tablename__ = "contests"
    id          = db.Column(db.BigInteger, primary_key=True)
    title       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    entry_fee   = db.Column(db.Numeric(10, 2), nullable=False)
    prize_pool  = db.Column(db.Numeric(10, 2), default=0)
    start_time  = db.Column(db.DateTime, nullable=False)
    end_time    = db.Column(db.DateTime, nullable=False)
    status      = db.Column(db.String(20), default="upcoming")  # upcoming | live | completed
    category    = db.Column(db.String(50), default="cricket")
    max_entries = db.Column(db.Integer, default=10000)
    created_at  = db.Column(db.DateTime, default=lambda: datetime.now(IST))

    def to_dict(self):
        return dict(
            id=self.id, title=self.title, description=self.description,
            entry_fee=float(self.entry_fee), prize_pool=float(self.prize_pool),
            start_time=self.start_time.isoformat(), end_time=self.end_time.isoformat(),
            status=self.status, category=self.category, max_entries=self.max_entries,
        )


class Question(db.Model):
    __tablename__ = "questions"
    id             = db.Column(db.BigInteger, primary_key=True)
    contest_id     = db.Column(db.BigInteger, db.ForeignKey("contests.id"), nullable=False)
    question_text  = db.Column(db.Text, nullable=False)
    q_type         = db.Column(db.String(20), default="single_choice")  # single_choice | range
    options        = db.Column(db.JSON)         # ["TeamA","TeamB",...]
    correct_answer = db.Column(db.String(200))  # set after match
    points         = db.Column(db.Integer, default=50)

    def to_dict(self):
        return dict(id=self.id, contest_id=self.contest_id,
                    question_text=self.question_text, q_type=self.q_type,
                    options=self.options, points=self.points)


class Entry(db.Model):
    __tablename__ = "entries"
    id           = db.Column(db.BigInteger, primary_key=True)
    user_id      = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    contest_id   = db.Column(db.BigInteger, db.ForeignKey("contests.id"), nullable=False)
    score        = db.Column(db.Integer, default=0)
    is_paid      = db.Column(db.Boolean, default=False)
    submitted_at = db.Column(db.DateTime, default=lambda: datetime.now(IST))
    __table_args__ = (db.UniqueConstraint("user_id", "contest_id"),)


class Answer(db.Model):
    __tablename__ = "answers"
    id          = db.Column(db.BigInteger, primary_key=True)
    entry_id    = db.Column(db.BigInteger, db.ForeignKey("entries.id"), nullable=False)
    question_id = db.Column(db.BigInteger, db.ForeignKey("questions.id"), nullable=False)
    user_answer = db.Column(db.String(500))


class Payment(db.Model):
    __tablename__ = "payments"
    id                  = db.Column(db.BigInteger, primary_key=True)
    user_id             = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    contest_id          = db.Column(db.BigInteger, db.ForeignKey("contests.id"), nullable=False)
    razorpay_order_id   = db.Column(db.String(100))
    razorpay_payment_id = db.Column(db.String(100))
    status              = db.Column(db.String(20), default="pending")
    amount              = db.Column(db.Numeric(10, 2))
    created_at          = db.Column(db.DateTime, default=lambda: datetime.now(IST))


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id         = db.Column(db.BigInteger, primary_key=True)
    user_id    = db.Column(db.BigInteger)
    action     = db.Column(db.String(100))
    detail     = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(IST))


# ─────────────────────────── HELPERS ───────────────────────────

def log_audit(action, detail="", user_id=None):
    try:
        al = AuditLog(
            user_id=user_id or session.get("user_id"),
            action=action, detail=detail,
            ip_address=request.remote_addr
        )
        db.session.add(al)
        db.session.commit()
    except Exception as e:
        logger.warning("Audit log failed: %s", e)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Login required"}), 401
        return f(*args, **kwargs)
    return decorated


def compute_scores(contest_id: int):
    """Score all entries for a completed contest."""
    questions = Question.query.filter_by(contest_id=contest_id).all()
    entries   = Entry.query.filter_by(contest_id=contest_id, is_paid=True).all()

    for entry in entries:
        total = 0
        for q in questions:
            if not q.correct_answer:
                continue
            ans = Answer.query.filter_by(entry_id=entry.id, question_id=q.id).first()
            if not ans:
                continue
            if q.q_type == "single_choice":
                if ans.user_answer and ans.user_answer.strip().lower() == q.correct_answer.strip().lower():
                    total += q.points
            elif q.q_type == "range":
                # correct_answer stored as "min-max", e.g. "150-180"
                try:
                    lo, hi = map(int, q.correct_answer.split("-"))
                    val = int(ans.user_answer)
                    if lo <= val <= hi:
                        total += q.points
                    elif abs(val - (lo + hi) // 2) <= 10:
                        total += q.points // 2   # partial credit
                except Exception:
                    pass
        entry.score = total

    db.session.commit()
    logger.info("Scores computed for contest %s", contest_id)


# ─────────────────────────── AUTH ROUTES ───────────────────────

@app.route("/api/register", methods=["POST"])
def register():
    data = request.json or {}
    mobile = (data.get("mobile") or "").strip()
    name   = (data.get("name") or "").strip()
    email  = (data.get("email") or "").strip()
    pw     = data.get("password", "")

    if not mobile or not pw:
        return jsonify({"error": "Mobile and password required"}), 400
    if User.query.filter_by(mobile=mobile).first():
        return jsonify({"error": "Mobile already registered"}), 409

    u = User(name=name, mobile=mobile, email=email, is_verified=True)
    u.set_password(pw)
    db.session.add(u)
    db.session.commit()
    session["user_id"] = u.id
    log_audit("REGISTER", f"user={u.id}", user_id=u.id)
    return jsonify({"message": "Registered", "user": u.to_dict()}), 201


@app.route("/api/login", methods=["POST"])
def login():
    data   = request.json or {}
    mobile = (data.get("mobile") or "").strip()
    pw     = data.get("password", "")

    u = User.query.filter_by(mobile=mobile).first()
    if not u or not u.check_password(pw):
        log_audit("LOGIN_FAIL", f"mobile={mobile}")
        return jsonify({"error": "Invalid credentials"}), 401

    session["user_id"] = u.id
    log_audit("LOGIN", user_id=u.id)
    return jsonify({"message": "Logged in", "user": u.to_dict()})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out"})


@app.route("/api/me")
@login_required
def me():
    u = User.query.get(session["user_id"])
    return jsonify(u.to_dict())


# ─────────────────────── CONTEST ROUTES ────────────────────────

@app.route("/api/contests")
def list_contests():
    status = request.args.get("status")
    q = Contest.query
    if status:
        q = q.filter_by(status=status)
    contests = q.order_by(Contest.start_time).all()
    return jsonify([c.to_dict() for c in contests])


@app.route("/api/contests/<int:contest_id>")
def contest_detail(contest_id):
    c = Contest.query.get_or_404(contest_id)
    qs = Question.query.filter_by(contest_id=contest_id).all()
    data = c.to_dict()
    data["questions"] = [q.to_dict() for q in qs]

    # Entry count
    data["entry_count"] = Entry.query.filter_by(contest_id=contest_id, is_paid=True).count()
    return jsonify(data)


@app.route("/api/contests/<int:contest_id>/leaderboard")
def leaderboard(contest_id):
    entries = (
        db.session.query(Entry, User)
        .join(User, User.id == Entry.user_id)
        .filter(Entry.contest_id == contest_id, Entry.is_paid == True)
        .order_by(Entry.score.desc(), Entry.submitted_at.asc())
        .limit(100)
        .all()
    )
    board = []
    for rank, (e, u) in enumerate(entries, 1):
        board.append({"rank": rank, "name": u.name, "score": e.score,
                      "submitted_at": e.submitted_at.isoformat()})
    return jsonify(board)


@app.route("/api/contests/<int:contest_id>/my-score")
@login_required
def my_score(contest_id):
    e = Entry.query.filter_by(user_id=session["user_id"], contest_id=contest_id).first()
    if not e:
        return jsonify({"error": "No entry found"}), 404
    return jsonify({"score": e.score, "is_paid": e.is_paid})


# ────────────────────── PAYMENT ROUTES ─────────────────────────

@app.route("/api/payment/create-order", methods=["POST"])
@login_required
def create_order():
    data       = request.json or {}
    contest_id = data.get("contest_id")
    contest    = Contest.query.get_or_404(contest_id)

    # Check duplicate
    existing = Entry.query.filter_by(
        user_id=session["user_id"], contest_id=contest_id, is_paid=True
    ).first()
    if existing:
        return jsonify({"error": "Already joined this contest"}), 409

    amount_paise = int(float(contest.entry_fee) * 100)

    if RAZORPAY_KEY_ID:
        client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        order  = client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"spl_{contest_id}_{session['user_id']}_{int(datetime.now().timestamp())}",
            "notes": {"contest": contest.title, "skill_contest": "yes"}
        })
        rzp_order_id = order["id"]
    else:
        # Dev mode – skip real payment
        rzp_order_id = f"dev_order_{int(datetime.now().timestamp())}"

    payment = Payment(
        user_id=session["user_id"], contest_id=contest_id,
        razorpay_order_id=rzp_order_id,
        amount=contest.entry_fee, status="pending"
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({
        "order_id": rzp_order_id,
        "amount": amount_paise,
        "currency": "INR",
        "key": RAZORPAY_KEY_ID or "dev_mode",
        "contest": contest.title
    })


@app.route("/api/payment/verify", methods=["POST"])
@login_required
def verify_payment():
    data       = request.json or {}
    order_id   = data.get("razorpay_order_id")
    payment_id = data.get("razorpay_payment_id")
    signature  = data.get("razorpay_signature")
    contest_id = data.get("contest_id")

    # Dev bypass
    if not RAZORPAY_KEY_SECRET or order_id.startswith("dev_"):
        verified = True
    else:
        body     = f"{order_id}|{payment_id}"
        expected = hmac.new(
            RAZORPAY_KEY_SECRET.encode(), body.encode(), hashlib.sha256
        ).hexdigest()
        verified = hmac.compare_digest(expected, signature or "")

    if not verified:
        log_audit("PAYMENT_FAIL", f"order={order_id}")
        return jsonify({"error": "Payment verification failed"}), 400

    payment = Payment.query.filter_by(razorpay_order_id=order_id).first()
    if payment:
        payment.razorpay_payment_id = payment_id
        payment.status = "success"

    # Create / unlock entry
    entry = Entry.query.filter_by(
        user_id=session["user_id"], contest_id=contest_id
    ).first()
    if not entry:
        entry = Entry(user_id=session["user_id"], contest_id=contest_id)
        db.session.add(entry)

    entry.is_paid = True

    # Update prize pool
    contest = Contest.query.get(contest_id)
    if contest:
        contest.prize_pool = float(contest.prize_pool or 0) + float(contest.entry_fee) * (1 - PLATFORM_COMMISSION)

    db.session.commit()
    log_audit("PAYMENT_SUCCESS", f"contest={contest_id} order={order_id}")
    return jsonify({"message": "Payment verified. You can now submit predictions!"})


# ────────────────────── ANSWER ROUTES ──────────────────────────

@app.route("/api/contests/<int:contest_id>/submit", methods=["POST"])
@login_required
def submit_answers(contest_id):
    contest = Contest.query.get_or_404(contest_id)
    now     = datetime.now(IST)

    if now > contest.start_time.replace(tzinfo=IST):
        return jsonify({"error": "Submission deadline passed"}), 400

    entry = Entry.query.filter_by(
        user_id=session["user_id"], contest_id=contest_id, is_paid=True
    ).first()
    if not entry:
        return jsonify({"error": "Join the contest first"}), 403

    # Delete previous answers if re-submitting
    Answer.query.filter_by(entry_id=entry.id).delete()

    answers_data = request.json.get("answers", {})   # {question_id: answer}
    for qid, ans in answers_data.items():
        a = Answer(entry_id=entry.id, question_id=int(qid), user_answer=str(ans))
        db.session.add(a)

    entry.submitted_at = now
    db.session.commit()
    log_audit("SUBMIT_ANSWERS", f"contest={contest_id} entry={entry.id}")
    return jsonify({"message": "Predictions locked in! Good luck 🏆"})


# ────────────────────── ADMIN ROUTES ───────────────────────────
# Simple token-based admin (set ADMIN_TOKEN env var)

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "admin-secret-change-me")

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("X-Admin-Token", "")
        if token != ADMIN_TOKEN:
            return jsonify({"error": "Forbidden"}), 403
        return f(*args, **kwargs)
    return decorated


@app.route("/api/admin/contests", methods=["POST"])
@admin_required
def create_contest():
    data = request.json or {}
    c = Contest(
        title       = data["title"],
        description = data.get("description", ""),
        entry_fee   = data["entry_fee"],
        start_time  = datetime.fromisoformat(data["start_time"]),
        end_time    = datetime.fromisoformat(data["end_time"]),
        category    = data.get("category", "cricket"),
        max_entries = data.get("max_entries", 10000),
        status      = data.get("status", "upcoming"),
    )
    db.session.add(c)
    db.session.flush()

    for q in data.get("questions", []):
        qu = Question(
            contest_id    = c.id,
            question_text = q["question_text"],
            q_type        = q.get("q_type", "single_choice"),
            options       = q.get("options", []),
            points        = q.get("points", 50),
        )
        db.session.add(qu)

    db.session.commit()
    return jsonify({"message": "Contest created", "id": c.id}), 201


@app.route("/api/admin/contests/<int:contest_id>/set-answers", methods=["POST"])
@admin_required
def set_answers(contest_id):
    """Set correct answers and trigger scoring."""
    data = request.json or {}   # {question_id: correct_answer}
    for qid, ans in data.items():
        q = Question.query.get(int(qid))
        if q and q.contest_id == contest_id:
            q.correct_answer = str(ans)

    contest = Contest.query.get_or_404(contest_id)
    contest.status = "completed"
    db.session.commit()

    compute_scores(contest_id)
    return jsonify({"message": "Answers set and scores computed"})


@app.route("/api/admin/contests/<int:contest_id>/status", methods=["PATCH"])
@admin_required
def update_status(contest_id):
    c = Contest.query.get_or_404(contest_id)
    c.status = request.json.get("status", c.status)
    db.session.commit()
    return jsonify({"message": "Status updated"})


# ─────────────────────── FRONTEND (SPA) ────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Smart Predictor League</title>
<meta name="description" content="Skill-based prediction contests. Predict cricket, sports & tech outcomes. Win real prizes."/>
<script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<style>
  :root{
    --bg:#0d0f1a;--card:#161928;--accent:#6c63ff;--accent2:#ff6584;
    --text:#e8eaf6;--muted:#8892b0;--green:#00e676;--yellow:#ffd740;--red:#ff5252;
    --border:rgba(255,255,255,0.07);--radius:14px;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:'Segoe UI',sans-serif;min-height:100vh}
  a{color:var(--accent);text-decoration:none}
  button{cursor:pointer;border:none;outline:none}
  input,select,textarea{background:#1e2235;border:1px solid var(--border);color:var(--text);
    border-radius:8px;padding:10px 14px;font-size:14px;width:100%}
  input:focus,select:focus{border-color:var(--accent);outline:none}

  /* NAV */
  nav{background:#111327;border-bottom:1px solid var(--border);padding:0 24px;
      display:flex;align-items:center;justify-content:space-between;height:60px;
      position:sticky;top:0;z-index:100}
  .logo{font-size:20px;font-weight:800;background:linear-gradient(135deg,var(--accent),var(--accent2));
        -webkit-background-clip:text;-webkit-text-fill-color:transparent}
  .nav-links{display:flex;gap:12px;align-items:center}
  .btn{padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;transition:all .2s}
  .btn-primary{background:var(--accent);color:#fff}
  .btn-primary:hover{background:#5a54d4}
  .btn-ghost{background:transparent;color:var(--muted);border:1px solid var(--border)}
  .btn-ghost:hover{border-color:var(--accent);color:var(--accent)}
  .btn-danger{background:var(--red);color:#fff}
  .btn-success{background:var(--green);color:#000}
  .btn-lg{padding:12px 28px;font-size:15px;border-radius:10px}

  /* LAYOUT */
  .container{max-width:1100px;margin:0 auto;padding:32px 20px}
  .grid-3{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px}

  /* CARD */
  .card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:24px;
        transition:transform .2s,box-shadow .2s}
  .card:hover{transform:translateY(-3px);box-shadow:0 8px 32px rgba(108,99,255,.15)}

  /* BADGE */
  .badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700;
         text-transform:uppercase;letter-spacing:.5px}
  .badge-live{background:rgba(0,230,118,.15);color:var(--green)}
  .badge-upcoming{background:rgba(255,215,64,.15);color:var(--yellow)}
  .badge-completed{background:rgba(136,146,176,.15);color:var(--muted)}

  /* PRIZE */
  .prize-bar{background:linear-gradient(135deg,#1a1040,#1a2040);border:1px solid rgba(108,99,255,.3);
             border-radius:10px;padding:14px 18px;margin:12px 0;display:flex;justify-content:space-between;align-items:center}
  .prize-amount{font-size:22px;font-weight:800;color:var(--yellow)}

  /* FORM */
  .form-group{margin-bottom:16px}
  .form-group label{display:block;font-size:13px;color:var(--muted);margin-bottom:6px;font-weight:600}

  /* OPTION BUTTONS */
  .option-btn{display:block;width:100%;text-align:left;padding:12px 16px;margin:6px 0;
               background:#1e2235;border:1px solid var(--border);border-radius:8px;
               color:var(--text);font-size:14px;transition:all .2s}
  .option-btn.selected{border-color:var(--accent);background:rgba(108,99,255,.15);color:var(--accent)}
  .option-btn:hover:not(.selected){border-color:rgba(108,99,255,.4)}

  /* LEADERBOARD */
  table{width:100%;border-collapse:collapse}
  th,td{padding:12px 16px;text-align:left;border-bottom:1px solid var(--border);font-size:14px}
  th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.5px}
  tr:hover td{background:rgba(255,255,255,.02)}
  .rank-1{color:var(--yellow);font-weight:800}
  .rank-2{color:#c0c0c0;font-weight:700}
  .rank-3{color:#cd7f32;font-weight:700}

  /* TOAST */
  #toast{position:fixed;bottom:24px;right:24px;z-index:9999;display:flex;flex-direction:column;gap:8px}
  .toast-item{padding:12px 20px;border-radius:10px;font-size:14px;font-weight:600;
              animation:slideIn .3s ease;color:#fff;min-width:260px}
  .toast-success{background:rgba(0,230,118,.9)}
  .toast-error{background:rgba(255,82,82,.9)}
  .toast-info{background:rgba(108,99,255,.9)}
  @keyframes slideIn{from{transform:translateX(120%);opacity:0}to{transform:none;opacity:1}}

  /* MODAL */
  .modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:500;
             display:flex;align-items:center;justify-content:center;padding:20px}
  .modal{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
         padding:32px;width:100%;max-width:460px;max-height:90vh;overflow-y:auto}

  /* HERO */
  .hero{text-align:center;padding:60px 20px 40px;
        background:radial-gradient(ellipse at 50% 0%,rgba(108,99,255,.15),transparent 70%)}
  .hero h1{font-size:42px;font-weight:900;line-height:1.1;margin-bottom:16px}
  .hero p{color:var(--muted);font-size:16px;max-width:540px;margin:0 auto 28px}

  /* STAT PILLS */
  .stats{display:flex;gap:12px;justify-content:center;flex-wrap:wrap;margin-bottom:36px}
  .stat-pill{background:var(--card);border:1px solid var(--border);border-radius:999px;
             padding:8px 18px;font-size:13px;font-weight:600}

  /* PROGRESS */
  .progress{height:6px;background:rgba(255,255,255,.07);border-radius:3px;overflow:hidden;margin:10px 0}
  .progress-fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:3px}

  /* WALLET */
  .wallet-chip{background:rgba(0,230,118,.1);border:1px solid rgba(0,230,118,.3);
               border-radius:8px;padding:6px 14px;font-size:13px;color:var(--green);font-weight:700}

  /* RESPONSIVE */
  @media(max-width:600px){
    .hero h1{font-size:28px}
    .grid-3{grid-template-columns:1fr}
    nav{padding:0 12px}
  }
</style>
</head>
<body>
<div id="root"></div>
<div id="toast"></div>

<script type="text/babel">
const {useState, useEffect, useCallback} = React;

/* ─── TOAST ─────────────────────────────────────────────── */
function showToast(msg, type="info"){
  const el = document.createElement("div");
  el.className = `toast-item toast-${type}`;
  el.textContent = msg;
  document.getElementById("toast").appendChild(el);
  setTimeout(()=>el.remove(), 3500);
}

/* ─── API ────────────────────────────────────────────────── */
async function api(path, opts={}){
  const res = await fetch(path, {
    headers:{"Content-Type":"application/json",...(opts.headers||{})},
    credentials:"include",
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined
  });
  const data = await res.json();
  if(!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

/* ─── COUNTDOWN ─────────────────────────────────────────── */
function Countdown({target}){
  const [left,setLeft] = useState("");
  useEffect(()=>{
    const tick=()=>{
      const diff = new Date(target)-new Date();
      if(diff<=0){setLeft("Started");return}
      const h=Math.floor(diff/3600000), m=Math.floor((diff%3600000)/60000), s=Math.floor((diff%60000)/1000);
      setLeft(`${h}h ${m}m ${s}s`);
    };
    tick(); const id=setInterval(tick,1000); return()=>clearInterval(id);
  },[target]);
  return <span style={{fontWeight:700,color:"var(--yellow)"}}>{left}</span>;
}

/* ─── NAV ────────────────────────────────────────────────── */
function Nav({user, setPage, onLogout}){
  return (
    <nav>
      <div className="logo" onClick={()=>setPage("home")} style={{cursor:"pointer"}}>
        🏆 Predictor League
      </div>
      <div className="nav-links">
        {user ? <>
          <span className="wallet-chip">₹{Number(user.wallet||0).toFixed(2)}</span>
          <span style={{fontSize:13,color:"var(--muted)"}}>Hi, {user.name||user.mobile}</span>
          <button className="btn btn-ghost" onClick={onLogout}>Logout</button>
        </> : <>
          <button className="btn btn-ghost" onClick={()=>setPage("login")}>Login</button>
          <button className="btn btn-primary" onClick={()=>setPage("register")}>Join Free</button>
        </>}
      </div>
    </nav>
  );
}

/* ─── HOME ───────────────────────────────────────────────── */
function Home({user, setPage, setSelectedContest}){
  const [contests, setContests] = useState([]);
  const [filter, setFilter] = useState("all");

  useEffect(()=>{
    api("/api/contests").then(d=>setContests(d)).catch(()=>{});
  },[]);

  const filtered = filter==="all" ? contests : contests.filter(c=>c.status===filter);

  return (
    <div>
      <div className="hero">
        <h1>Predict. Compete.<br/>Win Real Prizes 🏆</h1>
        <p>India's skill-based prediction contest platform. Use your cricket knowledge to outrank thousands and win big.</p>
        <div className="stats">
          <div className="stat-pill">⚡ Skill-Based Only</div>
          <div className="stat-pill">🏏 Cricket &amp; More</div>
          <div className="stat-pill">💰 Entry from ₹49</div>
          <div className="stat-pill">✅ 100% Legal</div>
        </div>
        {!user && <button className="btn btn-primary btn-lg" onClick={()=>setPage("register")}>Start Predicting →</button>}
      </div>

      <div className="container">
        <div style={{display:"flex",gap:10,marginBottom:24,flexWrap:"wrap"}}>
          {["all","upcoming","live","completed"].map(s=>(
            <button key={s} className={`btn ${filter===s?"btn-primary":"btn-ghost"}`}
              onClick={()=>setFilter(s)} style={{textTransform:"capitalize"}}>{s}</button>
          ))}
        </div>

        {filtered.length===0 && <div style={{textAlign:"center",padding:60,color:"var(--muted)"}}>No contests found</div>}

        <div className="grid-3">
          {filtered.map(c=>(
            <ContestCard key={c.id} contest={c} user={user}
              onJoin={()=>{setSelectedContest(c);setPage("contest")}}/>
          ))}
        </div>
      </div>
    </div>
  );
}

function ContestCard({contest,user,onJoin}){
  const filled = Math.min(100, (contest.entry_count||0) / contest.max_entries * 100);
  return (
    <div className="card" onClick={onJoin} style={{cursor:"pointer"}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:14}}>
        <span className={`badge badge-${contest.status}`}>{contest.status}</span>
        <span style={{fontSize:12,color:"var(--muted)",textTransform:"capitalize"}}>{contest.category}</span>
      </div>
      <div style={{fontWeight:700,fontSize:18,marginBottom:8,lineHeight:1.3}}>{contest.title}</div>
      <div className="prize-bar">
        <div>
          <div style={{fontSize:11,color:"var(--muted)",marginBottom:2}}>PRIZE POOL</div>
          <div className="prize-amount">₹{Number(contest.prize_pool||0).toLocaleString("en-IN")}</div>
        </div>
        <div style={{textAlign:"right"}}>
          <div style={{fontSize:11,color:"var(--muted)",marginBottom:2}}>ENTRY</div>
          <div style={{fontWeight:800,color:"var(--accent)",fontSize:18}}>₹{contest.entry_fee}</div>
        </div>
      </div>
      <div style={{fontSize:12,color:"var(--muted)",marginBottom:6}}>
        {contest.status==="upcoming" ? <>Starts in: <Countdown target={contest.start_time}/></> : null}
      </div>
      <div className="progress"><div className="progress-fill" style={{width:`${filled}%`}}/></div>
      <div style={{fontSize:11,color:"var(--muted)",marginTop:4}}>{contest.entry_count||0} / {contest.max_entries} spots filled</div>
    </div>
  );
}

/* ─── CONTEST DETAIL ─────────────────────────────────────── */
function ContestDetail({contest:initial, user, setPage}){
  const [contest, setContest] = useState(initial);
  const [answers, setAnswers] = useState({});
  const [loading, setLoading] = useState(false);
  const [joined, setJoined] = useState(false);

  useEffect(()=>{
    api(`/api/contests/${initial.id}`).then(setContest).catch(()=>{});
    if(user) api(`/api/contests/${initial.id}/my-score`)
      .then(d=>{ if(d.is_paid) setJoined(true); }).catch(()=>{});
  },[initial.id, user]);

  async function handleJoin(){
    if(!user){setPage("login");return}
    setLoading(true);
    try{
      const order = await api("/api/payment/create-order",{method:"POST",body:{contest_id:contest.id}});

      if(order.key==="dev_mode"){
        // Dev mode: skip Razorpay
        await api("/api/payment/verify",{method:"POST",body:{
          razorpay_order_id: order.order_id,
          razorpay_payment_id:"dev_pay",
          razorpay_signature:"dev_sig",
          contest_id: contest.id
        }});
        setJoined(true);
        showToast("Joined! Now submit your predictions.","success");
      } else {
        const rzp = new window.Razorpay({
          key: order.key,
          amount: order.amount,
          currency: "INR",
          order_id: order.order_id,
          name: "Predictor League",
          description: order.contest,
          theme:{color:"#6c63ff"},
          handler: async function(resp){
            await api("/api/payment/verify",{method:"POST",body:{
              ...resp, contest_id: contest.id
            }});
            setJoined(true);
            showToast("Payment successful! Submit your predictions.","success");
          }
        });
        rzp.open();
      }
    }catch(e){showToast(e.message,"error")}
    setLoading(false);
  }

  async function handleSubmit(){
    if(Object.keys(answers).length < (contest.questions||[]).length){
      showToast("Please answer all questions","error"); return;
    }
    setLoading(true);
    try{
      const r = await api(`/api/contests/${contest.id}/submit`,{method:"POST",body:{answers}});
      showToast(r.message,"success");
    }catch(e){showToast(e.message,"error")}
    setLoading(false);
  }

  return (
    <div className="container">
      <button className="btn btn-ghost" onClick={()=>setPage("home")} style={{marginBottom:20}}>← Back</button>

      <div style={{display:"grid",gridTemplateColumns:"1fr 340px",gap:24,alignItems:"start"}}>
        <div>
          <div className="card" style={{marginBottom:20}}>
            <div style={{display:"flex",gap:10,alignItems:"center",marginBottom:14}}>
              <span className={`badge badge-${contest.status}`}>{contest.status}</span>
              <span style={{fontSize:12,color:"var(--muted)"}}>{contest.category}</span>
            </div>
            <h2 style={{fontSize:24,fontWeight:800,marginBottom:12}}>{contest.title}</h2>
            <p style={{color:"var(--muted)",marginBottom:16}}>{contest.description}</p>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:14}}>
              {[
                ["Entry Fee","₹"+contest.entry_fee,"var(--accent)"],
                ["Prize Pool","₹"+(Number(contest.prize_pool||0).toLocaleString("en-IN")),"var(--yellow)"],
                ["Spots Left",(contest.max_entries-(contest.entry_count||0)).toLocaleString(),"var(--green)"]
              ].map(([l,v,c])=>(
                <div key={l} style={{textAlign:"center",background:"rgba(255,255,255,.03)",borderRadius:10,padding:"14px 10px"}}>
                  <div style={{fontSize:10,color:"var(--muted)",marginBottom:4,textTransform:"uppercase",letterSpacing:1}}>{l}</div>
                  <div style={{fontSize:20,fontWeight:800,color:c}}>{v}</div>
                </div>
              ))}
            </div>
          </div>

          {/* PREDICTION FORM */}
          {joined && contest.questions && contest.status==="upcoming" && (
            <div className="card">
              <h3 style={{marginBottom:20,fontWeight:700}}>📝 Your Predictions</h3>
              {contest.questions.map((q,i)=>(
                <div key={q.id} style={{marginBottom:24}}>
                  <div style={{fontWeight:600,marginBottom:8,fontSize:15}}>
                    Q{i+1}. {q.question_text}
                    <span style={{float:"right",fontSize:12,color:"var(--accent)",background:"rgba(108,99,255,.1)",
                      padding:"2px 8px",borderRadius:999}}>{q.points} pts</span>
                  </div>
                  {q.q_type==="single_choice" && (q.options||[]).map(opt=>(
                    <button key={opt} className={`option-btn ${answers[q.id]===opt?"selected":""}`}
                      onClick={()=>setAnswers(a=>({...a,[q.id]:opt}))}>{opt}</button>
                  ))}
                  {q.q_type==="range" && (
                    <input type="number" placeholder="Enter your number"
                      value={answers[q.id]||""} onChange={e=>setAnswers(a=>({...a,[q.id]:e.target.value}))}/>
                  )}
                </div>
              ))}
              <button className="btn btn-primary btn-lg" style={{width:"100%"}} onClick={handleSubmit} disabled={loading}>
                {loading?"Submitting...":"🔒 Lock My Predictions"}
              </button>
            </div>
          )}

          {contest.status==="completed" && <Leaderboard contestId={contest.id}/>}
        </div>

        {/* SIDEBAR */}
        <div>
          <div className="card" style={{position:"sticky",top:80}}>
            <div style={{textAlign:"center",padding:"10px 0 20px"}}>
              <div style={{fontSize:40,marginBottom:8}}>🏆</div>
              <div style={{fontSize:28,fontWeight:900,color:"var(--yellow)"}}>
                ₹{Number(contest.prize_pool||0).toLocaleString("en-IN")}
              </div>
              <div style={{color:"var(--muted)",fontSize:13}}>Total Prize Pool</div>
            </div>

            {!joined ? (
              <button className="btn btn-primary btn-lg" style={{width:"100%"}} onClick={handleJoin} disabled={loading}>
                {loading?"Processing...":"🎮 Join for ₹"+contest.entry_fee}
              </button>
            ) : contest.status==="upcoming" ? (
              <div style={{textAlign:"center",padding:14,background:"rgba(0,230,118,.1)",
                borderRadius:10,color:"var(--green)",fontWeight:700}}>✅ You're In!</div>
            ) : null}

            <div style={{marginTop:20,fontSize:12,color:"var(--muted)",lineHeight:1.7}}>
              <div>🛡️ 100% skill-based contest</div>
              <div>⚡ Instant UPI payments</div>
              <div>🏅 Winners paid within 24hrs</div>
              <div>📜 Legal under Indian law</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── LEADERBOARD ────────────────────────────────────────── */
function Leaderboard({contestId}){
  const [board, setBoard] = useState([]);
  useEffect(()=>{
    api(`/api/contests/${contestId}/leaderboard`).then(setBoard).catch(()=>{});
  },[contestId]);

  return (
    <div className="card">
      <h3 style={{marginBottom:20,fontWeight:700}}>🏅 Leaderboard</h3>
      <table>
        <thead><tr><th>#</th><th>Player</th><th>Score</th></tr></thead>
        <tbody>
          {board.map(r=>(
            <tr key={r.rank}>
              <td className={r.rank<=3?`rank-${r.rank}`:""}>{r.rank<=3?"🥇🥈🥉"[r.rank-1]:r.rank}</td>
              <td>{r.name}</td>
              <td style={{fontWeight:700,color:"var(--accent)"}}>{r.score}</td>
            </tr>
          ))}
          {board.length===0 && <tr><td colSpan={3} style={{textAlign:"center",color:"var(--muted)",padding:30}}>Results coming soon</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

/* ─── AUTH ───────────────────────────────────────────────── */
function AuthPage({mode, setPage, setUser}){
  const [form, setForm] = useState({name:"",mobile:"",email:"",password:""});
  const [loading, setLoading] = useState(false);
  const isReg = mode==="register";

  async function submit(){
    setLoading(true);
    try{
      const path = isReg ? "/api/register" : "/api/login";
      const d = await api(path,{method:"POST",body:form});
      setUser(d.user);
      showToast(isReg?"Welcome aboard!":"Welcome back!","success");
      setPage("home");
    }catch(e){showToast(e.message,"error")}
    setLoading(false);
  }

  return (
    <div style={{display:"flex",alignItems:"center",justifyContent:"center",minHeight:"80vh",padding:20}}>
      <div className="card" style={{width:"100%",maxWidth:420}}>
        <h2 style={{fontWeight:800,marginBottom:6}}>{isReg?"Create Account":"Welcome Back"}</h2>
        <p style={{color:"var(--muted)",marginBottom:24,fontSize:14}}>
          {isReg?"Join India's skill-based prediction contest":"Login to your account"}
        </p>
        {isReg && <>
          <div className="form-group"><label>Full Name</label>
            <input placeholder="Rahul Sharma" value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></div>
          <div className="form-group"><label>Email</label>
            <input placeholder="rahul@email.com" value={form.email} onChange={e=>setForm({...form,email:e.target.value})}/></div>
        </>}
        <div className="form-group"><label>Mobile Number</label>
          <input placeholder="9876543210" value={form.mobile} onChange={e=>setForm({...form,mobile:e.target.value})}/></div>
        <div className="form-group"><label>Password</label>
          <input type="password" placeholder="••••••••" value={form.password} onChange={e=>setForm({...form,password:e.target.value})}/></div>
        <button className="btn btn-primary btn-lg" style={{width:"100%",marginBottom:16}} onClick={submit} disabled={loading}>
          {loading?"Please wait...":(isReg?"Create Account →":"Login →")}
        </button>
        <div style={{textAlign:"center",fontSize:13,color:"var(--muted)"}}>
          {isReg?"Already have an account?":"Don't have an account?"}{" "}
          <a onClick={()=>setPage(isReg?"login":"register")} style={{cursor:"pointer"}}>{isReg?"Login":"Register"}</a>
        </div>
        {isReg && <div style={{marginTop:16,fontSize:11,color:"var(--muted)",textAlign:"center",lineHeight:1.6}}>
          By registering, you agree that this is a skill-based prediction contest and winners are determined by performance, not chance.
        </div>}
      </div>
    </div>
  );
}

/* ─── APP ────────────────────────────────────────────────── */
function App(){
  const [page, setPage] = useState("home");
  const [user, setUser] = useState(null);
  const [selectedContest, setSelectedContest] = useState(null);

  useEffect(()=>{
    api("/api/me").then(setUser).catch(()=>{});
  },[]);

  async function logout(){
    await api("/api/logout",{method:"POST"}).catch(()=>{});
    setUser(null); setPage("home");
    showToast("Logged out","info");
  }

  return (
    <>
      <Nav user={user} setPage={setPage} onLogout={logout}/>
      {page==="home"    && <Home user={user} setPage={setPage} setSelectedContest={setSelectedContest}/>}
      {page==="contest" && selectedContest && <ContestDetail contest={selectedContest} user={user} setPage={setPage}/>}
      {page==="login"   && <AuthPage mode="login" setPage={setPage} setUser={setUser}/>}
      {page==="register"&& <AuthPage mode="register" setPage={setPage} setUser={setUser}/>}
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

# ─────────────────────────── INIT DB ───────────────────────────

def seed_sample_data():
    """Insert one sample contest so the app isn't empty on first launch."""
    if Contest.query.count() > 0:
        return
    now = datetime.now(IST)
    c = Contest(
        title       = "IPL Mega Predictor – Win Big! 🏏",
        description = "Predict the outcome of today's IPL match. Show off your cricket knowledge and win prizes!",
        entry_fee   = 99,
        start_time  = now + timedelta(hours=2),
        end_time    = now + timedelta(hours=8),
        status      = "upcoming",
        category    = "cricket",
        max_entries = 5000,
    )
    db.session.add(c)
    db.session.flush()

    questions = [
        Question(contest_id=c.id, question_text="Who will win the match?",
                 q_type="single_choice", options=["Mumbai Indians","Chennai Super Kings"], points=50),
        Question(contest_id=c.id, question_text="Who will be the top run-scorer?",
                 q_type="single_choice",
                 options=["Rohit Sharma","MS Dhoni","Virat Kohli","Hardik Pandya"], points=70),
        Question(contest_id=c.id, question_text="Total runs scored (predict the number)?",
                 q_type="range", options=[], points=40),
        Question(contest_id=c.id, question_text="Total wickets fallen (predict the number)?",
                 q_type="range", options=[], points=40),
        Question(contest_id=c.id, question_text="Who will win the toss?",
                 q_type="single_choice", options=["Mumbai Indians","Chennai Super Kings"], points=20),
    ]
    for q in questions:
        db.session.add(q)
    db.session.commit()
    logger.info("Sample contest seeded.")


with app.app_context():
    db.create_all()
    seed_sample_data()

# ────────────────────────── ENTRY POINT ────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
