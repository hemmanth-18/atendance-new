import os
import math
import time
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta, datetime
import pymysql
import pymysql.cursors
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'attendsmart3_secret_2024')

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# MySQL connection
def get_db():
    return pymysql.connect(
        host=os.environ.get('MYSQL_HOST', 'localhost'),
        port=int(os.environ.get('MYSQL_PORT', 3306)),
        user=os.environ.get('MYSQL_USER', 'root'),
        password=os.environ.get('MYSQL_PASSWORD', 'qwe123'),
        database=os.environ.get('MYSQL_DATABASE', 'atten'),
        cursorclass=pymysql.cursors.Cursor,
        autocommit=False,
        charset='utf8mb4'
    )

def release_db(conn):
    try:
        conn.close()
    except Exception:
        pass

def get_cursor():
    conn = get_db()
    cur = conn.cursor()
    return conn, cur

DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
SLOT_TIMES = ['8:00 AM', '9:00 AM', '10:00 AM', '11:00 AM', '12:00 PM',
              '1:00 PM',  '2:00 PM',  '3:00 PM',  '4:00 PM',  '5:00 PM']

def get_user(user_id):
    conn, cur = get_cursor()
    try:
        cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
        user = cur.fetchone()
    finally:
        cur.close(); release_db(conn)
    return user

def validate_session():
    if 'user_id' not in session:
        return None
    user = get_user(session['user_id'])
    if not user:
        session.clear()
        return None
    return user

