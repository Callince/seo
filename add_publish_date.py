from config import Config
import psycopg2

def add_publish_date_column():
    try:
        db_url = Config.SQLALCHEMY_DATABASE_URI
        print("Connecting to:", db_url)

        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()

        # Add the new column only if it doesn't exist
        query = """
        ALTER TABLE blogs
        ADD COLUMN IF NOT EXISTS publish_date DATE;
        """
        cursor.execute(query)

        conn.commit()
        cursor.close()
        conn.close()

        print("✔ Column 'publish_date' added successfully!")

    except Exception as e:
        print("❌ Error:", e)

if __name__ == "__main__":
    add_publish_date_column()
