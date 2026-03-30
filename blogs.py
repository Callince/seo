"""
Database Initialization Script
This script initializes all database tables defined in app2.py
Run this to create or update all database tables.
"""

import sys
import os

# Add the current directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def init_all_databases():
    """
    Initialize all database tables defined in app2.py
    This will create tables that don't exist and preserve existing data.
    """
    from app import app, db, create_super_admin, normalize_existing_admin_emails, fix_user_timestamps, initialize_website_settings, cleanup_duplicate_subscriptions

    with app.app_context():
        try:
            print("=" * 50)
            print("DATABASE INITIALIZATION")
            print("=" * 50)

            # Get all model classes before creation
            print("\nDetected Database Models:")
            print("-" * 30)

            # List all tables that will be created
            tables = db.metadata.tables.keys()
            for i, table_name in enumerate(sorted(tables), 1):
                print(f"  {i}. {table_name}")

            print(f"\nTotal tables: {len(tables)}")
            print("-" * 30)

            # Create all tables
            print("\nCreating/Updating database tables...")
            db.create_all()
            print("[OK] All database tables created successfully!")

            # Initialize super admin
            print("\nInitializing super admin...")
            try:
                create_super_admin()
                print("[OK] Super admin initialized!")
            except Exception as e:
                print(f"[WARN] Super admin initialization: {str(e)}")

            # Normalize admin emails
            print("\nNormalizing admin emails...")
            try:
                normalize_existing_admin_emails()
                print("[OK] Admin emails normalized!")
            except Exception as e:
                print(f"[WARN] Email normalization: {str(e)}")

            # Fix user timestamps
            print("\nFixing user timestamps...")
            try:
                fix_user_timestamps()
                print("[OK] User timestamps fixed!")
            except Exception as e:
                print(f"[WARN] Timestamp fix: {str(e)}")

            # Initialize website settings
            print("\nInitializing website settings...")
            try:
                initialize_website_settings()
                print("[OK] Website settings initialized!")
            except Exception as e:
                print(f"[WARN] Website settings: {str(e)}")

            # Clean up duplicate subscriptions
            print("\nCleaning up duplicate subscriptions...")
            try:
                deactivated_count = cleanup_duplicate_subscriptions()
                if deactivated_count > 0:
                    print(f"[OK] Cleaned up {deactivated_count} duplicate subscriptions!")
                else:
                    print("[OK] No duplicate subscriptions found!")
            except Exception as e:
                print(f"[WARN] Subscription cleanup: {str(e)}")

            print("\n" + "=" * 50)
            print("DATABASE INITIALIZATION COMPLETE!")
            print("=" * 50)

            # Print summary of tables
            print("\nDatabase Tables Summary:")
            print("-" * 30)

            # Check table row counts
            from sqlalchemy import text
            for table_name in sorted(tables):
                try:
                    result = db.session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                    count = result.scalar()
                    print(f"  {table_name}: {count} rows")
                except Exception as e:
                    print(f"  {table_name}: (unable to count)")

            return True

        except Exception as e:
            print(f"\n[ERROR] Error during database initialization: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


def list_all_models():
    """
    List all database models defined in app2.py without making changes
    """
    from app2 import app, db

    with app.app_context():
        print("=" * 50)
        print("DATABASE MODELS IN app2.py")
        print("=" * 50)

        tables = db.metadata.tables

        for i, (table_name, table) in enumerate(sorted(tables.items()), 1):
            print(f"\n{i}. Table: {table_name}")
            print("   Columns:")
            for column in table.columns:
                nullable = "NULL" if column.nullable else "NOT NULL"
                primary = " (PK)" if column.primary_key else ""
                print(f"      - {column.name}: {column.type} {nullable}{primary}")

        print(f"\nTotal: {len(tables)} tables")
        return tables


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Database initialization utility')
    parser.add_argument('--list', action='store_true', help='List all models without creating tables')
    parser.add_argument('--init', action='store_true', help='Initialize all database tables')

    args = parser.parse_args()

    if args.list:
        list_all_models()
    elif args.init:
        init_all_databases()
    else:
        # Default: run initialization
        print("Running database initialization...")
        print("(Use --list to only list models, --init to initialize)")
        print()
        init_all_databases()