def get_active_semester_id(user_id):
    conn, cur = get_cursor()
    try:
        cur.execute("SELECT id FROM semesters WHERE user_id=%s AND is_active=1 ORDER BY id DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
    finally:
        cur.close(); release_db(conn)
    return row[0] if row else None

def get_subjects(user_id):
    conn, cur = get_cursor()
    try:
        sem_id = get_active_semester_id(user_id)
        if sem_id:
            cur.execute("SELECT id, subject_name FROM subjects WHERE user_id=%s AND semester_id=%s ORDER BY subject_name", (user_id, sem_id))
        else:
            cur.execute("SELECT id, subject_name FROM subjects WHERE user_id=%s AND semester_id IS NULL ORDER BY subject_name", (user_id,))
        rows = cur.fetchall()
    finally:
        cur.close(); release_db(conn)
    return rows

def get_day_timetable(user_id, day_of_week):
    conn, cur = get_cursor()
    try:
        sem_id = get_active_semester_id(user_id)
        if sem_id:
            cur.execute("""SELECT t.id, t.period_number, t.slot_label, t.is_free,
                       t.subject_id, COALESCE(s.subject_name,'Free Hour')
                FROM timetable t LEFT JOIN subjects s ON t.subject_id=s.id
                WHERE t.user_id=%s AND t.day_of_week=%s AND t.semester_id=%s ORDER BY t.period_number""",
                (user_id, day_of_week, sem_id))
        else:
            cur.execute("""SELECT t.id, t.period_number, t.slot_label, t.is_free,
                       t.subject_id, COALESCE(s.subject_name,'Free Hour')
                FROM timetable t LEFT JOIN subjects s ON t.subject_id=s.id
                WHERE t.user_id=%s AND t.day_of_week=%s AND t.semester_id IS NULL ORDER BY t.period_number""",
                (user_id, day_of_week))
        rows = cur.fetchall()
    finally:
        cur.close(); release_db(conn)
    return rows

def count_class_dates(start_date, end_date, day_of_week):
    count = 0
    current = start_date
    while current <= end_date:
        if current.weekday() == day_of_week:
            count += 1
        current += timedelta(days=1)
    return count

def predict(attended, total_held, future_classes):
    total_at_end = total_held + future_classes
    if total_at_end == 0:
        return {"current_pct": 0, "risk": "NO DATA", "can_miss": 0,
                "need_to_attend": 0, "best_possible_pct": 0,
                "message": "No classes scheduled.", "total_at_end": 0, "min_needed_at_end": 0}
    current_pct = min(100.0, round(attended / total_held * 100, 1)) if total_held > 0 else 0
    best_possible_pct = round((attended + future_classes) / total_at_end * 100, 1)
    min_needed_at_end = math.ceil(0.75 * total_at_end)
    need_to_attend = max(0, min_needed_at_end - attended)
    can_miss = future_classes - need_to_attend
    if future_classes == 0:
        risk = "SAFE" if current_pct >= 75 else "DANGER"
        message = f" Semester complete! Final: {current_pct}%"
    elif best_possible_pct < 75:
        risk = "DANGER"
        message = f" Cannot reach 75%. Best possible: {best_possible_pct}%."
    elif can_miss <= 0:
        risk = "HIGH"
        message = f"Must attend ALL {future_classes} remaining!"
    elif can_miss <= 2:
        risk = "HIGH"
        message = f" Only {can_miss} miss(es) allowed."
    elif can_miss <= 5:
        risk = "MEDIUM"
        message = f" Can miss {can_miss} more."
    else:
        risk = "SAFE"
        message = f" Safe! Can miss up to {can_miss} more."
    return {"current_pct": current_pct, "risk": risk, "can_miss": max(0, can_miss),
            "need_to_attend": need_to_attend, "best_possible_pct": best_possible_pct,
            "message": message, "total_at_end": total_at_end, "min_needed_at_end": min_needed_at_end}

@app.route('/')
def home():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']; email = request.form['email']
        password = generate_password_hash(request.form['password'])
        total_sems = int(request.form.get('total_semesters', 8))
        semester = int(request.form.get('semester', 1)); branch = request.form['branch']
        sem_start = request.form['semester_start']; sem_end = request.form['semester_end']
        if not sem_start or not sem_end:
            flash('Please fill in semester dates!', 'error')
            return render_template('register.html')
        conn, cur = get_cursor()
        try:
            cur.execute("""INSERT INTO users (name,email,password,semester,branch,semester_start,semester_end,total_semesters)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", (name,email,password,semester,branch,sem_start,sem_end,total_sems))
            user_id = cur.lastrowid
            cur.execute("""INSERT INTO semesters (user_id,semester_number,semester_label,branch,sem_start,sem_end,is_active)
                VALUES (%s,%s,%s,%s,%s,%s,1)""", (user_id,semester,f"Sem {semester}",branch,sem_start,sem_end))
            conn.commit()
            flash('Registered! Please login.', 'success')
            return redirect(url_for('login'))
        except:
            conn.rollback()
            flash('Email already exists or invalid data.', 'error')
        finally:
            cur.close(); release_db(conn)
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']; password = request.form['password']
        conn, cur = get_cursor()
        try:
            cur.execute("SELECT * FROM users WHERE email=%s", (email,))
            user = cur.fetchone()
        finally:
            cur.close(); release_db(conn)
        if user and check_password_hash(user[3], password):
            session['user_id'] = user[0]; session['user_name'] = user[1]
            try:
                conn2, cur2 = get_cursor()
                cur2.execute("SELECT photo FROM users WHERE id=%s", (user[0],))
                pr = cur2.fetchone()
                session['user_photo'] = pr[0] if pr and pr[0] else None
                cur2.close(); release_db(conn2)
            except: session['user_photo'] = None
            if not user[8]: return redirect(url_for('setup_step1'))
            return redirect(url_for('dashboard'))
        flash('Invalid credentials!', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

@app.route('/setup/step1', methods=['GET', 'POST'])
def setup_step1():
    user = validate_session()
    if not user: return redirect(url_for('login'))
    user_id = user[0]
    if request.method == 'POST':
        conn, cur = get_cursor()
        try:
            sem_id = get_active_semester_id(user_id)
            if sem_id: cur.execute("DELETE FROM day_config WHERE user_id=%s AND semester_id=%s", (user_id, sem_id))
            else: cur.execute("DELETE FROM day_config WHERE user_id=%s AND semester_id IS NULL", (user_id,))
            for day_idx in range(6):
                has_class = request.form.get(f'has_class_{day_idx}', '0')
                total_periods = request.form.get(f'periods_{day_idx}', '0')
                if has_class == '1' and int(total_periods) > 0:
                    cur.execute("INSERT INTO day_config (user_id,day_of_week,total_periods,has_classes,semester_id) VALUES (%s,%s,%s,1,%s)",
                                (user_id, day_idx, int(total_periods), sem_id))
            conn.commit()
        finally: cur.close(); release_db(conn)
        return redirect(url_for('setup_step2'))
    return render_template('setup_step1.html', days=DAY_NAMES)

@app.route('/setup/step2', methods=['GET', 'POST'])
def setup_step2():
    user = validate_session()
    if not user: return redirect(url_for('login'))
    user_id = user[0]
    if request.method == 'POST':
        conn, cur = get_cursor()
        try:
            sem_id = get_active_semester_id(user_id)
            if sem_id: cur.execute("DELETE FROM subjects WHERE user_id=%s AND semester_id=%s", (user_id, sem_id))
            else: cur.execute("DELETE FROM subjects WHERE user_id=%s AND semester_id IS NULL", (user_id,))
            conn.commit()
            names = [n.strip() for n in request.form.getlist('subject_name') if n.strip()]
            for name in names:
                cur.execute("INSERT INTO subjects (user_id,subject_name,semester_id) VALUES (%s,%s,%s)", (user_id, name, sem_id))
            conn.commit()
        finally: cur.close(); release_db(conn)
        return redirect(url_for('setup_step3'))
    return render_template('setup_step2.html')

@app.route('/setup/step3', methods=['GET', 'POST'])
def setup_step3():
    user = validate_session()
    if not user: return redirect(url_for('login'))
    user_id = user[0]
    conn, cur = get_cursor()
    try:
        if request.method == 'POST':
            sem_id = get_active_semester_id(user_id)
            if sem_id:
                cur.execute("DELETE FROM timetable WHERE user_id=%s AND semester_id=%s", (user_id, sem_id))
                cur.execute("SELECT day_of_week, total_periods FROM day_config WHERE user_id=%s AND has_classes=1 AND semester_id=%s", (user_id, sem_id))
                day_configs = {r[0]: r[1] for r in cur.fetchall()}
                cur.execute("SELECT id, subject_name FROM subjects WHERE user_id=%s AND semester_id=%s", (user_id, sem_id))
            else:
                cur.execute("DELETE FROM timetable WHERE user_id=%s AND semester_id IS NULL", (user_id,))
                cur.execute("SELECT day_of_week, total_periods FROM day_config WHERE user_id=%s AND has_classes=1 AND semester_id IS NULL", (user_id,))
                day_configs = {r[0]: r[1] for r in cur.fetchall()}
                cur.execute("SELECT id, subject_name FROM subjects WHERE user_id=%s AND semester_id IS NULL", (user_id,))
            subj_map = {r[1]: r[0] for r in cur.fetchall()}
            for day_idx, total_periods in day_configs.items():
                for period in range(1, total_periods + 1):
                    slot_time = SLOT_TIMES[period-1] if period <= len(SLOT_TIMES) else f"Period {period}"
                    val = request.form.get(f"slot_{day_idx}_{period}", '').strip()
                    if val == 'FREE':
                        cur.execute("INSERT INTO timetable (user_id,subject_id,day_of_week,period_number,slot_label,is_free,semester_id) VALUES (%s,NULL,%s,%s,%s,1,%s)",
                                    (user_id, day_idx, period, slot_time, sem_id))
                    elif val and val in subj_map:
                        cur.execute("INSERT INTO timetable (user_id,subject_id,day_of_week,period_number,slot_label,is_free,semester_id) VALUES (%s,%s,%s,%s,%s,0,%s)",
                                    (user_id, subj_map[val], day_idx, period, slot_time, sem_id))
            cur.execute("UPDATE users SET setup_done=1 WHERE id=%s", (user_id,))
            conn.commit()
        else:
            sem_id = get_active_semester_id(user_id)
            if sem_id:
                cur.execute("SELECT day_of_week, total_periods FROM day_config WHERE user_id=%s AND has_classes=1 AND semester_id=%s ORDER BY day_of_week", (user_id, sem_id))
                day_configs = cur.fetchall()
                cur.execute("SELECT id, subject_name FROM subjects WHERE user_id=%s AND semester_id=%s ORDER BY subject_name", (user_id, sem_id))
            else:
                cur.execute("SELECT day_of_week, total_periods FROM day_config WHERE user_id=%s AND has_classes=1 AND semester_id IS NULL ORDER BY day_of_week", (user_id,))
                day_configs = cur.fetchall()
                cur.execute("SELECT id, subject_name FROM subjects WHERE user_id=%s AND semester_id IS NULL ORDER BY subject_name", (user_id,))
            subjects = cur.fetchall()
            return render_template('setup_step3.html', day_configs=day_configs, subjects=subjects, day_names=DAY_NAMES, slot_times=SLOT_TIMES)
    finally:
        cur.close(); release_db(conn)
    flash('Timetable saved! You are all set.', 'success')
    return redirect(url_for('dashboard'))

def get_active_semester(user_id):
    conn, cur = get_cursor()
    try:
        cur.execute("SELECT * FROM semesters WHERE user_id=%s AND is_active=1 ORDER BY id DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
    finally:
        cur.close(); release_db(conn)
    return row

@app.route('/dashboard')
def dashboard():
    user = validate_session()
    if not user: return redirect(url_for('login'))
    user_id = user[0]
    if not user[8]: return redirect(url_for('setup_step1'))
    _active_sem = get_active_semester(user_id)
    sem_start = _active_sem[5] if _active_sem else user[6]
    sem_end = _active_sem[6] if _active_sem else user[7]
    today = date.today()
    conn, cur = get_cursor()
    try:
        cur.execute("SELECT id FROM daily_submissions WHERE user_id=%s AND submission_date=%s", (user_id, today))
        today_submitted = cur.fetchone()
        is_saturday = today.weekday() == 5
        if is_saturday:
            cur.execute("SELECT COUNT(*) FROM saturday_slots WHERE user_id=%s AND sat_date=%s", (user_id, today))
            today_class_count = cur.fetchone()[0]
            if today_class_count == 0:
                cur.execute("SELECT is_working, total_periods FROM saturday_config WHERE user_id=%s AND sat_date=%s", (user_id, today))
                sat_cfg = cur.fetchone()
                today_class_count = sat_cfg[1] if sat_cfg and sat_cfg[0] == 1 else -1
        else:
            sem_id = get_active_semester_id(user_id)
            if sem_id: cur.execute("SELECT COUNT(*) FROM timetable WHERE user_id=%s AND day_of_week=%s AND semester_id=%s", (user_id, today.weekday(), sem_id))
            else: cur.execute("SELECT COUNT(*) FROM timetable WHERE user_id=%s AND day_of_week=%s", (user_id, today.weekday()))
            today_class_count = cur.fetchone()[0]
        subjects = get_subjects(user_id)
        results = []
        sem_id_val = get_active_semester_id(user_id)
        for subj in subjects:
            subj_id = subj[0]
            cur.execute("""SELECT COUNT(*) FROM attendance WHERE user_id=%s AND status='present'
                AND ((subject_id=%s AND is_free_hour=0) OR (free_subject_id=%s AND is_free_hour=1))
                AND class_date BETWEEN %s AND %s""", (user_id, subj_id, subj_id, sem_start, today))
            attended = cur.fetchone()[0]
            cur.execute("""SELECT COUNT(*) FROM attendance WHERE user_id=%s
                AND ((subject_id=%s AND is_free_hour=0) OR (free_subject_id=%s AND is_free_hour=1))
                AND class_date BETWEEN %s AND %s""", (user_id, subj_id, subj_id, sem_start, today))
            total_held = cur.fetchone()[0]
            grand_total = 0
            if sem_id_val:
                cur.execute("SELECT day_of_week, COUNT(*) FROM timetable WHERE user_id=%s AND subject_id=%s AND semester_id=%s AND is_free=0 GROUP BY day_of_week",
                            (user_id, subj_id, sem_id_val))
            else:
                cur.execute("SELECT day_of_week, COUNT(*) FROM timetable WHERE user_id=%s AND subject_id=%s AND is_free=0 GROUP BY day_of_week", (user_id, subj_id))
            for row in cur.fetchall():
                grand_total += count_class_dates(sem_start, sem_end, row[0]) * row[1]
            future_classes = max(0, grand_total - total_held)
            pred = predict(attended, total_held, future_classes)
            results.append({"id": subj_id, "name": subj[1], "attended": attended,
                            "total_held": total_held, "grand_total": grand_total,
                            "future_classes": future_classes, "prediction": pred})
        danger = sum(1 for r in results if r['prediction']['risk'] == 'DANGER')
        high   = sum(1 for r in results if r['prediction']['risk'] == 'HIGH')
        safe   = sum(1 for r in results if r['prediction']['risk'] == 'SAFE')
        cur.execute("SELECT submission_date FROM daily_submissions WHERE user_id=%s AND submission_date BETWEEN %s AND %s", (user_id, sem_start, today))
        submitted_dates = {row[0] for row in cur.fetchall()}
        sem_id = get_active_semester_id(user_id)
        if sem_id: cur.execute("SELECT DISTINCT day_of_week FROM timetable WHERE user_id=%s AND semester_id=%s", (user_id, sem_id))
        else: cur.execute("SELECT DISTINCT day_of_week FROM timetable WHERE user_id=%s", (user_id,))
        tt_days = {row[0] for row in cur.fetchall()}
        cur.execute("SELECT sat_date FROM saturday_config WHERE user_id=%s AND is_working=1 AND sat_date BETWEEN %s AND %s", (user_id, sem_start, today))
        working_saturdays = {row[0] for row in cur.fetchall()}
        pending_count = 0
        d = sem_start
        while d < today:
            dow = d.weekday()
            if dow == 6: d += timedelta(days=1); continue
            if d not in submitted_dates:
                if dow == 5: pending_count += 1
                elif dow in tt_days: pending_count += 1
            d += timedelta(days=1)
    finally:
        cur.close(); release_db(conn)
    is_sunday = today.weekday() == 6
    if is_saturday:
        has_pending = not today_submitted and sem_start <= today <= sem_end
        show_saturday_prompt = today_class_count == -1 and not today_submitted
    else:
        has_pending = today_class_count > 0 and not today_submitted
        show_saturday_prompt = False
    show_reminder = False if is_sunday else has_pending
    return render_template('dashboard.html', user=user, results=results, today=today,
        today_class_count=today_class_count, today_submitted=today_submitted,
        show_reminder=show_reminder, show_saturday_prompt=show_saturday_prompt,
        is_saturday=is_saturday, danger=danger, high=high, safe=safe, pending_count=pending_count)

@app.route('/mark', methods=['GET', 'POST'])
def mark_attendance():
    user = validate_session()
    if not user: return redirect(url_for('login'))
    user_id = user[0]
    subjects = get_subjects(user_id)
    subjects_dict = {s[0]: s[1] for s in subjects}
    mark_date_str = request.args.get('date', date.today().isoformat())
    mark_date = date.fromisoformat(mark_date_str)
    day_of_week = mark_date.weekday()
    day_name = DAY_NAMES[day_of_week] if day_of_week < 6 else 'Sunday'
    is_saturday = (day_of_week == 5)
    conn, cur = get_cursor()
    try:
        cur.execute("SELECT id FROM daily_submissions WHERE user_id=%s AND submission_date=%s", (user_id, mark_date))
        already_submitted = cur.fetchone()
        force_edit = request.args.get('edit') == '1'
        if force_edit and already_submitted: already_submitted = None
        slots = get_day_timetable(user_id, day_of_week)
        if not slots:
            flash(f'No classes scheduled on {day_name}!', 'error')
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            action = request.form.get('action', 'save')
            if action == 'holiday':
                cur.execute("DELETE FROM attendance WHERE user_id=%s AND class_date=%s AND timetable_id > 0", (user_id, mark_date))
                cur.execute("INSERT IGNORE INTO daily_submissions (user_id,submission_date) VALUES (%s,%s)", (user_id, mark_date))
                conn.commit()
                flash(f'{mark_date.strftime("%A, %d %b %Y")} marked as Holiday 🏖️', 'success')
                return redirect(url_for('dashboard'))
            cur.execute("DELETE FROM attendance WHERE user_id=%s AND class_date=%s AND timetable_id > 0", (user_id, mark_date))
            for slot in slots:
                tt_id = slot[0]; is_free = slot[3]; original_subj_id = slot[4]
                status = request.form.get(f'status_{tt_id}', 'absent')
                if is_free:
                    free_subj_id = request.form.get(f'free_subject_{tt_id}', None)
                    skip = request.form.get(f'skip_free_{tt_id}', '0')
                    if skip == '1' or not free_subj_id: continue
                    free_subj_id = int(free_subj_id)
                    cur.execute("INSERT INTO attendance (user_id,subject_id,timetable_id,class_date,status,is_free_hour,free_subject_id) VALUES (%s,%s,%s,%s,%s,1,%s)",
                                (user_id, free_subj_id, tt_id, mark_date, status, free_subj_id))
                else:
                    sub_val = request.form.get(f'sub_subject_{tt_id}', '')
                    actual_subj_id = int(sub_val) if sub_val else original_subj_id
                    sub_record = actual_subj_id if actual_subj_id != original_subj_id else None
                    cur.execute("INSERT INTO attendance (user_id,subject_id,timetable_id,class_date,status,is_free_hour,free_subject_id) VALUES (%s,%s,%s,%s,%s,0,%s)",
                                (user_id, actual_subj_id, tt_id, mark_date, status, sub_record))
            cur.execute("INSERT IGNORE INTO daily_submissions (user_id,submission_date) VALUES (%s,%s)", (user_id, mark_date))
            conn.commit()
            flash(f'Attendance saved for {mark_date.strftime("%A, %d %b %Y")}! ✅', 'success')
            return redirect(url_for('dashboard'))
        existing = {}; free_chosen = {}; sub_chosen = {}
        for slot in slots:
            tt_id = slot[0]
            cur.execute("SELECT status, free_subject_id, subject_id FROM attendance WHERE user_id=%s AND timetable_id=%s AND class_date=%s",
                        (user_id, tt_id, mark_date))
            row = cur.fetchone()
            if row: existing[tt_id] = row[0]; free_chosen[tt_id] = row[1]; sub_chosen[tt_id] = row[2]
    finally:
        cur.close(); release_db(conn)
    return render_template('mark_attendance.html', slots=slots, mark_date=mark_date, day_name=day_name,
        is_saturday=is_saturday, already_submitted=already_submitted, existing=existing,
        free_chosen=free_chosen, sub_chosen=sub_chosen, subjects=subjects,
        subjects_dict=subjects_dict, user=user, today=date.today())

@app.route('/past_dates')
def past_dates():
    user = validate_session()
    if not user: return redirect(url_for("login"))
    user_id = user[0]
    _active_sem = get_active_semester(user_id)
    sem_start = _active_sem[5] if _active_sem else user[6]
    today = date.today()
    conn, cur = get_cursor()
    try:
        cur.execute("SELECT submission_date FROM daily_submissions WHERE user_id=%s AND submission_date BETWEEN %s AND %s", (user_id, sem_start, today))
        submitted = {row[0] for row in cur.fetchall()}
        sem_id = get_active_semester_id(user_id)
        if sem_id: cur.execute("SELECT DISTINCT day_of_week FROM timetable WHERE user_id=%s AND semester_id=%s", (user_id, sem_id))
        else: cur.execute("SELECT DISTINCT day_of_week FROM timetable WHERE user_id=%s AND semester_id IS NULL", (user_id,))
        tt_days = {row[0] for row in cur.fetchall()}
        cur.execute("SELECT sat_date FROM saturday_config WHERE user_id=%s AND is_working=1 AND sat_date BETWEEN %s AND %s", (user_id, sem_start, today))
        working_saturdays = {row[0] for row in cur.fetchall()}
    finally:
        cur.close(); release_db(conn)
    pending = []
    d = sem_start
    while d < today:
        dow = d.weekday()
        if dow == 6: d += timedelta(days=1); continue
        if d not in submitted:
            if dow == 5: pending.append({"date": d, "is_saturday": True, "configured": d in working_saturdays})
            elif dow in tt_days: pending.append({"date": d, "is_saturday": False, "configured": True})
        d += timedelta(days=1)
    page = int(request.args.get('page', 1)); per_page = 30; total = len(pending)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    return render_template("past_dates.html", pending_dates=pending[start:start+per_page],
        user=user, page=page, total_pages=total_pages, total=total)

@app.route('/timetable')
def view_timetable():
    user = validate_session()
    if not user: return redirect(url_for('login'))
    user_id = user[0]
    conn, cur = get_cursor()
    try:
        sem_id = get_active_semester_id(user_id)
        if sem_id: cur.execute("SELECT day_of_week, total_periods FROM day_config WHERE user_id=%s AND has_classes=1 AND semester_id=%s ORDER BY day_of_week", (user_id, sem_id))
        else: cur.execute("SELECT day_of_week, total_periods FROM day_config WHERE user_id=%s AND has_classes=1 AND semester_id IS NULL ORDER BY day_of_week", (user_id,))
        day_configs = {row[0]: row[1] for row in cur.fetchall()}
        grid = {}
        for day_idx in day_configs:
            grid[day_idx] = {p: None for p in range(1, day_configs[day_idx]+1)}
        if sem_id:
            cur.execute("""SELECT t.day_of_week, t.period_number, t.slot_label, t.is_free, COALESCE(s.subject_name,'Free Hour')
                FROM timetable t LEFT JOIN subjects s ON t.subject_id=s.id
                WHERE t.user_id=%s AND t.semester_id=%s ORDER BY t.day_of_week, t.period_number""", (user_id, sem_id))
        else:
            cur.execute("""SELECT t.day_of_week, t.period_number, t.slot_label, t.is_free, COALESCE(s.subject_name,'Free Hour')
                FROM timetable t LEFT JOIN subjects s ON t.subject_id=s.id
                WHERE t.user_id=%s AND t.semester_id IS NULL ORDER BY t.day_of_week, t.period_number""", (user_id,))
        for row in cur.fetchall():
            dow, period, time_label, is_free, subj_name = row
            if dow in grid: grid[dow][period] = {"name": subj_name, "is_free": is_free, "time": time_label}
        max_periods = max(day_configs.values()) if day_configs else 0
    finally:
        cur.close(); release_db(conn)
    return render_template('timetable.html', grid=grid, day_configs=day_configs,
        day_names=DAY_NAMES, max_periods=max_periods, user=user)

@app.route('/saturday', methods=['GET', 'POST'])
def saturday_check():
    user = validate_session()
    if not user: return redirect(url_for('login'))
    user_id = user[0]
    subjects = get_subjects(user_id)
    subjects_dict = {s[0]: s[1] for s in subjects}
    mark_date_str = request.args.get('date', date.today().isoformat())
    mark_date = date.fromisoformat(mark_date_str)
    is_edit_mode = request.args.get('edit') == '1'
    conn, cur = get_cursor()
    try:
        cur.execute("SELECT is_working, total_periods FROM saturday_config WHERE user_id=%s AND sat_date=%s", (user_id, mark_date))
        existing_config = cur.fetchone()
        existing_slots = []
        if existing_config and existing_config[0] == 1:
            cur.execute("""SELECT ss.id, ss.period_number, ss.slot_label, ss.subject_id,
                   COALESCE(s.subject_name,'Free Hour'), ss.is_free
                FROM saturday_slots ss LEFT JOIN subjects s ON ss.subject_id=s.id
                WHERE ss.user_id=%s AND ss.sat_date=%s ORDER BY ss.period_number""", (user_id, mark_date))
            existing_slots = cur.fetchall()
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'holiday':
                # MySQL ON DUPLICATE KEY UPDATE replaces PostgreSQL ON CONFLICT DO UPDATE
                cur.execute("INSERT INTO saturday_config (user_id,sat_date,is_working,total_periods) VALUES (%s,%s,0,0) ON DUPLICATE KEY UPDATE is_working=0, total_periods=0",
                            (user_id, mark_date))
                cur.execute("INSERT IGNORE INTO daily_submissions (user_id,submission_date) VALUES (%s,%s)", (user_id, mark_date))
                conn.commit()
                flash(f'{mark_date.strftime("%d %b %Y")} marked as holiday 🏖️', 'success')
                return redirect(url_for('dashboard'))
            elif action == 'working':
                total_periods = int(request.form.get('total_periods', 0))
                if total_periods == 0:
                    flash('Please select number of periods!', 'error')
                    return redirect(url_for('saturday_check', date=mark_date_str))
                cur.execute("INSERT INTO saturday_config (user_id,sat_date,is_working,total_periods) VALUES (%s,%s,1,%s) ON DUPLICATE KEY UPDATE is_working=1, total_periods=%s",
                            (user_id, mark_date, total_periods, total_periods))
                cur.execute("DELETE FROM saturday_slots WHERE user_id=%s AND sat_date=%s", (user_id, mark_date))
                for p in range(1, total_periods + 1):
                    subj_id = request.form.get(f'period_{p}_subject', '')
                    slot_label = SLOT_TIMES[p-1] if p <= len(SLOT_TIMES) else f'Period {p}'
                    if subj_id == 'FREE':
                        cur.execute("INSERT INTO saturday_slots (user_id,sat_date,period_number,subject_id,slot_label,is_free) VALUES (%s,%s,%s,NULL,%s,1)",
                                    (user_id, mark_date, p, slot_label))
                    elif subj_id:
                        cur.execute("INSERT INTO saturday_slots (user_id,sat_date,period_number,subject_id,slot_label,is_free) VALUES (%s,%s,%s,%s,%s,0)",
                                    (user_id, mark_date, p, int(subj_id), slot_label))
                conn.commit()
                flash('Saturday schedule saved! Now mark attendance.', 'success')
                if is_edit_mode: return redirect(url_for('mark_saturday', date=mark_date_str, edit='1'))
                return redirect(url_for('mark_saturday', date=mark_date_str))
    finally:
        cur.close(); release_db(conn)
    return render_template('saturday_check.html', mark_date=mark_date, subjects=subjects,
        subjects_dict=subjects_dict, existing_config=existing_config, existing_slots=existing_slots,
        slot_times=SLOT_TIMES, user=user, today=date.today(), is_edit_mode=is_edit_mode)

@app.route('/mark_saturday', methods=['GET', 'POST'])
def mark_saturday():
    user = validate_session()
    if not user: return redirect(url_for('login'))
    user_id = user[0]
    subjects = get_subjects(user_id)
    subjects_dict = {s[0]: s[1] for s in subjects}
    mark_date_str = request.args.get('date', date.today().isoformat())
    mark_date = date.fromisoformat(mark_date_str)
    conn, cur = get_cursor()
    try:
        cur.execute("""SELECT ss.id, ss.period_number, ss.slot_label, ss.subject_id,
               COALESCE(s.subject_name,'Free Hour'), ss.is_free
            FROM saturday_slots ss LEFT JOIN subjects s ON ss.subject_id=s.id
            WHERE ss.user_id=%s AND ss.sat_date=%s ORDER BY ss.period_number""", (user_id, mark_date))
        sat_slots = cur.fetchall()
        if not sat_slots: return redirect(url_for('saturday_check', date=mark_date_str))
        cur.execute("SELECT id FROM daily_submissions WHERE user_id=%s AND submission_date=%s", (user_id, mark_date))
        already_submitted = cur.fetchone()
        force_edit = request.args.get('edit') == '1'
        if force_edit and already_submitted: already_submitted = None
        if request.method == 'POST':
            cur.execute("DELETE FROM attendance WHERE user_id=%s AND class_date=%s AND timetable_id < 0", (user_id, mark_date))
            for slot in sat_slots:
                slot_id, period, slot_label, orig_subj_id, orig_subj_name, is_free = slot
                fake_tt_id = -slot_id
                if is_free:
                    skip = request.form.get(f'skip_free_{slot_id}', '1')
                    free_subj_id = request.form.get(f'free_subject_{slot_id}', None)
                    if skip == '1' or not free_subj_id: continue
                    free_subj_id = int(free_subj_id)
                    status = request.form.get(f'status_{slot_id}', 'absent')
                    cur.execute("INSERT INTO attendance (user_id,subject_id,timetable_id,class_date,status,is_free_hour,free_subject_id) VALUES (%s,%s,%s,%s,%s,1,%s)",
                                (user_id, free_subj_id, fake_tt_id, mark_date, status, free_subj_id))
                else:
                    status = request.form.get(f'status_{slot_id}', 'absent')
                    sub_val = request.form.get(f'sub_subject_{slot_id}', '')
                    actual_subj_id = int(sub_val) if sub_val else orig_subj_id
                    if not actual_subj_id: continue
                    sub_record = actual_subj_id if actual_subj_id != orig_subj_id else None
                    cur.execute("INSERT INTO attendance (user_id,subject_id,timetable_id,class_date,status,is_free_hour,free_subject_id) VALUES (%s,%s,%s,%s,%s,0,%s)",
                                (user_id, actual_subj_id, fake_tt_id, mark_date, status, sub_record))
            cur.execute("INSERT IGNORE INTO daily_submissions (user_id,submission_date) VALUES (%s,%s)", (user_id, mark_date))
            conn.commit()
            flash(f'Saturday attendance saved for {mark_date.strftime("%d %b %Y")}! ✅', 'success')
            return redirect(url_for('dashboard'))
        existing = {}; sub_chosen = {}; free_chosen = {}
        for slot in sat_slots:
            slot_id, period, slot_label, orig_subj_id, orig_subj_name, is_free = slot
            fake_tt_id = -slot_id
            cur.execute("SELECT status, subject_id, free_subject_id FROM attendance WHERE user_id=%s AND timetable_id=%s AND class_date=%s",
                        (user_id, fake_tt_id, mark_date))
            row = cur.fetchone()
            if row: existing[slot_id] = row[0]; sub_chosen[slot_id] = row[1]; free_chosen[slot_id] = row[2]
    finally:
        cur.close(); release_db(conn)
    return render_template('mark_saturday.html', sat_slots=sat_slots, mark_date=mark_date,
        already_submitted=already_submitted, existing=existing, sub_chosen=sub_chosen,
        free_chosen=free_chosen, subjects_dict=subjects_dict, subjects=subjects,
        user=user, today=date.today())

@app.route('/api/today_status')
def today_status():
    user = validate_session()
    if not user: return jsonify({"has_classes": False, "submitted": False, "is_saturday": False})
    user_id = user[0]; today = date.today()
    conn, cur = get_cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM timetable WHERE user_id=%s AND day_of_week=%s AND semester_id=%s",
                    (user_id, today.weekday(), get_active_semester_id(user_id)))
        has_classes = cur.fetchone()[0] > 0
        cur.execute("SELECT id FROM daily_submissions WHERE user_id=%s AND submission_date=%s", (user_id, today))
        submitted = cur.fetchone() is not None
    finally:
        cur.close(); release_db(conn)
    return jsonify({"has_classes": has_classes, "submitted": submitted, "is_saturday": today.weekday() == 5, "date": today.isoformat()})

@app.route('/api/chart/<int:subject_id>')
def chart_data(subject_id):
    user = validate_session()
    if not user: return jsonify({})
    user_id = user[0]
    conn, cur = get_cursor()
    try:
        cur.execute("""SELECT class_date, status FROM attendance WHERE user_id=%s
            AND ((subject_id=%s AND is_free_hour=0) OR (free_subject_id=%s AND is_free_hour=1))
            ORDER BY class_date ASC LIMIT 30""", (user_id, subject_id, subject_id))
        rows = cur.fetchall()
    finally:
        cur.close(); release_db(conn)
    labels, pcts = [], []; attended = total = 0
    for r in rows:
        total += 1
        if r[1] == 'present': attended += 1
        labels.append(str(r[0])); pcts.append(min(100.0, round(attended/total*100, 1)))
    return jsonify({"labels": labels, "pcts": pcts})

def restore_semester_snapshot(user_id, sem_id, cur):
    cur.execute("SELECT COUNT(*) FROM timetable WHERE user_id=%s AND semester_id=%s", (user_id, sem_id))
    return cur.fetchone()[0] > 0

def ensure_semester_exists(user_id, user):
    conn, cur = get_cursor()
    try:
        cur.execute("SELECT id FROM semesters WHERE user_id=%s", (user_id,))
        if not cur.fetchone() and user[6] and user[7]:
            cur.execute("""INSERT INTO semesters (user_id,semester_number,semester_label,branch,sem_start,sem_end,is_active)
                VALUES (%s,%s,%s,%s,%s,%s,1)""",
                (user_id, user[4] or 1, f"Sem {user[4] or 1} (imported)", user[5] or '', user[6], user[7]))
            conn.commit()
    finally:
        cur.close(); release_db(conn)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    user = validate_session()
    if not user: return redirect(url_for('login'))
    user_id = user[0]
    ensure_semester_exists(user_id, user)
    conn, cur = get_cursor()
    try:
        cur.execute("SELECT * FROM semesters WHERE user_id=%s ORDER BY id DESC", (user_id,))
        all_sems = cur.fetchall()
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'update_profile':
                new_name = request.form.get('name', '').strip()
                new_password = request.form.get('new_password', '').strip()
                current_password = request.form.get('current_password', '').strip()
                photo_filename = None
                if 'photo' in request.files:
                    f = request.files['photo']
                    if f and f.filename and allowed_file(f.filename):
                        ext = f.filename.rsplit('.', 1)[1].lower()
                        photo_filename = f"user_{user_id}.{ext}"
                        for e in ALLOWED_EXTENSIONS:
                            old_path = os.path.join(UPLOAD_FOLDER, f"user_{user_id}.{e}")
                            if os.path.exists(old_path) and e != ext: os.remove(old_path)
                        f.save(os.path.join(UPLOAD_FOLDER, photo_filename))
                if new_name: cur.execute("UPDATE users SET name=%s WHERE id=%s", (new_name, user_id)); session['user_name'] = new_name
                if photo_filename:
                    try: cur.execute("UPDATE users SET photo=%s WHERE id=%s", (photo_filename, user_id))
                    except: pass
                    session['user_photo'] = photo_filename
                if new_password:
                    if not current_password or not check_password_hash(user[3], current_password):
                        flash('Current password is incorrect!', 'error'); return redirect(url_for('profile'))
                    if len(new_password) < 6:
                        flash('New password must be at least 6 characters!', 'error'); return redirect(url_for('profile'))
                    cur.execute("UPDATE users SET password=%s WHERE id=%s", (generate_password_hash(new_password), user_id))
                conn.commit(); flash('Profile updated! ✅', 'success')
            elif action == 'add_semester':
                sem_num = request.form.get('semester_number', '1'); sem_label = request.form.get('semester_label', '').strip()
                branch = request.form.get('branch', '').strip(); sem_start = request.form.get('sem_start', '')
                sem_end = request.form.get('sem_end', ''); make_active = request.form.get('make_active') == '1'
                if not sem_start or not sem_end:
                    flash('Please fill in semester dates!', 'error'); return redirect(url_for('profile'))
                if make_active: cur.execute("UPDATE semesters SET is_active=0 WHERE user_id=%s", (user_id,))
                cur.execute("""INSERT INTO semesters (user_id,semester_number,semester_label,branch,sem_start,sem_end,is_active)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (user_id, int(sem_num), sem_label or f"Sem {sem_num}", branch, sem_start, sem_end, 1 if make_active else 0))
                if make_active:
                    cur.execute("UPDATE users SET semester=%s,branch=%s,semester_start=%s,semester_end=%s,setup_done=0 WHERE id=%s",
                                (int(sem_num), branch, sem_start, sem_end, user_id))
                    conn.commit(); flash('New semester created! 🗓️', 'success'); return redirect(url_for('setup_step1'))
                conn.commit(); flash('Semester added! ✅', 'success')
            elif action == 'switch_semester':
                sem_id = int(request.form.get('sem_id', 0))
                if sem_id:
                    cur.execute("SELECT semester_number,branch,sem_start,sem_end FROM semesters WHERE id=%s AND user_id=%s", (sem_id, user_id))
                    s = cur.fetchone()
                    if s:
                        cur.execute("UPDATE semesters SET is_active=0 WHERE user_id=%s", (user_id,))
                        cur.execute("UPDATE semesters SET is_active=1 WHERE id=%s AND user_id=%s", (sem_id, user_id))
                        cur.execute("UPDATE users SET semester=%s,branch=%s,semester_start=%s,semester_end=%s WHERE id=%s",
                                    (s[0], s[1], s[2], s[3], user_id))
                        has_data = restore_semester_snapshot(user_id, sem_id, cur)
                        conn.commit()
                        if has_data:
                            cur.execute("UPDATE users SET setup_done=1 WHERE id=%s", (user_id,)); conn.commit()
                            flash('Switched semester ✅', 'success')
                        else:
                            cur.execute("UPDATE users SET setup_done=0 WHERE id=%s", (user_id,)); conn.commit()
                            flash('Please set up timetable. 🗓️', 'info'); return redirect(url_for('setup_step1'))
                    conn.commit()
            elif action == 'edit_semester':
                sem_id = int(request.form.get('sem_id', 0)); sem_start = request.form.get('sem_start', '')
                sem_end = request.form.get('sem_end', ''); sem_label = request.form.get('semester_label', '').strip()
                branch = request.form.get('branch', '').strip()
                if sem_id and sem_start and sem_end:
                    cur.execute("UPDATE semesters SET sem_start=%s,sem_end=%s,semester_label=%s,branch=%s WHERE id=%s AND user_id=%s",
                                (sem_start, sem_end, sem_label, branch, sem_id, user_id))
                    cur.execute("SELECT is_active FROM semesters WHERE id=%s", (sem_id,))
                    row = cur.fetchone()
                    if row and row[0]: cur.execute("UPDATE users SET semester_start=%s,semester_end=%s,branch=%s WHERE id=%s",
                                                   (sem_start, sem_end, branch, user_id))
                    conn.commit(); flash('Semester updated! ✅', 'success')
            return redirect(url_for('profile'))
        photo = None
        try:
            cur.execute("SELECT photo FROM users WHERE id=%s", (user_id,))
            row = cur.fetchone(); photo = row[0] if row else None
        except: pass
    finally:
        cur.close(); release_db(conn)
    total_sems = user[9] if len(user) > 9 else 8
    return render_template('profile.html', user=user, all_sems=all_sems, photo=photo,
        today=date.today(), total_sems=total_sems)

@app.route('/api/semester_stats/<int:sem_id>')
def semester_stats(sem_id):
    user = validate_session()
    if not user: return jsonify({})
    user_id = user[0]
    conn, cur = get_cursor()
    try:
        cur.execute("SELECT * FROM semesters WHERE id=%s AND user_id=%s", (sem_id, user_id))
        sem = cur.fetchone()
        if not sem: return jsonify({})
        sem_start, sem_end = sem[5], sem[6]
        cur.execute("""SELECT s.subject_name, SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END), COUNT(*)
            FROM attendance a JOIN subjects s ON a.subject_id=s.id
            WHERE a.user_id=%s AND a.class_date BETWEEN %s AND %s GROUP BY s.subject_name ORDER BY s.subject_name""",
            (user_id, sem_start, sem_end))
        rows = cur.fetchall()
    finally:
        cur.close(); release_db(conn)
    data = [{"subject": r[0], "attended": int(r[1]), "total": int(r[2]), "pct": round(r[1]/r[2]*100,1) if r[2] > 0 else 0} for r in rows]
    return jsonify({"semester": sem[3], "start": str(sem_start), "end": str(sem_end), "subjects": data})

@app.route('/api/upload_photo', methods=['POST'])
def upload_photo():
    user = validate_session()
    if not user: return jsonify({'ok': False, 'error': 'Not logged in'}), 401
    user_id = user[0]
    if 'photo' not in request.files: return jsonify({'ok': False, 'error': 'No file sent'}), 400
    f = request.files['photo']
    if not f or not f.filename: return jsonify({'ok': False, 'error': 'Empty file'}), 400
    if not allowed_file(f.filename): return jsonify({'ok': False, 'error': 'Invalid file type'}), 400
    ext = f.filename.rsplit('.', 1)[1].lower(); filename = f"user_{user_id}.{ext}"
    for e in ALLOWED_EXTENSIONS:
        old_path = os.path.join(UPLOAD_FOLDER, f"user_{user_id}.{e}")
        if os.path.exists(old_path) and e != ext: os.remove(old_path)
    f.save(os.path.join(UPLOAD_FOLDER, filename))
    conn, cur = get_cursor()
    try:
        cur.execute("UPDATE users SET photo=%s WHERE id=%s", (filename, user_id)); conn.commit()
    except Exception as e:
        return jsonify({'ok': False, 'error': f'DB error: {str(e)}'}), 500
    finally:
        cur.close(); release_db(conn)
    session['user_photo'] = filename
    return jsonify({'ok': True, 'filename': filename, 'url': f"/static/uploads/{filename}?v={int(time.time())}"})

@app.route('/attendance_history')
def attendance_history():
    user = validate_session()
    if not user: return redirect(url_for('login'))
    user_id = user[0]
    _active_sem = get_active_semester(user_id)
    sem_start = _active_sem[5] if _active_sem else user[6]
    sem_end = _active_sem[6] if _active_sem else user[7]
    sem_id = get_active_semester_id(user_id)
    conn, cur = get_cursor()
    try:
        cur.execute("SELECT submission_date FROM daily_submissions WHERE user_id=%s AND submission_date BETWEEN %s AND %s ORDER BY submission_date DESC",
                    (user_id, sem_start, sem_end))
        submitted_dates = [row[0] for row in cur.fetchall()]
        history = []
        for d in submitted_dates:
            is_saturday = d.weekday() == 5
            if is_saturday:
                cur.execute("""SELECT SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END), SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END)
                    FROM saturday_slots ss JOIN attendance a ON a.timetable_id=-ss.id AND a.user_id=ss.user_id AND a.class_date=%s
                    WHERE ss.user_id=%s AND ss.sat_date=%s AND ss.is_free=0""", (d, user_id, d))
            else:
                if sem_id:
                    cur.execute("""SELECT SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END), SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END)
                        FROM timetable t JOIN attendance a ON a.timetable_id=t.id AND a.user_id=t.user_id AND a.class_date=%s
                        WHERE t.user_id=%s AND t.day_of_week=%s AND t.semester_id=%s AND t.is_free=0""", (d, user_id, d.weekday(), sem_id))
                else:
                    cur.execute("""SELECT SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END), SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END)
                        FROM timetable t JOIN attendance a ON a.timetable_id=t.id AND a.user_id=t.user_id AND a.class_date=%s
                        WHERE t.user_id=%s AND t.day_of_week=%s AND t.is_free=0""", (d, user_id, d.weekday()))
            row = cur.fetchone(); present = int(row[0] or 0); absent = int(row[1] or 0)
            history.append({'date': d, 'day_name': DAY_NAMES[d.weekday()] if d.weekday() < 6 else 'Sunday',
                'total': present+absent, 'present': present, 'absent': absent, 'is_saturday': is_saturday})
    finally:
        cur.close(); release_db(conn)
    return render_template('attendance_history.html', history=history, user=user,
        sem_start=sem_start, sem_end=sem_end, today=date.today())

@app.route('/timetable/edit', methods=['GET', 'POST'])
def edit_timetable():
    user = validate_session()
    if not user: return redirect(url_for('login'))
    user_id = user[0]
    conn, cur = get_cursor()
    try:
        sem_id = get_active_semester_id(user_id)
        if request.method == 'POST':
            if sem_id:
                cur.execute("SELECT day_of_week, total_periods FROM day_config WHERE user_id=%s AND has_classes=1 AND semester_id=%s", (user_id, sem_id))
                day_configs = {r[0]: r[1] for r in cur.fetchall()}
                cur.execute("SELECT id, subject_name FROM subjects WHERE user_id=%s AND semester_id=%s", (user_id, sem_id))
            else:
                cur.execute("SELECT day_of_week, total_periods FROM day_config WHERE user_id=%s AND has_classes=1 AND semester_id IS NULL", (user_id,))
                day_configs = {r[0]: r[1] for r in cur.fetchall()}
                cur.execute("SELECT id, subject_name FROM subjects WHERE user_id=%s AND semester_id IS NULL", (user_id,))
            subj_map = {r[1]: r[0] for r in cur.fetchall()}
            if sem_id: cur.execute("DELETE FROM timetable WHERE user_id=%s AND semester_id=%s", (user_id, sem_id))
            else: cur.execute("DELETE FROM timetable WHERE user_id=%s AND semester_id IS NULL", (user_id,))
            for day_idx, total_periods in day_configs.items():
                for period in range(1, total_periods + 1):
                    field = f"slot_{day_idx}_{period}"; val = request.form.get(field, '').strip()
                    slot_time = SLOT_TIMES[period-1] if period <= len(SLOT_TIMES) else f"Period {period}"
                    if val == 'FREE':
                        cur.execute("INSERT INTO timetable (user_id,subject_id,day_of_week,period_number,slot_label,is_free,semester_id) VALUES (%s,NULL,%s,%s,%s,1,%s)",
                                    (user_id, day_idx, period, slot_time, sem_id))
                    elif val and val in subj_map:
                        cur.execute("INSERT INTO timetable (user_id,subject_id,day_of_week,period_number,slot_label,is_free,semester_id) VALUES (%s,%s,%s,%s,%s,0,%s)",
                                    (user_id, subj_map[val], day_idx, period, slot_time, sem_id))
            conn.commit(); flash('Timetable updated! ✅', 'success')
            return redirect(url_for('view_timetable'))
        if sem_id:
            cur.execute("SELECT day_of_week, total_periods FROM day_config WHERE user_id=%s AND has_classes=1 AND semester_id=%s ORDER BY day_of_week", (user_id, sem_id))
            day_configs = cur.fetchall()
            cur.execute("SELECT id, subject_name FROM subjects WHERE user_id=%s AND semester_id=%s ORDER BY subject_name", (user_id, sem_id))
        else:
            cur.execute("SELECT day_of_week, total_periods FROM day_config WHERE user_id=%s AND has_classes=1 AND semester_id IS NULL ORDER BY day_of_week", (user_id,))
            day_configs = cur.fetchall()
            cur.execute("SELECT id, subject_name FROM subjects WHERE user_id=%s AND semester_id IS NULL ORDER BY subject_name", (user_id,))
        subjects = cur.fetchall()
        if sem_id:
            cur.execute("""SELECT t.day_of_week, t.period_number, t.is_free, COALESCE(s.subject_name,'')
                FROM timetable t LEFT JOIN subjects s ON t.subject_id=s.id WHERE t.user_id=%s AND t.semester_id=%s""", (user_id, sem_id))
        else:
            cur.execute("""SELECT t.day_of_week, t.period_number, t.is_free, COALESCE(s.subject_name,'')
                FROM timetable t LEFT JOIN subjects s ON t.subject_id=s.id WHERE t.user_id=%s AND t.semester_id IS NULL""", (user_id,))
        current = {}
        for row in cur.fetchall():
            dow, period, is_free, subj_name = row
            if dow not in current: current[dow] = {}
            current[dow][period] = 'FREE' if is_free else subj_name
    finally:
        cur.close(); release_db(conn)
    return render_template('edit_timetable.html', day_configs=day_configs, subjects=subjects,
        current=current, day_names=DAY_NAMES, slot_times=SLOT_TIMES, user=user)

if __name__ == '__main__':
    app.run(debug=True)
