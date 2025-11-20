"""
Migration script to CREATE new _anthropic tables based on existing _convonet tables.
This keeps the old _convonet tables intact and creates new _anthropic tables with the same structure.

This script:
1. Gets the table structure from existing _convonet tables
2. Creates new _anthropic tables with the same structure
3. Does NOT copy data (tables start empty)
4. Does NOT drop or rename existing tables
"""

import os
import sys
from sqlalchemy import create_engine, text, inspect
from dotenv import load_dotenv

load_dotenv()

def get_table_create_statement(conn, table_name):
    """Get CREATE TABLE statement for a table"""
    # Get table structure using PostgreSQL-specific query
    query = text("""
        SELECT 
            column_name,
            data_type,
            character_maximum_length,
            is_nullable,
            column_default,
            udt_name
        FROM information_schema.columns
        WHERE table_schema = 'public' 
        AND table_name = :table_name
        ORDER BY ordinal_position;
    """)
    
    columns = conn.execute(query, {"table_name": table_name}).fetchall()
    
    if not columns:
        return None
    
    # Build CREATE TABLE statement
    create_parts = [f'CREATE TABLE "{table_name}" (']
    col_defs = []
    
    for col in columns:
        col_name = col[0]
        data_type = col[1]
        max_length = col[2]
        is_nullable = col[3]
        default = col[4]
        udt_name = col[5]
        
        # Map PostgreSQL types
        if udt_name == 'uuid':
            type_str = 'UUID'
        elif udt_name == 'varchar':
            type_str = f'VARCHAR({max_length})' if max_length else 'VARCHAR'
        elif udt_name == 'text':
            type_str = 'TEXT'
        elif udt_name == 'boolean':
            type_str = 'BOOLEAN'
        elif udt_name == 'timestamp':
            type_str = 'TIMESTAMP WITH TIME ZONE'
        elif udt_name == 'integer':
            type_str = 'INTEGER'
        else:
            type_str = data_type.upper()
        
        col_def = f'    "{col_name}" {type_str}'
        
        if default:
            col_def += f' DEFAULT {default}'
        
        if is_nullable == 'NO':
            col_def += ' NOT NULL'
        
        col_defs.append(col_def)
    
    create_parts.append(',\n'.join(col_defs))
    create_parts.append(');')
    
    return '\n'.join(create_parts)

def get_primary_keys(conn, table_name):
    """Get primary key constraints for a table"""
    query = text("""
        SELECT 
            a.attname
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = :table_name::regclass
        AND i.indisprimary;
    """)
    
    try:
        result = conn.execute(query, {"table_name": table_name}).fetchall()
        return [row[0] for row in result]
    except:
        return []

def get_foreign_keys(conn, table_name):
    """Get foreign key constraints for a table"""
    query = text("""
        SELECT
            tc.constraint_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
        AND tc.table_name = :table_name;
    """)
    
    try:
        result = conn.execute(query, {"table_name": table_name}).fetchall()
        return result
    except:
        return []

def get_indexes(conn, table_name):
    """Get indexes for a table"""
    query = text("""
        SELECT
            indexname,
            indexdef
        FROM pg_indexes
        WHERE tablename = :table_name
        AND schemaname = 'public';
    """)
    
    try:
        result = conn.execute(query, {"table_name": table_name}).fetchall()
        return result
    except:
        return []

