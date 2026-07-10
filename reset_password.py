"""One-off admin password reset. Run in the project venv:  python reset_password.py"""
import sqlite3
from lubripos.config import Config
from lubripos.core import security

USERNAME = "admin"
NEW_PASSWORD = "admin123"   # temporary — you'll be forced to change it at login

db_path = Config().db_path
print("Database:", db_path)
h, salt, iters = security.hash_password(NEW_PASSWORD)
conn = sqlite3.connect(str(db_path))
cur = conn.execute(
    "UPDATE users SET password_hash=?, password_salt=?, pwd_iterations=?, "
    "must_change_pw=1, is_active=1 WHERE username=?",
    (h, salt, iters, USERNAME),
)
conn.commit()
print("OK: password reset. Log in as 'admin' / 'admin123'." if cur.rowcount
      else "No 'admin' user found.")
conn.close()