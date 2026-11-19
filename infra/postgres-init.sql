-- Local database setup (no Docker). Run once as a superuser:
--     sudo -u postgres psql -f infra/postgres-init.sql
-- Creates the app role, the app database and a separate database for the pytest suite. Safe to re-run.
SELECT 'CREATE ROLE audit LOGIN PASSWORD ''audit'''
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'audit')\gexec
SELECT 'CREATE DATABASE audit OWNER audit'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'audit')\gexec
SELECT 'CREATE DATABASE audit_test OWNER audit'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'audit_test')\gexec
