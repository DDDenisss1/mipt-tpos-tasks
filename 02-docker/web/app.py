import os
import time
import pymysql
from flask import Flask, jsonify

app = Flask(__name__)

def get_connection():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        charset="utf8mb4",
        connect_timeout=5,
        cursorclass=pymysql.cursors.DictCursor,
    )


def get_rows():
    last_error = None

    for attempt in range(10):
        try:
            connection = get_connection()

            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT name, age FROM data"
                    )
                    return cursor.fetchall()
            finally:
                connection.close()

        except pymysql.MySQLError as error:
            last_error = error
            time.sleep(2)

    raise last_error


@app.route("/")
@app.route("/data")
@app.route("/api/data")
@app.route("/get_data")
def data():
    try:
        rows = get_rows()
        return jsonify(rows), 200

    except Exception:
        app.logger.exception(
            "Failed to retrieve data from database"
        )
        return jsonify({
            "error": "Could not retrieve data from database"
        }), 503


@app.route("/health")
def health():
    try:
        connection = get_connection()
        connection.close()
        return jsonify({"status": "OK"}), 200
    except Exception:
        app.logger.exception("Health check failed")
        return jsonify({"status": "ERROR"}), 503


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8000,
    )
