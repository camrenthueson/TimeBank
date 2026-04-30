import streamlit as st
from supabase import create_client
import datetime
import pytz
from streamlit_autorefresh import st_autorefresh

# Refresh every 2 seconds for live tracking
count = st_autorefresh(interval=2000, key="fivedatarefresh")

icon_url = "https://github.com/camrenthueson/TimeBank/raw/main/icon%20green.png"

# Inject Custom Page Title and Favicon
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

# Setup Supabase
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

def format_hours(decimal_hours):
    hours = int(abs(decimal_hours))
    minutes = int((abs(decimal_hours) * 60) % 60)
    sign = "+" if decimal_hours >= 0 else "-"
    return f"{sign}{hours}h {minutes}m"

st.markdown("<h1 style='text-align: center;'>Time Bank</h1>", unsafe_allow_html=True)

# 1. Fetch Data
response = supabase.table("shifts").select("*").order("created_at", desc=True).execute()
shifts = response.data

adj_response = supabase.table("adjustments").select("*").execute()
adj_total = sum(a['amount'] for a in adj_response.data)

# 2. Calculate Totals
active_shift = next((s for s in shifts if s['clock_out'] is None), None)
bank_total = sum(s.get('delta') or 0.0 for s in shifts)
final_bank = bank_total + adj_total

# 3. Display Main Metric
bank_color = "#28a745" if final_bank >= 0 else "#dc3545"
st.markdown(
    f"<h1 style='text-align: center; color: {bank_color}; font-size: 55px; margin-top: 0;'>"
    f"{format_hours(final_bank)}"
    f"</h1>", 
    unsafe_allow_html=True
)

st.divider()

# 4. Clock In/Out Logic
if not active_shift:
    # --- SECTION: CLOCK IN ---
    st.write("### Ready to start?")
    with st.expander("Adjust start time"):
        in_minutes_ago = st.slider("Minutes ago:", 0, 120, 0, step=5, key="in_slider")
        
    # WRAPPER FOR IN
    st.markdown('<div class="in-button">', unsafe_allow_html=True)
    if st.button("Clock In", use_container_width=True, key="btn_in"):
        now_local = datetime.datetime.now(local_tz)
        actual_start = now_local - datetime.timedelta(minutes=in_minutes_ago)
        supabase.table("shifts").insert({"clock_in": actual_start.isoformat()}).execute()
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

else:
    # --- THIS LINE WAS MISSING (The fix for the NameError) ---
    in_time = datetime.datetime.fromisoformat(active_shift['clock_in']).astimezone(local_tz)
    
    today_str = in_time.strftime('%Y-%m-%d')
    today_shifts = [s for s in shifts if s['clock_in'].startswith(today_str) and s['clock_out'] is not None]
    already_worked_today = sum(s['total_hours'] for s in today_shifts)
    hours_left_to_eight = 8.0 - already_worked_today
    projected_out = in_time + datetime.timedelta(hours=max(0, hours_left_to_eight))

    st.info(f"Clocked in at: **{in_time.strftime('%I:%M %p')}**")
    
    if hours_left_to_eight <= 0:
        st.success(f"✨ You've hit your 8 hours!")
    else:
        st.success(f"Projected 8-hour mark: **{projected_out.strftime('%I:%M %p')}**")

    st.write("---")
    with st.expander("Adjust End Time"):
        out_minutes_ago = st.slider("Minutes ago:", 0, 120, 0, step=5, key="out_slider")
   
    # WRAPPER FOR OUT
    st.markdown('<div class="out-button">', unsafe_allow_html=True)
    if st.button("Clock Out", use_container_width=True, key="btn_out"):
        out_time = datetime.datetime.now(local_tz) - datetime.timedelta(minutes=out_minutes_ago)
        if out_time < in_time:
            out_time = in_time 
            
        duration = (out_time - in_time).total_seconds() / 3600
        prev_hours_today = sum(s['total_hours'] for s in today_shifts)
        total_hours_today = prev_hours_today + duration
        delta = duration if prev_hours_today > 0 else (total_hours_today - 8.0)

        supabase.table("shifts").update({
            "clock_out": out_time.isoformat(),
            "total_hours": round(duration, 2),
            "delta": round(delta, 2)
        }).eq("id", active_shift['id']).execute()
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # Progress Dashboard
    now = datetime.datetime.now(local_tz)
    current_session = (now - in_time).total_seconds() / 3600
    st.write("---")
    col1, col2 = st.columns(2)
    col1.metric("Current Session", format_hours(current_session).replace('+', ''))
    col2.metric("Total Today", format_hours(already_worked_today + current_session).replace('+', ''))

