"""
Simple migration helper: adds missing columns to `users` table
and creates new tables for SQLite databases.

Run this from the flask_dashboard folder like:
  python db_migrate.py

It will inspect the configured `SQLALCHEMY_DATABASE_URI` and, for sqlite files,
add missing columns using `ALTER TABLE`.
"""
import sqlite3
import os
from urllib.parse import urlparse
from app import app


def run_migrations():
    with app.app_context():
        uri = app.config.get('SQLALCHEMY_DATABASE_URI')
        if not uri:
            print('No database URI configured')
            return

        if uri.startswith('sqlite:///'):
            db_path = uri.replace('sqlite:///', '')
        elif uri.startswith('sqlite:'):
            # fallback
            db_path = uri.split(':', 1)[1]
        else:
            print('Only sqlite databases are supported by this helper.')
            return

        # If the path is not absolute, try common locations (app.instance_path)
        if not os.path.isabs(db_path) and not os.path.exists(db_path):
            alt = os.path.join(app.instance_path, os.path.basename(db_path))
            if os.path.exists(alt):
                db_path = alt
            else:
                print(f'Database file not found: {db_path}')
                return

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Get current columns in users table
        cur.execute("PRAGMA table_info('users')")
        cols = [r[1] for r in cur.fetchall()]
        
        # Define all columns that should exist
        user_columns = {
            'password_hash': 'TEXT',
            'is_admin': 'INTEGER DEFAULT 0',
            'mentor_id': 'TEXT',
            'is_mentor': 'INTEGER DEFAULT 0',
            'referred_by_mentor_id': 'TEXT',
            'total_referrals': 'INTEGER DEFAULT 0',
            'total_commission': 'REAL DEFAULT 0.0',
            'email_notifications': 'INTEGER DEFAULT 1',
            'trade_alerts': 'INTEGER DEFAULT 1',
            'signal_alerts': 'INTEGER DEFAULT 1',
        }
        
        for col_name, col_type in user_columns.items():
            if col_name not in cols:
                print(f'Adding column: {col_name}')
                cur.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
            else:
                print(f'Column {col_name} already present')

        # Create notifications table if not exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                type TEXT DEFAULT 'info',
                is_read INTEGER DEFAULT 0,
                data TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        print('Notifications table ready')
        
        # Create referrals table if not exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mentor_id TEXT NOT NULL,
                referred_user_id TEXT NOT NULL,
                license_id INTEGER,
                commission_amount REAL DEFAULT 0.0,
                commission_paid INTEGER DEFAULT 0,
                paid_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (mentor_id) REFERENCES users(id),
                FOREIGN KEY (referred_user_id) REFERENCES users(id),
                FOREIGN KEY (license_id) REFERENCES licenses(id)
            )
        """)
        print('Referrals table ready')

        conn.commit()
        conn.close()
        print('Migration complete!')


if __name__ == '__main__':
    run_migrations()
