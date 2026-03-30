"""
Migration script to add custom_usage_limit column to subscribed_users table
Run this script to add the new column to the database
"""

from app import app, db
from sqlalchemy import inspect

def add_custom_usage_limit_column():
    """Add custom_usage_limit column to subscribed_users table if it doesn't exist"""
    with app.app_context():
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('subscribed_users')]

        if 'custom_usage_limit' not in columns:
            print("Adding custom_usage_limit column to subscribed_users table...")
            try:
                # Add the column
                with db.engine.connect() as conn:
                    conn.execute(db.text("""
                        ALTER TABLE subscribed_users
                        ADD COLUMN custom_usage_limit INTEGER NULL
                    """))
                    conn.commit()
                print("✓ Successfully added custom_usage_limit column")
                return True
            except Exception as e:
                print(f"✗ Error adding column: {str(e)}")
                return False
        else:
            print("✓ custom_usage_limit column already exists")
            return True

if __name__ == '__main__':
    success = add_custom_usage_limit_column()
    if success:
        print("\n✓ Database migration completed successfully!")
        print("You can now use the additional usage feature in admin panel.")
    else:
        print("\n✗ Database migration failed. Please check the error message above.")
