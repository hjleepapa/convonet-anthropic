# Database Migration Scripts

## Overview

This directory contains migration scripts for managing Convonet-Anthropic database tables.

## Available Scripts

### 1. `create_anthropic_tables.py` ⭐ **RECOMMENDED**
**Creates new `*_anthropic` tables based on existing `*_convonet` tables.**

- ✅ Keeps original `*_convonet` tables intact
- ✅ Creates new empty `*_anthropic` tables with same structure
- ✅ Updates foreign keys to point to new tables
- ✅ Safe to run multiple times (skips existing tables)

**Usage:**
```bash
python migrations/create_anthropic_tables.py
```

**When to use:**
- First time setting up Anthropic tables
- When you want both old and new tables to coexist
- Recommended approach for production

---

### 2. `rollback_table_renames.py`
**Rolls back table renames from `*_anthropic` back to `*_convonet`.**

- Undoes the `rename_tables_to_anthropic.py` migration
- Only use if you accidentally ran the rename script

**Usage:**
```bash
python migrations/rollback_table_renames.py
```

**When to use:**
- If you accidentally renamed tables and want to restore original names
- Before running `create_anthropic_tables.py` if tables were renamed

---

### 3. `rename_tables_to_anthropic.py` ⚠️ **DEPRECATED**
**Renames existing `*_convonet` tables to `*_anthropic`.**

- ❌ **NOT RECOMMENDED** - This renames existing tables
- ❌ Loses original table names
- ⚠️ Use `rollback_table_renames.py` to undo

**Usage:**
```bash
python migrations/rename_tables_to_anthropic.py
```

**When to use:**
- Only if you want to completely replace old tables
- Not recommended for production

---

## Migration Workflow

### Recommended Workflow (Create New Tables)

1. **Ensure your application is running** (so models are loaded)
2. **Run the create script:**
   ```bash
   python migrations/create_anthropic_tables.py
   ```
3. **Verify tables were created:**
   ```sql
   SELECT table_name 
   FROM information_schema.tables 
   WHERE table_schema = 'public' 
   AND table_name LIKE '%_anthropic';
   ```
4. **Update your code** to use `*_anthropic` tables (already done)
5. **Deploy and test**

### If Tables Were Already Renamed (Rollback First)

1. **Rollback the rename:**
   ```bash
   python migrations/rollback_table_renames.py
   ```
2. **Then create new tables:**
   ```bash
   python migrations/create_anthropic_tables.py
   ```

## Table Mappings

| Old Table Name | New Table Name |
|----------------|----------------|
| `users_convonet` | `users_anthropic` |
| `teams_convonet` | `teams_anthropic` |
| `team_memberships_convonet` | `team_memberships_anthropic` |
| `todos_convonet` | `todos_anthropic` |
| `reminders_convonet` | `reminders_anthropic` |
| `calendar_events_convonet` | `calendar_events_anthropic` |
| `call_recordings_convonet` | `call_recordings_anthropic` |

## Notes

- All scripts require `DB_URI` environment variable
- Scripts use transactions - they rollback on error
- Foreign keys are automatically updated to point to new tables
- Indexes and constraints are preserved
- **No data is copied** - new tables start empty

## Troubleshooting

### Error: "Table already exists"
- The script will skip existing tables
- If you want to recreate, drop the table first:
  ```sql
  DROP TABLE IF EXISTS users_anthropic CASCADE;
  ```

### Error: "Source table does not exist"
- Make sure your original `*_convonet` tables exist
- Run Flask-Migrate or `db.create_all()` first if needed

### Foreign Key Errors
- The script automatically updates foreign keys
- If errors occur, check that all referenced tables exist

