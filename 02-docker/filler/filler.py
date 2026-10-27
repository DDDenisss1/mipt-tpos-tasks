import csv
import os
import sys
import time
import pymysql

def connect():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        charset="utf8mb4",
        connect_timeout=5,
        autocommit=False,
    )


def read_csv():
    with open(
        "/app/data.csv",
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames or not {
            "name", "age"
        }.issubset(set(reader.fieldnames)):
            raise ValueError(
                "CSV must contain name and age columns"
            )

        rows = []

        for line_number, row in enumerate(reader, start=2):
            name = (row.get("name") or "").strip()
            age_value = row.get("age")

            if not name or age_value is None:
                raise ValueError(
                    f"Invalid CSV data at line {line_number}"
                )

            try:
                age = int(age_value)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Invalid age at line {line_number}: "
                    f"{age_value!r}"
                ) from error

            rows.append((name, age))

        if not rows:
            raise ValueError("CSV contains no data rows")

        return rows


def main():
    connection = None

    for attempt in range(30):
        try:
            connection = connect()
            break
        except pymysql.MySQLError as error:
            print(
                f"Waiting for database ({attempt + 1}/30): "
                f"{error}",
                flush=True,
            )
            time.sleep(2)

    if connection is None:
        print(
            "ERROR: Could not connect to database",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        rows = read_csv()

        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS data (
                    name VARCHAR(255) NOT NULL,
                    age INT NOT NULL
                )
                """
            )

            inserted_count = 0

            for name, age in rows:
                cursor.execute(
                    """
                    SELECT 1
                    FROM data
                    WHERE name = %s AND age = %s
                    LIMIT 1
                    """,
                    (name, age),
                )

                if cursor.fetchone() is None:
                    cursor.execute(
                        """
                        INSERT INTO data (name, age)
                        VALUES (%s, %s)
                        """,
                        (name, age),
                    )
                    inserted_count += 1

        connection.commit()

        print(
            f"CSV processed: {len(rows)} rows, "
            f"{inserted_count} new rows inserted",
            flush=True,
        )

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

if __name__ == "__main__":
    main()
