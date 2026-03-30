from config import Config
import psycopg2

def add_trial_tokens_column():
    try:
        db_url = Config.SQLALCHEMY_DATABASE_URI
        print("Connecting to:", db_url)

        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()

        # Check if column exists
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='users' AND column_name='trial_tokens';
        """)
        
        exists = cursor.fetchone()

        if exists:
            print("✔ Column 'trial_tokens' already exists. No action required.")
        else:
            print("⏳ Adding 'trial_tokens' column...")
            cursor.execute("""
                ALTER TABLE users
                ADD COLUMN trial_tokens INTEGER DEFAULT 5 NOT NULL;
            """)
            print("✔ Column 'trial_tokens' added successfully!")

        conn.commit()
        cursor.close()
        conn.close()

    except Exception as e:
        print("❌ Error:", e)

if __name__ == "__main__":
    add_trial_tokens_column()
