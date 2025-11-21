# FusionPBX Dialplan Configuration for Twilio Transfers

## Problem

Twilio sends SIP INVITE to `sip:2001@136.115.41.45`, but FusionPBX abandons the call with `WRONG_CALL_STATE` because the dialplan doesn't know how to route external SIP calls to extensions.

## Solution: Configure FusionPBX Dialplan

FusionPBX needs a dialplan entry to route external SIP calls (from Twilio) to internal extensions.

### Step 1: Access FusionPBX Dialplan Manager

1. Login to FusionPBX: `https://136.115.41.45`
2. Navigate to: **Advanced → Dialplan Manager**

### Step 2: Create Dialplan Entry for External SIP Calls

**Option A: Create New Dialplan (Recommended)**

1. Click **"Add"** to create a new dialplan
2. Configure as follows:

   **Basic Settings:**
   - **Context**: `public` (for external calls)
   - **Name**: `Twilio-to-Extensions`
   - **Enabled**: `True`
   - **Description**: `Route Twilio SIP calls to extensions`

   **Dialplan Details:**
   - **Destination Number**: `^(\d+)$` (matches any extension number)
   - **Caller ID Name**: (leave empty or set to variable)
   - **Caller ID Number**: (leave empty or set to variable)

   **Actions:**
   - **Action**: `transfer`
   - **Destination**: `${destination_number}@internal`
   - **Order**: `100` (or appropriate priority)

   **Advanced:**
   - **Continue**: `false`
   - **Enabled**: `true`

**Option B: Edit Existing Public Dialplan**

1. Find the existing `public` context dialplan
2. Add a new entry:
   - **Destination Number**: `^2001$` (or `^(\d+)$` for all extensions)
   - **Action**: `transfer`
   - **Destination**: `2001@internal` (or `${destination_number}@internal`)

### Step 3: Verify Dialplan

Test the dialplan:

```bash
# On FusionPBX server
fs_cli -x "dialplan xml public 2001"
```

Should return XML showing the dialplan routing to `2001@internal`.

### Step 4: Test with fs_cli

```bash
# Test dialplan routing
fs_cli -x "originate sofia/internal/2001@internal &echo"
```

## Alternative: Use SIP Trunk with Outbound Routes

If dialplan doesn't work, configure Twilio as a SIP trunk:

1. **Go to**: Advanced → Trunks → Add
2. **Trunk Type**: SIP
3. **Trunk Name**: `Twilio`
4. **SIP Profile**: `external`
5. **Register**: `false`
6. **Gateway**: Configure with Twilio IP ranges

Then create outbound route:
1. **Go to**: Advanced → Outbound Routes → Add
2. **Route Name**: `Twilio-to-Extensions`
3. **Dial Patterns**: `^2001$` (or `^(\d+)$`)
4. **Trunk**: Select `Twilio` trunk
5. **Gateway**: Your FusionPBX gateway

## Verification

After configuration, test the transfer:

1. Trigger transfer from WebRTC voice assistant
2. Check FusionPBX logs:
   ```bash
   tail -f /var/log/freeswitch/freeswitch.log | grep 2001
   ```
3. Should see:
   - SIP INVITE received
   - Call routed to `2001@internal`
   - Extension 2001 rings
   - Call answered

## Expected Log Flow (After Fix)

```
[INFO] receiving invite from 54.172.60.0:5060
[DEBUG] State NEW -> INIT
[DEBUG] Dialplan: public -> 2001@internal
[DEBUG] State INIT -> RINGING
[NOTICE] Extension 2001 is ringing
[DEBUG] State RINGING -> ANSWERED
[NOTICE] Call answered by extension 2001
```

Instead of:
```
[WARNING] Abandoned
[NOTICE] Hangup [CS_NEW] [WRONG_CALL_STATE]
```

## Troubleshooting

### Issue: Dialplan Not Matching

**Check dialplan:**
```bash
fs_cli -x "dialplan show public"
# Look for your dialplan entry
```

**Test pattern matching:**
```bash
fs_cli -x "regex ^2001$ ^(\d+)$"
# Should return: true
```

### Issue: Extension Not Found

**Check extension exists:**
```bash
fs_cli -x "user_data 2001@internal var"
# Should return extension data
```

**Check extension is registered:**
```bash
fs_cli -x "sofia status"
# Look for 2001@internal in registered users
```

### Issue: Context Routing Fails

**Check internal context dialplan:**
```bash
fs_cli -x "dialplan xml internal 2001"
# Should show routing to extension 2001
```

## Quick Reference

**SIP URI Format:**
- ✅ Correct: `sip:2001@136.115.41.45;transport=udp` (for Twilio)
- ❌ Wrong: `sip:2001@internal;transport=udp` (Twilio can't resolve `internal`)

**FusionPBX Routing:**
- External calls come in via `public` context
- Dialplan must transfer to `2001@internal` context
- Internal context routes to registered extension

