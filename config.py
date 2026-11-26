import os

class Config:
    SECRET_KEY = os.getenv("SHOPSPHERE_SECRET_KEY")
    MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER = os.getenv("MYSQL_USER", "shopsphere")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "shopsphere_db")
    MYSQL_CHARSET = "utf8mb4"
    MYSQL_ALLOW_LOCAL_INFILE = False
    MYSQL_AUTOCOMMIT = False
    MYSQL_SSL_CA = os.getenv("MYSQL_SSL_CA") or None
    MYSQL_SSL_DISABLED = os.getenv("MYSQL_SSL_DISABLED") == "1"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("COOKIE_SECURE") == "1"
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
