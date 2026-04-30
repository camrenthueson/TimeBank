import streamlit as st
from supabase import create_client
import datetime
import pytz
from streamlit_autorefresh import st_autorefresh

# Refresh every 60 seconds (60,000 milliseconds)
# 'key' can be anything; it just tracks the counter
count = st_autorefresh(interval=6000, key="fivedatarefresh")

icon_url = "https://github.com/camrenthueson/TimeBank/raw/main/icon%20green.png"

# We use an empty placeholder to inject the HTML at the very top of the app body
st.components.v1.html(
    f"""
    <script>
        window.parent.document.title = "Time Bank";
        var link = window.parent.document.querySelector("link[rel*='apple-touch-icon']") || window.parent.document.createElement('link');
        link.type = 'image/x-icon';
        link.rel = 'apple-touch-icon';
        link.href = '{icon_url}';
        window.parent.document.getElementsByTagName('head')[0].appendChild(link);
    </script>
    """,
    height=0,
)


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


st.markdown("<h1 style='text-align: center;'>Time Bank</h1>", unsafe_allow_html=True)

# 1. Fetch Data (Shifts and Adjustments)
# Fetch shifts
response = supabase.table("shifts").select("*").order("created_at", desc=True).execute()
shifts = response.data

# Fetch adjustments
adj_response = supabase.table("adjustments").select("*").execute()
adj_total = sum(a['amount'] for a in adj_response.data)

# 2. Calculate Totals
active_shift = next((s for s in shifts if s['clock_out'] is None), None)
# Use a default of 0.0 for s['delta'] if it's None to prevent crashes
bank_total = sum(s.get('delta') or 0.0 for s in shifts)
final_bank = bank_total + adj_total

# 3. Display Main Metric
# Set the hex color: Green for positive/zero, Red for negative
bank_color = "#28a745" if final_bank >= 0 else "#dc3545"

# Display the bank as a large, colored header
st.markdown(
    f"<h1 style='text-align: center; color: {bank_color}; font-size: 55px; margin-top: 0;'>"
    f"{format_hours(final_bank)}"
    f"</h1>", 
    unsafe_allow_html=True
)

st.divider()

# 4. Clock In/Out Logic
if not active_shift:
    # --- NEW SLIDER LOGIC ---
    st.write("### Ready to start?")
    minutes_ago = st.slider("Started how many minutes ago?", 0, 120, 0, step=5)
    
    if st.button("Clock In", type="primary", use_container_width=True):
        # Calculate the actual start time based on the slider
        now_local = datetime.datetime.now(local_tz)
        actual_start = now_local - datetime.timedelta(minutes=minutes_ago)
        
        supabase.table("shifts").insert({
            "clock_in": actual_start.isoformat()
        }).execute()
        st.rerun()
else:
    # 1. Parse the current clock-in time
    in_time = datetime.datetime.fromisoformat(active_shift['clock_in']).astimezone(local_tz)
    today_str = in_time.strftime('%Y-%m-%d')

    # 2. Calculate how much you've already worked TODAY (excluding current shift)
    today_shifts = [s for s in shifts if s['clock_in'].startswith(today_str) and s['clock_out'] is not None]
    already_worked_today = sum(s['total_hours'] for s in today_shifts)

    # 3. Calculate remaining time needed to hit 8 hours
    hours_left_to_eight = 8.0 - already_worked_today
    
    # If you've already worked 8 hours, the projection should just be 'now' 
    # or show you're in 'overtime' mode.
    projected_out = in_time + datetime.timedelta(hours=max(0, hours_left_to_eight))

    # 4. Display the info
    st.info(f"Clocked in at: **{in_time.strftime('%I:%M %p')}**")
    
    if already_worked_today > 0:
        st.write(f"Already worked today: **{format_hours(already_worked_today).replace('+', '')}**")

    if hours_left_to_eight <= 0:
        st.success(f"✨ You've hit your 8 hours! Everything now is pure bank.")
    else:
        st.success(f"Projected 8-hour mark: **{projected_out.strftime('%I:%M %p')}**")

    # 5. Live progress calculation
    now = datetime.datetime.now(local_tz)
    current_session = (now - in_time).total_seconds() / 3600
    st.write(f"Current session: **{format_hours(current_session).replace('+', '')}**")
    st.write(f"Total for today: **{format_hours(already_worked_today + current_session).replace('+', '')}**")

    if st.button("Clock Out", type="secondary", use_container_width=True):
        out_time = datetime.datetime.now(local_tz)
        duration = (out_time - in_time).total_seconds() / 3600
        
        # 1. Find other shifts from TODAY
        today_str = out_time.strftime('%Y-%m-%d')
        
        # Filter shifts that started today and are already finished
        today_shifts = [s for s in shifts if s['clock_in'].startswith(today_str) and s['clock_out'] is not None]
        
        # 2. Calculate previous hours worked today
        prev_hours_today = sum(s['total_hours'] for s in today_shifts)
        total_hours_today = prev_hours_today + duration
        
        # 3. Delta Logic: 
        # If this is the FIRST shift of the day, delta is (Total - 8).
        # If we already clocked out once today, the -8 was already applied, 
        # so this shift's delta is just the full duration.
        if prev_hours_today > 0:
            delta = duration # The -8 was already "paid" by the first shift
        else:
            delta = total_hours_today - 8.0

        supabase.table("shifts").update({
            "clock_out": out_time.isoformat(),
            "total_hours": round(duration, 2),
            "delta": round(delta, 2)
        }).eq("id", active_shift['id']).execute()
        st.rerun()