# 5. Manual Adjustment Form
with st.expander("➕ Add Manual Adjustment"):
    with st.form("adj_form", clear_on_submit=True):
        adj_date = st.date_input("Date of Adjustment", value=datetime.datetime.now(local_tz).date())
        col1, col2 = st.columns(2)
        adj_h = col1.number_input("Hours", min_value=0, step=1, value=0)
        adj_m = col2.number_input("Minutes", min_value=0, max_value=59, step=1, value=0)
        adj_type = st.radio("Adjustment Type", ["Add to Bank (+)", "Subtract from Bank (-)"], horizontal=True)
        adj_reason = st.text_input("Reason", placeholder="e.g., Training...")

        if st.form_submit_button("Apply to Bank"):
            decimal_value = adj_h + (adj_m / 60)
            if "Subtract" in adj_type: decimal_value = -decimal_value
            if decimal_value != 0:
                timestamp = datetime.datetime.combine(adj_date, datetime.time(12, 0)).isoformat()
                supabase.table("adjustments").insert({"amount": decimal_value, "reason": adj_reason, "created_at": timestamp}).execute()
                st.rerun()

# 6. History Table
if shifts or adj_response.data:
    st.write("### Daily Summary")
    daily_logs = {}
    for s in shifts:
        if s['clock_out']:
            d = datetime.datetime.fromisoformat(s['clock_in']).strftime('%b %d, %Y')
            daily_logs[d] = daily_logs.get(d, 0.0) + s['delta']
    for a in adj_response.data:
        if a.get('created_at'):
            d = datetime.datetime.fromisoformat(a['created_at']).strftime('%b %d, %Y')
            daily_logs[d] = daily_logs.get(d, 0.0) + a['amount']

    sorted_dates = sorted(daily_logs.keys(), key=lambda x: datetime.datetime.strptime(x, '%b %d, %Y'), reverse=True)
    history_data = [{"Date": d, "Daily Bank Impact": format_hours(daily_logs[d])} for d in sorted_dates]
    st.table(history_data)

# UI Settings & CSS
settings_data = supabase.table("settings").select("*").execute().data
settings_dict = {item['id']: item['value'] for item in settings_data}

saved_bg = settings_dict.get('bg_color', '#0e1117')
saved_in = settings_dict.get('in_btn_color', '#28a745')
saved_out = settings_dict.get('out_btn_color', '#dc3545')

with st.sidebar:
    st.write("### 🎨 Theme Settings")
    new_bg = st.color_picker("Background", saved_bg)
    new_in = st.color_picker("Clock In Button", saved_in)
    new_out = st.color_picker("Clock Out Button", saved_out)

    if (new_bg != saved_bg or new_in != saved_in or new_out != saved_out):
        supabase.table("settings").upsert([
            {"id": "bg_color", "value": new_bg},
            {"id": "in_btn_color", "value": new_in},
            {"id": "out_btn_color", "value": new_out}
        ]).execute()
        st.rerun()

# --- 3. Inject CSS with Specific Selectors ---
st.markdown(
    f"""
    <style>
    /* 1. Background Color */
    .stApp {{ background-color: {new_bg} !important; }}
    
    /* 2. Clock In Button Style */
    div.in-button button[kind="secondary"] {{
        background-color: {new_in} !important;
        color: white !important;
        border: 1px solid {new_in} !important;
    }}
    
    /* 3. Clock Out Button Style */
    div.out-button button[kind="secondary"] {{
        background-color: {new_out} !important;
        color: white !important;
        border: 1px solid {new_out} !important;
    }}

    /* 4. Ensure the text inside the buttons is white */
    div.in-button button p, div.out-button button p {{
        color: white !important;
        font-weight: bold !important;
    }}

    /* 5. Hover Effects */
    div.in-button button:hover, div.out-button button:hover {{
        opacity: 0.8 !important;
        border: 1px solid white !important;
    }}
    </style>
    """,
    unsafe_allow_html=True
)
