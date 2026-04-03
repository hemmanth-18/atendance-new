-- ─────────────────────────────────────────────────────
-- AttendSmart — MySQL Schema
-- Run this in your MySQL database
-- ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    semester INT DEFAULT 1,
    branch VARCHAR(100),
    semester_start DATE NOT NULL,
    semester_end DATE NOT NULL,
    setup_done TINYINT DEFAULT 0,
    total_semesters INT DEFAULT 8,
    photo VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS semesters (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    semester_number INT NOT NULL,
    semester_label VARCHAR(50) DEFAULT '',
    branch VARCHAR(100),
    sem_start DATE NOT NULL,
    sem_end DATE NOT NULL,
    is_active TINYINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS subjects (
    id INT AUTO_INCREMENT PRIMARY KEY,  
    user_id INT NOT NULL,
    subject_name VARCHAR(100) NOT NULL,
    semester_id INT DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS day_config (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    day_of_week INT NOT NULL,
    total_periods INT NOT NULL DEFAULT 5,
    has_classes TINYINT DEFAULT 1,
    semester_id INT DEFAULT NULL,
    UNIQUE KEY uq_day_config (user_id, day_of_week, semester_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS timetable (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    subject_id INT,
    day_of_week INT NOT NULL,
    period_number INT NOT NULL,
    slot_label VARCHAR(20) DEFAULT '',
    is_free TINYINT DEFAULT 0,
    semester_id INT DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS attendance (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    subject_id INT NOT NULL,
    timetable_id INT NOT NULL,
    class_date DATE NOT NULL,
    status VARCHAR(10) NOT NULL DEFAULT 'absent',
    is_free_hour TINYINT DEFAULT 0,
    free_subject_id INT DEFAULT NULL,
    marked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_attendance (user_id, timetable_id, class_date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS daily_submissions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    submission_date DATE NOT NULL,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_daily_sub (user_id, submission_date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS saturday_config (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    sat_date DATE NOT NULL,
    is_working TINYINT DEFAULT 1,
    total_periods INT DEFAULT 0,
    UNIQUE KEY uq_sat_config (user_id, sat_date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS saturday_slots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    sat_date DATE NOT NULL,
    period_number INT NOT NULL,
    subject_id INT DEFAULT NULL,
    slot_label VARCHAR(20) DEFAULT '',
    is_free TINYINT DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS semester_snapshots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    semester_id INT NOT NULL,
    record_type VARCHAR(20) NOT NULL,
    meta1 VARCHAR(255) DEFAULT NULL,
    meta2 VARCHAR(50)  DEFAULT NULL,
    meta3 VARCHAR(50)  DEFAULT NULL,
    meta4 VARCHAR(50)  DEFAULT NULL,
    meta5 VARCHAR(10)  DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