# 5. Manual Adjustment Form
with st.expander("➕ Add Manual Adjustment"):
    with st.form("adj_form", clear_on_submit=True):
        # 1. Date Picker
        adj_date = st.date_input("Date of Adjustment", value=datetime.datetime.now(local_tz).date())
        
        # 2. H/M Inputs side-by-side
        col1, col2 = st.columns(2)
        with col1:
            adj_h = st.number_input("Hours", min_value=0, step=1, value=0)
        with col2:
            adj_m = st.number_input("Minutes", min_value=0, max_value=59, step=1, value=0)
        
        # 3. Type Selection (Gain or Loss)
        adj_type = st.radio("Adjustment Type", ["Add to Bank (+)", "Subtract from Bank (-)"], horizontal=True)
        
        adj_reason = st.text_input("Reason", placeholder="e.g., Training, Forgot to clock in...")

        if st.form_submit_button("Apply to Bank"):
            # Convert H/M to a single decimal value
            decimal_value = adj_h + (adj_m / 60)
            
            # Make it negative if that's what was selected
            if "Subtract" in adj_type:
                decimal_value = -decimal_value
            
            if decimal_value != 0:
                # We save the adjustment with the chosen date
                # We format the date to match your shift timestamps for the history grouping
                timestamp = datetime.datetime.combine(adj_date, datetime.time(12, 0)).isoformat()
                
                supabase.table("adjustments").insert({
                    "amount": decimal_value,
                    "reason": adj_reason,
                    "created_at": timestamp # This ensures it shows up in history correctly
                }).execute()
                st.rerun()

# 6. History Table (Grouped by Day)
if shifts or adj_response.data:
    st.write("### Daily Summary")
    
    daily_logs = {}

    # 1. Process Shifts
    for s in shifts:
        if s['clock_out']:
            date_str = datetime.datetime.fromisoformat(s['clock_in']).strftime('%b %d, %Y')
            
            if date_str not in daily_logs:
                daily_logs[date_str] = {'delta': 0.0}
            
            daily_logs[date_str]['delta'] += s['delta']

    # 2. Process Adjustments
    for a in adj_response.data:
        if 'created_at' in a and a['created_at']:
            date_str = datetime.datetime.fromisoformat(a['created_at']).strftime('%b %d, %Y')
            
            if date_str not in daily_logs:
                daily_logs[date_str] = {'delta': 0.0}
            
            daily_logs[date_str]['delta'] += a['amount']

    # 3. Sort and Format for Display
    sorted_dates = sorted(
        daily_logs.keys(), 
        key=lambda x: datetime.datetime.strptime(x, '%b %d, %Y'), 
        reverse=True
    )

    history_data = []
    for date in sorted_dates:
        totals = daily_logs[date]
        history_data.append({
            "Date": date,
            "Daily Bank Impact": format_hours(totals['delta'])
        })

    st.table(history_data)
