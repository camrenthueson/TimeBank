import streamlit as st
from supabase import create_client
import datetime
import pytz

local_tz = pytz.timezone("America/Denver")

# Setup
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)


def format_hours(decimal_hours):
    hours = int(abs(decimal_hours))
    minutes = int((abs(decimal_hours) * 60) % 60)
    sign = "+" if decimal_hours >= 0 else "-"
    return f"{sign}{hours}h {minutes}m"


st.title("⏱️ Time Bank")

# 1. Fetch Data (Shifts and Adjustments)
# Fetch shifts
response = supabase.table("shifts").select("*").order("created_at", desc=True).execute()
shifts = response.data

# Fetch adjustments
adj_response = supabase.table("adjustments").select("amount").execute()
adj_total = sum(a['amount'] for a in adj_response.data)

# 2. Calculate Totals
active_shift = next((s for s in shifts if s['clock_out'] is None), None)
bank_total = sum(s['delta'] for s in shifts if s['delta'] is not None)
final_bank = bank_total + adj_total

# 3. Display Main Metric
st.metric(
    label="Total Time Bank",
    value=format_hours(final_bank),
    delta=f"{final_bank:.2f} decimal hrs"
)

st.divider()

# 4. Clock In/Out Logic
if not active_shift:
    if st.button("Clock In", type="primary", use_container_width=True):
        # Use timezone-aware UTC for consistency
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        supabase.table("shifts").insert({"clock_in": now_iso}).execute()
        st.rerun()
else:
    # Parse the clock-in time
    in_time = datetime.datetime.fromisoformat(active_shift['clock_in'])
    projected_out = in_time + datetime.timedelta(hours=8)

    st.info(f"Clocked in at: **{in_time.astimezone().strftime('%I:%M %p')}**")
    st.success(f"Projected 8-hour mark: **{projected_out.astimezone().strftime('%I:%M %p')}**")

    # Live progress calculation
    now = datetime.datetime.now(datetime.timezone.utc)
    elapsed = (now - in_time).total_seconds() / 3600
    st.write(f"Current session: **{format_hours(elapsed).replace('+', '')}**")

    if st.button("Clock Out", type="secondary", use_container_width=True):
        out_time = datetime.datetime.now(datetime.timezone.utc)
        duration = (out_time - in_time).total_seconds() / 3600
        delta = duration - 8.0

        supabase.table("shifts").update({
            "clock_out": out_time.isoformat(),
            "total_hours": round(duration, 2),
            "delta": round(delta, 2)
        }).eq("id", active_shift['id']).execute()
        st.rerun()

# 5. Manual Adjustment Form
with st.expander("➕ Add Manual Adjustment"):
    with st.form("adj_form", clear_on_submit=True):
        adj_amount = st.number_input("Hours (use negative for under)", value=0.0, step=0.25)
        adj_reason = st.text_input("Reason", placeholder="Forgot to clock in...")

        if st.form_submit_button("Apply to Bank"):
            if adj_amount != 0:
                supabase.table("adjustments").insert({
                    "amount": adj_amount,
                    "reason": adj_reason
                }).execute()
                st.rerun()

# 6. History Table
if shifts:
    st.write("### Recent Shifts")
    history_data = []
    for s in shifts:
        if s['clock_out']:
            history_data.append({
                "Date": s['clock_in'][:10],
                "Duration": f"{s['total_hours']} hrs",
                "Bank Impact": format_hours(s['delta'])
            })
    st.table(history_data)
