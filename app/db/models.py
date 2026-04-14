"""
Supabase table definitions — for reference only.
These tables must be created in your Supabase dashboard (SQL Editor).

Run the SQL in supabase_schema.sql to create them.
"""

# Tables:
#   customers        — phone_number, full_name, document_number, status, preferred_language
#   appointments     — customer_id, appointment_date, appointment_type, status, location
#   calls            — customer_id, twilio_call_sid, direction, started_at, ended_at, final_status, transcript_summary, action_taken
#   call_events      — call_id, event_type, payload_json, created_at
#   call_scripts     — name, description, welcome_greeting, system_prompt, active
