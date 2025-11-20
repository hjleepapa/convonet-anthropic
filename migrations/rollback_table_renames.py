"""
Rollback script to rename tables back from _anthropic to _convonet
This undoes the rename_tables_to_anthropic.py migration.
"""

import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

def rollback_table_renames():
    """Rename all anthropic tables back to convonet"""
    
    db_uri = os.getenv("DB_URI")
    if not db_uri:
        print("❌ DB_URI environment variable not set")
        sys.exit(1)
    
    # Table rename mappings (reverse of the original migration)
    table_renames = [
        ("users_anthropic", "users_convonet"),
        ("teams_anthropic", "teams_convonet"),
        ("team_memberships_anthropic", "team_memberships_convonet"),
        ("todos_anthropic", "todos_convonet"),
        ("reminders_anthropic", "reminders_convonet"),
        ("calendar_events_anthropic", "calendar_events_convonet"),
        ("call_recordings_anthropic", "call_recordings_convonet"),
    ]
    
    try:
        engine = create_engine(db_uri)
        
        with engine.connect() as conn:
            # Start transaction
            trans = conn.begin()
            
            try:
                print("🔄 Starting rollback - renaming tables back to _convonet...")
                
                # Check which tables exist and rename them back
                for old_name, new_name in table_renames:
                    # Check if old table (anthropic) exists
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
                    
                    # Check if new table (convonet) already exists
                    result = conn.execute(check_query, {"table_name": new_name}).fetchone()
                    new_table_exists = result[0] if result else False
                    
                    if new_table_exists:
                        print(f"⚠️  Table {new_name} already exists, cannot rollback {old_name}...")
                        print(f"    You may need to drop {old_name} manually if it's a duplicate")
                        continue
                    
                    # Rename the table back
                    rename_query = text(f'ALTER TABLE "{old_name}" RENAME TO "{new_name}";')
                    conn.execute(rename_query)
                    print(f"✅ Renamed {old_name} → {new_name}")
                
                # Update ForeignKey constraints back to original
                print("\n🔄 Updating ForeignKey constraints...")
                
                # Update foreign keys in team_memberships_convonet
                fk_updates = [
                    # Update foreign key to users_convonet
                    ("""
                        ALTER TABLE team_memberships_convonet 
                        DROP CONSTRAINT IF EXISTS team_memberships_convonet_user_id_fkey;
                    """, """
                        ALTER TABLE team_memberships_convonet 
                        ADD CONSTRAINT team_memberships_convonet_user_id_fkey 
                        FOREIGN KEY (user_id) REFERENCES users_convonet(id);
                    """),
                    # Update foreign key to teams_convonet
                    ("""
                        ALTER TABLE team_memberships_convonet 
                        DROP CONSTRAINT IF EXISTS team_memberships_convonet_team_id_fkey;
                    """, """
                        ALTER TABLE team_memberships_convonet 
                        ADD CONSTRAINT team_memberships_convonet_team_id_fkey 
                        FOREIGN KEY (team_id) REFERENCES teams_convonet(id);
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
                print("\n✅ Rollback completed successfully!")
                print("📝 Tables have been renamed back to _convonet suffix")
                
            except Exception as e:
                trans.rollback()
                print(f"\n❌ Rollback failed: {e}")
                raise
        
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("=" * 60)
    print("Convonet-Anthropic Table Rename ROLLBACK")
    print("=" * 60)
    print("\nThis will rename all _anthropic tables back to _convonet.")
    print("This undoes the rename_tables_to_anthropic.py migration.\n")
    
    response = input("Do you want to proceed with rollback? (yes/no): ")
    if response.lower() != 'yes':
        print("Rollback cancelled.")
        sys.exit(0)
    
    rollback_table_renames()

