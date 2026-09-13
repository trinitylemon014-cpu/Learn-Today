-- Migration: 006_add_schools_multitenancy.sql
-- Purpose: Convert Learn Together from a single-school platform into a
--          multi-tenant platform. Each school gets its own principal
--          (admin), branding, and isolated roster of teachers/students.
--
-- Run this against your Supabase Postgres database (e.g. via the Supabase
-- SQL editor, or psql "$DATABASE_URL" -f db/migrations/006_add_schools_multitenancy.sql)
--
-- Safe to run once. Wrapped in a transaction so it's all-or-nothing.

BEGIN;

-- 1. Core schools table ------------------------------------------------

CREATE TABLE IF NOT EXISTS schools (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    slug            VARCHAR(100) NOT NULL UNIQUE,
    logo            VARCHAR(300),
    primary_color   VARCHAR(20) DEFAULT '#2563EB',
    principal_id    INTEGER REFERENCES users(id),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_schools_slug ON schools(slug);

-- 2. Tenant column on every table that needs direct scoping -------------

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS school_id INTEGER REFERENCES schools(id);

ALTER TABLE courses
    ADD COLUMN IF NOT EXISTS school_id INTEGER REFERENCES schools(id);

ALTER TABLE groups
    ADD COLUMN IF NOT EXISTS school_id INTEGER REFERENCES schools(id);

ALTER TABLE attendance_sessions
    ADD COLUMN IF NOT EXISTS school_id INTEGER REFERENCES schools(id);

ALTER TABLE scheduled_lessons
    ADD COLUMN IF NOT EXISTS school_id INTEGER REFERENCES schools(id);

CREATE INDEX IF NOT EXISTS idx_users_school_id ON users(school_id);
CREATE INDEX IF NOT EXISTS idx_courses_school_id ON courses(school_id);
CREATE INDEX IF NOT EXISTS idx_groups_school_id ON groups(school_id);

-- 3. role: allow 'principal' as a valid value ----------------------------
-- (role is a free-text VARCHAR in the current schema, so no CHECK
--  constraint needs altering — this line is a no-op safeguard in case
--  one was added later.)

-- 4. Backfill: fold your existing single school into "schools" ----------
-- Creates one School row and attaches every existing user/course/group
-- to it, so nothing already in production becomes orphaned.

INSERT INTO schools (name, slug, primary_color, created_at)
SELECT 'Learn Together', 'learn-together', '#2563EB', NOW()
WHERE NOT EXISTS (SELECT 1 FROM schools WHERE slug = 'learn-together');

UPDATE users
SET school_id = (SELECT id FROM schools WHERE slug = 'learn-together')
WHERE school_id IS NULL;

UPDATE courses
SET school_id = (SELECT id FROM schools WHERE slug = 'learn-together')
WHERE school_id IS NULL;

UPDATE groups
SET school_id = (SELECT id FROM schools WHERE slug = 'learn-together')
WHERE school_id IS NULL;

UPDATE attendance_sessions
SET school_id = (SELECT id FROM schools WHERE slug = 'learn-together')
WHERE school_id IS NULL;

UPDATE scheduled_lessons
SET school_id = (SELECT id FROM schools WHERE slug = 'learn-together')
WHERE school_id IS NULL;

-- 5. Promote your current admin account to principal of that school -----
-- Adjust the email below to match your actual admin account, or run this
-- manually afterwards. Left commented out so it doesn't fire blindly.

-- UPDATE users SET role = 'principal' WHERE email = 'admin@learntogether.com';
-- UPDATE schools SET principal_id = (SELECT id FROM users WHERE email = 'admin@learntogether.com')
-- WHERE slug = 'learn-together';

COMMIT;
