"""
DEPRECATED: This script RENAMES tables (not recommended).

Use create_anthropic_tables.py instead, which CREATES new tables
while keeping the old ones intact.

This script renames:
- users_convonet → users_anthropic
- teams_convonet → teams_anthropic
- team_memberships_convonet → team_memberships_anthropic
- todos_convonet → todos_anthropic
- reminders_convonet → reminders_anthropic
- calendar_events_convonet → calendar_events_anthropic
- call_recordings_convonet → call_recordings_anthropic

⚠️  WARNING: This will rename existing tables. Use rollback_table_renames.py to undo.
"""

import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

def rename_tables():
    """Rename all convonet tables to include anthropic suffix"""
    
    db_uri = os.getenv("DB_URI")
    if not db_uri:
        print("❌ DB_URI environment variable not set")
        sys.exit(1)
    
    # Table rename mappings
    table_renames = [
        ("users_convonet", "users_anthropic"),
        ("teams_convonet", "teams_anthropic"),
        ("team_memberships_convonet", "team_memberships_anthropic"),
        ("todos_convonet", "todos_anthropic"),
        ("reminders_convonet", "reminders_anthropic"),
        ("calendar_events_convonet", "calendar_events_anthropic"),
        ("call_recordings_convonet", "call_recordings_anthropic"),
    ]
    
    try:
        engine = create_engine(db_uri)
        
        with engine.connect() as conn:
            # Start transaction
            trans = conn.begin()
            
            try:
                print("🔄 Starting table rename migration...")
                
                # Check which tables exist
                for old_name, new_name in table_renames:
                    # Check if old table exists
                    check_query = text("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = 'public' 
                            AND table_name = :table_name
                        );
                    """)
                    
                    result = conn.execute(check_query, {"table_name": old_name}).fetchone()
                    table_exists = result[0] if result else False
                    
                    if not table_exists:
                        print(f"⚠️  Table {old_name} does not exist, skipping...")
                        continue
                    
                    # Check if new table already exists
                    result = conn.execute(check_query, {"table_name": new_name}).fetchone()
                    new_table_exists = result[0] if result else False
                    
                    if new_table_exists:
                        print(f"⚠️  Table {new_name} already exists, skipping rename of {old_name}...")
                        continue
                    
                    # Rename the table
                    rename_query = text(f'ALTER TABLE "{old_name}" RENAME TO "{new_name}";')
                    conn.execute(rename_query)
                    print(f"✅ Renamed {old_name} → {new_name}")
                
                # Update ForeignKey constraints that reference old table names
                print("\n🔄 Updating ForeignKey constraints...")
                
                # Update foreign keys in team_memberships_anthropic
                fk_updates = [
                    # Update foreign key to users_anthropic
                    ("""
                        ALTER TABLE team_memberships_anthropic 
                        DROP CONSTRAINT IF EXISTS team_memberships_anthropic_user_id_fkey;
                    """, """
                        ALTER TABLE team_memberships_anthropic 
                        ADD CONSTRAINT team_memberships_anthropic_user_id_fkey 
                        FOREIGN KEY (user_id) REFERENCES users_anthropic(id);
                    """),
                    # Update foreign key to teams_anthropic
                    ("""
                        ALTER TABLE team_memberships_anthropic 
                        DROP CONSTRAINT IF EXISTS team_memberships_anthropic_team_id_fkey;
                    """, """
                        ALTER TABLE team_memberships_anthropic 
                        ADD CONSTRAINT team_memberships_anthropic_team_id_fkey 
                        FOREIGN KEY (team_id) REFERENCES teams_anthropic(id);
                    """),
                ]
                
                for drop_query, add_query in fk_updates:
                    try:
                        conn.execute(text(drop_query))
                        conn.execute(text(add_query))
                        print("✅ Updated ForeignKey constraints")
                    except Exception as e:
                        print(f"⚠️  ForeignKey update warning: {e}")
                
                # Commit transaction
                trans.commit()
                print("\n✅ Migration completed successfully!")
                
            except Exception as e:
                trans.rollback()
                print(f"\n❌ Migration failed: {e}")
                raise
        
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("=" * 60)
    print("Convonet-Anthropic Table Rename Migration")
    print("=" * 60)
    print("\nThis will rename all convonet tables to include 'anthropic' suffix.")
    print("Make sure you have a database backup before proceeding!\n")
    
    response = input("Do you want to proceed? (yes/no): ")
    if response.lower() != 'yes':
        print("Migration cancelled.")
        sys.exit(0)
    
    rename_tables()

