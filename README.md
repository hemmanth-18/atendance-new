# AttendSmart — Supabase Edition

This project has been converted from MySQL to **Supabase (PostgreSQL)**.

---

## Step 1 — Set Up Supabase Database

1. Go to [supabase.com](https://supabase.com) and create a free account
2. Click **New Project** → give it a name and set a password
3. Wait ~2 minutes for it to spin up
4. Go to **SQL Editor** → paste the entire contents of `database.sql` → click **Run**
5. Go to **Settings → Database → Connection string → URI** → copy the URL

---

## Step 2 — Configure Environment Variables

Copy `.env.example` to `.env`:

```
cp .env.example .env
```

Edit `.env` and paste your Supabase connection URL:

```
DATABASE_URL=postgresql://postgres:[YOUR-PASSWORD]@db.xxxx.supabase.co:5432/postgres
SECRET_KEY=any_random_string_here
```

---

## Step 3 — Run Locally

```bash
pip install -r requirements.txt
python app.py
```

Visit: http://localhost:5000

---

## Step 4 — Deploy Free Forever

### Option A: Render (Recommended — no sleep on paid, free tier available)

1. Push your code to GitHub
2. Go to [render.com](https://render.com) → New Web Service → connect GitHub repo
3. Set **Build Command**: `pip install -r requirements.txt`
4. Set **Start Command**: `gunicorn app:app`
5. Add environment variables: `DATABASE_URL` and `SECRET_KEY`
6. Deploy!

### Option B: Railway

1. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
2. Add environment variables: `DATABASE_URL` and `SECRET_KEY`
3. Railway auto-detects the Procfile and deploys

### Option C: Koyeb (Free, no sleep)

1. Go to [koyeb.com](https://koyeb.com) → Create App → GitHub
2. Set run command: `gunicorn app:app`
3. Add env vars: `DATABASE_URL` and `SECRET_KEY`

---

## What Changed From MySQL Version

| MySQL | PostgreSQL/Supabase |
|---|---|
| `flask-mysqldb` + `pymysql` | `psycopg2-binary` |
| `mysql.connection.cursor()` | `psycopg2` connection pool |
| `INSERT IGNORE` | `INSERT ... ON CONFLICT DO NOTHING` |
| `ON DUPLICATE KEY UPDATE` | `ON CONFLICT (...) DO UPDATE SET` |
| `AUTO_INCREMENT` | `SERIAL` |
| `TINYINT` | `SMALLINT` |
| `ENUM(...)` | `VARCHAR + CHECK constraint` |
| `cur.lastrowid` | `RETURNING id` → `cur.fetchone()[0]` |
| `mysql.connection.commit()` | `conn.commit()` |
| `mysql.connection.rollback()` | `conn.rollback()` |

---

## Important Notes

- **Supabase free tier**: Projects pause after **7 days of inactivity** — just log into supabase.com to unpause
- **File uploads** (profile photos): Stored locally in `static/uploads/`. For production, consider using Supabase Storage or Cloudinary instead
- The `DATABASE_URL` must never be committed to GitHub — keep it only in `.env` (which is in `.gitignore`)
