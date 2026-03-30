# Create a new file: migrate_token_pausing.py
# Run this script ONCE to add the new columns to your database

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
import os

# Import your existing app configuration
from config import Config, DevelopmentConfig, ProductionConfig

# Create Flask app with same config as your main app
app = Flask(__name__)

# Configure based on environment
if os.environ.get('FLASK_ENV') == 'production':
    app.config.from_object(ProductionConfig)
else:
    app.config.from_object(DevelopmentConfig)

# Initialize SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = app.config.get('SQLALCHEMY_DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

def migrate_user_tokens_table():
    """
    Add new columns to the user_tokens table to support token pausing
    """
    print("🚀 Starting UserToken table migration...")
    
    try:
        with app.app_context():
            # Check if columns already exist
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('user_tokens')]
            
            # Add new columns if they don't exist
            migrations = []
            
            if 'is_paused' not in columns:
                migrations.append("ALTER TABLE user_tokens ADD COLUMN is_paused BOOLEAN DEFAULT FALSE")
                print("  ➕ Adding is_paused column")
            
            if 'paused_at' not in columns:
                migrations.append("ALTER TABLE user_tokens ADD COLUMN paused_at TIMESTAMP NULL")
                print("  ➕ Adding paused_at column")
            
            if 'original_subscription_id' not in columns:
                migrations.append("ALTER TABLE user_tokens ADD COLUMN original_subscription_id INTEGER NULL")
                print("  ➕ Adding original_subscription_id column")
            
            # Execute migrations
            if migrations:
                for migration_sql in migrations:
                    print(f"  🔧 Executing: {migration_sql}")
                    db.session.execute(text(migration_sql))
                
                db.session.commit()
                print("  ✅ All migrations completed successfully!")
            else:
                print("  ℹ️  All columns already exist, no migration needed")
            
            # Verify the new structure
            updated_columns = [col['name'] for col in inspector.get_columns('user_tokens')]
            print(f"  📋 Updated table columns: {updated_columns}")
            
            # Update existing records to set original_subscription_id
            print("  🔄 Updating existing token records...")
            update_sql = """
                UPDATE user_tokens 
                SET original_subscription_id = subscription_id 
                WHERE original_subscription_id IS NULL
            """
            result = db.session.execute(text(update_sql))
            db.session.commit()
            print(f"  ✅ Updated {result.rowcount} existing token records")
            
    except Exception as e:
        db.session.rollback()
        print(f"  ❌ Migration failed: {str(e)}")
        raise

def verify_migration():
    """
    Verify that the migration was successful
    """
    print("\n🔍 Verifying migration...")
    
    try:
        with app.app_context():
            # Test the new columns
            test_query = text("""
                SELECT COUNT(*) as total_tokens,
                       COUNT(CASE WHEN is_paused = TRUE THEN 1 END) as paused_tokens,
                       COUNT(CASE WHEN original_subscription_id IS NOT NULL THEN 1 END) as tokens_with_original_sub
                FROM user_tokens
            """)
            
            result = db.session.execute(test_query).fetchone()
            
            print(f"  📊 Total token records: {result.total_tokens}")
            print(f"  ⏸️  Paused tokens: {result.paused_tokens}")
            print(f"  🔗 Tokens with original subscription: {result.tokens_with_original_sub}")
            print("  ✅ Migration verification completed!")
            
    except Exception as e:
        print(f"  ❌ Verification failed: {str(e)}")
        raise

if __name__ == "__main__":
    print("=" * 60)
    print("🎯 USER TOKEN PAUSING MIGRATION")
    print("=" * 60)
    print("This script will add new columns to support token pausing.")
    print("This ensures unused tokens are preserved when subscriptions expire.")
    print()
    
    confirm = input("Continue with migration? (y/N): ")
    if confirm.lower() != 'y':
        print("❌ Migration cancelled by user")
        exit(1)
    
    try:
        migrate_user_tokens_table()
        verify_migration()
        
        print("\n" + "=" * 60)
        print("🎉 MIGRATION COMPLETED SUCCESSFULLY!")
        print("=" * 60)
        print("✅ Token pausing feature is now ready to use")
        print("✅ Existing tokens have been preserved")
        print("✅ New tokens will support pause/resume functionality")
        print("\n💡 Next steps:")
        print("   1. Restart your Flask application")
        print("   2. Test token purchasing and subscription expiry")
        print("   3. Verify tokens are paused/reactivated correctly")
        
    except Exception as e:
        print(f"\n❌ MIGRATION FAILED: {str(e)}")
        print("Please check the error and try again")
        exit(1)