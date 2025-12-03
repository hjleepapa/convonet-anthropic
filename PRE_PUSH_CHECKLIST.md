# Pre-Push Checklist for Convonet-Anthropic

## ✅ Completed Changes

### 1. LLM Migration
- [x] Replaced OpenAI LLM with Anthropic Claude
- [x] Updated `langchain-openai` → `langchain-anthropic` in requirements.txt
- [x] Updated model from `gpt-4-turbo-preview` → `claude-3-5-sonnet-20241022`
- [x] Updated logging from `openai` → `anthropic`

### 2. TTS Migration
- [x] Replaced OpenAI TTS with Deepgram Aura-2 TTS
- [x] Updated `webrtc_voice_server.py` to use Deepgram TTS
- [x] Added `synthesize_speech` method to `deepgram_service.py`

### 3. Project Cleanup
- [x] Removed `blog_project/` directory
- [x] Removed `blnd_todo/` directory
- [x] Removed `vapi_todo/` directory
- [x] Removed `1. Main/` directory (duplicate)
- [x] Removed `archive/` directory
- [x] Removed empty `components/`, `instance/`, `recordings/` directories
- [x] Removed Flask-Login dependencies (using JWT auth)

### 4. Database Table Names
- [x] Updated all table names to include `_anthropic` suffix:
  - `users_convonet` → `users_anthropic`
  - `teams_convonet` → `teams_anthropic`
  - `team_memberships_convonet` → `team_memberships_anthropic`
  - `todos_convonet` → `todos_anthropic`
  - `reminders_convonet` → `reminders_anthropic`
  - `calendar_events_convonet` → `calendar_events_anthropic`
  - `call_recordings_convonet` → `call_recordings_anthropic`
- [x] Updated ForeignKey references
- [x] Updated documentation
- [x] Created migration script: `migrations/rename_tables_to_anthropic.py`

## ⚠️ Before Pushing to GitHub

### Security Check
- [x] `.env` file is in `.gitignore` ✅
- [x] `credentials.json` is in `.gitignore` ✅
- [x] `token.pickle` is in `.gitignore` ✅
- [ ] **Review Composio API keys** in `render.yaml` and `CONVONET_DEPLOYMENT_CONFIG.md`
  - If these are public/shared keys, they're fine
  - If these are private keys, consider using environment variables instead

### Files to Review
- [ ] Check if `.env` file exists and is not tracked by git
- [ ] Check if `credentials.json` exists and is not tracked by git
- [ ] Verify no hardcoded secrets in code (all use `os.getenv()`)

### Documentation
- [x] Updated `convonet/README.md` with Anthropic and Deepgram info
- [x] Updated `convonet/CONVONET_DEPLOYMENT_CONFIG.md` with new table names
- [x] Updated `convonet/templates/convonet_tech_spec.html` with new table names
- [ ] Consider updating root `README.md` (currently very basic)

### Migration Scripts
- [x] Created `migrations/create_anthropic_tables.py` ⭐ **RECOMMENDED**
- [x] Created `migrations/rollback_table_renames.py` (if needed)
- [x] Created `migrations/rename_tables_to_anthropic.py` (deprecated, not recommended)
- [x] Created `migrations/README_MIGRATIONS.md` (documentation)
- [ ] **Important**: Run `create_anthropic_tables.py` to create new tables (keeps old ones)
- [ ] Test migration script on a backup/staging database first

### Testing Checklist
- [ ] Test Anthropic LLM integration
- [ ] Test Deepgram TTS integration
- [ ] Test database queries with new table names
- [ ] Verify no references to old table names remain

## 🚀 Ready to Push?

1. **Verify sensitive files are not tracked:**
   ```bash
   git status
   # Ensure .env, credentials.json, token.pickle are not listed
   ```

2. **Review changes:**
   ```bash
   git diff
   # Review all changes before committing
   ```

3. **Commit with descriptive message:**
   ```bash
   git add .
   git commit -m "Migrate to Anthropic Claude LLM and Deepgram TTS, update table names to _anthropic suffix"
   ```

4. **Push to GitHub:**
   ```bash
   git push origin main
   ```

## 📝 Post-Push Tasks

1. **Run database migration (CREATE new tables, keep old ones):**
   ```bash
   # First, if tables were renamed, rollback:
   python migrations/rollback_table_renames.py
   
   # Then create new tables:
   python migrations/create_anthropic_tables.py
   ```
   
   **Note**: The create script will:
   - Keep original `*_convonet` tables intact
   - Create new empty `*_anthropic` tables with same structure
   - Update foreign keys automatically

2. **Update environment variables** in deployment platform (Render.com):
   - Ensure `ANTHROPIC_API_KEY` is set
   - Ensure `DEEPGRAM_API_KEY` is set
   - Remove `OPENAI_API_KEY` - no longer needed (using Claude LLM and Deepgram TTS)

3. **Test deployment:**
   - Verify application starts successfully
   - Test voice assistant functionality
   - Test database operations with new table names