def create_anthropic_tables():
    """Create new _anthropic tables based on existing _convonet tables"""
    
    db_uri = os.getenv("DB_URI")
    if not db_uri:
        print("❌ DB_URI environment variable not set")
        sys.exit(1)
    
    # Table mappings
    table_mappings = [
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
                print("🔄 Starting creation of new _anthropic tables...")
                print("📋 This will create new tables based on existing _convonet tables\n")
                
                for old_name, new_name in table_mappings:
                    # Check if source table exists
                    check_query = text("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = 'public' 
                            AND table_name = :table_name
                        );
                    """)
                    
                    result = conn.execute(check_query, {"table_name": old_name}).fetchone()
                    source_exists = result[0] if result else False
                    
                    if not source_exists:
                        print(f"⚠️  Source table {old_name} does not exist, skipping...")
                        continue
                    
                    # Check if target table already exists
                    result = conn.execute(check_query, {"table_name": new_name}).fetchone()
                    target_exists = result[0] if result else False
                    
                    if target_exists:
                        print(f"⚠️  Target table {new_name} already exists, skipping...")
                        continue
                    
                    # Use PostgreSQL's CREATE TABLE ... LIKE to copy structure
                    print(f"📋 Creating {new_name} based on {old_name}...")
                    
                    # First, get foreign keys from source table to know what to update
                    source_fks = get_foreign_keys(conn, old_name)
                    
                    # Create table with LIKE (exclude constraints - we'll add them manually)
                    # INCLUDING DEFAULTS and INCLUDING INDEXES, but NOT INCLUDING CONSTRAINTS
                    create_query = text(f'CREATE TABLE "{new_name}" (LIKE "{old_name}" INCLUDING DEFAULTS INCLUDING INDEXES);')
                    conn.execute(create_query)
                    
                    # Get all constraints from the source table to drop them from new table
                    # (in case they were copied anyway)
                    constraint_query = text("""
                        SELECT constraint_name
                        FROM information_schema.table_constraints
                        WHERE table_schema = 'public'
                        AND table_name = :table_name
                        AND constraint_type = 'FOREIGN KEY';
                    """)
                    existing_fks = conn.execute(constraint_query, {"table_name": new_name}).fetchall()
                    
                    # Drop any foreign keys that might have been copied
                    for fk_row in existing_fks:
                        constraint_name = fk_row[0]
                        drop_fk = text(f'ALTER TABLE "{new_name}" DROP CONSTRAINT IF EXISTS "{constraint_name}";')
                        try:
                            conn.execute(drop_fk)
                        except Exception as e:
                            # Ignore errors - constraint might not exist
                            pass
                    
                    # Recreate foreign keys pointing to _anthropic tables
                    # Process in order: create FKs only after referenced tables exist
                    fks_to_create = []
                    for fk in source_fks:
                        constraint_name, column_name, foreign_table, foreign_column = fk
                        
                        # Map foreign table names from _convonet to _anthropic
                        if foreign_table.endswith('_convonet'):
                            new_foreign_table = foreign_table.replace('_convonet', '_anthropic')
                            fks_to_create.append((column_name, new_foreign_table, foreign_column, constraint_name))
                    
                    # Create foreign keys (only if target table already exists)
                    for column_name, new_foreign_table, foreign_column, old_constraint_name in fks_to_create:
                        # Check if target table exists (must be created earlier in the loop)
                        check_target = text("""
                            SELECT EXISTS (
                                SELECT FROM information_schema.tables 
                                WHERE table_schema = 'public' 
                                AND table_name = :table_name
                            );
                        """)
                        target_exists = conn.execute(check_target, {"table_name": new_foreign_table}).fetchone()[0]
                        
                        if target_exists:
                            # Generate new constraint name
                            new_constraint_name = f"{new_name}_{column_name}_fkey"
                            
                            # Check if constraint already exists
                            check_constraint = text("""
                                SELECT EXISTS (
                                    SELECT FROM information_schema.table_constraints
                                    WHERE table_schema = 'public'
                                    AND table_name = :table_name
                                    AND constraint_name = :constraint_name
                                );
                            """)
                            constraint_exists = conn.execute(
                                check_constraint, 
                                {"table_name": new_name, "constraint_name": new_constraint_name}
                            ).fetchone()[0]
                            
                            if not constraint_exists:
                                add_fk = text(f'''
                                    ALTER TABLE "{new_name}" 
                                    ADD CONSTRAINT "{new_constraint_name}" 
                                    FOREIGN KEY ("{column_name}") 
                                    REFERENCES "{new_foreign_table}"("{foreign_column}");
                                ''')
                                try:
                                    conn.execute(add_fk)
                                    print(f"  ✅ Created FK: {column_name} → {new_foreign_table}")
                                except Exception as e:
                                    print(f"  ⚠️  FK creation warning: {e}")
                            else:
                                print(f"  ℹ️  FK {new_constraint_name} already exists, skipping")
                        else:
                            print(f"  ⚠️  Target table {new_foreign_table} doesn't exist yet, FK will be created later")
                    
                    print(f"✅ Created table {new_name}")
                
                # Commit transaction
                trans.commit()
                print("\n✅ Migration completed successfully!")
                print("📝 New _anthropic tables created (empty, no data copied)")
                print("📝 Original _convonet tables remain unchanged")
                
            except Exception as e:
                trans.rollback()
                print(f"\n❌ Migration failed: {e}")
                print("\n💡 Tip: If you see 'transaction is aborted' errors, the transaction was rolled back.")
                print("   You can safely run the script again - it will skip existing tables.")
                import traceback
                traceback.print_exc()
                raise
        
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("=" * 60)
    print("Create New Anthropic Tables Migration")
    print("=" * 60)
    print("\nThis will CREATE new _anthropic tables based on existing _convonet tables.")
    print("The old _convonet tables will remain unchanged.")
    print("New tables will be empty (no data copied).\n")
    
    response = input("Do you want to proceed? (yes/no): ")
    if response.lower() != 'yes':
        print("Migration cancelled.")
        sys.exit(0)
    
    create_anthropic_tables()

