"""
Cleanup script to drop all _anthropic tables if migration failed partway through.
Use this if you need to start the migration over.
"""

import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

def cleanup_anthropic_tables():
    """Drop all _anthropic tables"""
    
    db_uri = os.getenv("DB_URI")
    if not db_uri:
        print("❌ DB_URI environment variable not set")
        sys.exit(1)
    
    # Tables to drop (in reverse dependency order)
    tables_to_drop = [
        "team_memberships_anthropic",  # Drop first (has FKs)
        "todos_anthropic",
        "reminders_anthropic",
        "calendar_events_anthropic",
        "call_recordings_anthropic",
        "teams_anthropic",
        "users_anthropic",
    ]
    
    try:
        engine = create_engine(db_uri)
        
        with engine.connect() as conn:
            # Start transaction
            trans = conn.begin()
            
            try:
                print("🔄 Starting cleanup - dropping _anthropic tables...")
                
                for table_name in tables_to_drop:
                    # Check if table exists
                    check_query = text("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = 'public' 
                            AND table_name = :table_name
                        );
                    """)
                    
                    result = conn.execute(check_query, {"table_name": table_name}).fetchone()
                    table_exists = result[0] if result else False
                    
                    if table_exists:
                        # Drop table with CASCADE to handle dependencies
                        drop_query = text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE;')
                        conn.execute(drop_query)
                        print(f"✅ Dropped table {table_name}")
                    else:
                        print(f"ℹ️  Table {table_name} does not exist, skipping...")
                
                # Commit transaction
                trans.commit()
                print("\n✅ Cleanup completed successfully!")
                print("📝 All _anthropic tables have been dropped")
                print("💡 You can now run create_anthropic_tables.py again")
                
            except Exception as e:
                trans.rollback()
                print(f"\n❌ Cleanup failed: {e}")
                import traceback
                traceback.print_exc()
                raise
        
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("=" * 60)
    print("Cleanup Anthropic Tables")
    print("=" * 60)
    print("\nThis will DROP all _anthropic tables.")
    print("Use this if migration failed and you want to start over.\n")
    
    response = input("Do you want to proceed? (yes/no): ")
    if response.lower() != 'yes':
        print("Cleanup cancelled.")
        sys.exit(0)
    
    cleanup_anthropic_tables()

