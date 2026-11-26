from flask_mysql_connector import MySQL

mysql = MySQL()

def query(sql, parameters=()):
    with mysql.connection.cursor(dictionary=True) as cursor:
        cursor.execute(sql, parameters)
        return cursor.fetchall()

def one(sql, parameters=()):
    rows = query(sql, parameters)
    return rows[0] if rows else None

def execute(sql, parameters=()):
    with mysql.connection.cursor() as cursor:
        cursor.execute(sql, parameters)
        return cursor.lastrowid

def commit():
    mysql.connection.commit()

def rollback():
    mysql.connection.rollback()
