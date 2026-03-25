import os
import pandas as pd
from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, 'Train_details_22122017.csv')
df = pd.read_csv(CSV_PATH)
df.columns = df.columns.str.strip()
df['SEQ'] = pd.to_numeric(df['SEQ'], errors='coerce')
df['Train No'] = pd.to_numeric(df['Train No'], errors='coerce')

df = df.dropna(subset=['SEQ', 'Train No'])

def get_delta(t_str):
    try:
        fmt = "%H:%M:%S"
        t = datetime.strptime(str(t_str), fmt)
        return timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
    except:
        return timedelta(0)

def format_td(td):
    hours, remainder = divmod(td.total_seconds(), 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{int(hours)}h {int(minutes)}m"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/autocomplete')
def autocomplete():
    q = request.args.get('q', '').upper()
    mask = df['Station Code'].str.contains(q, na=False) | df['Station Name'].str.contains(q, na=False, case=False)
    matches = df[mask][['Station Code', 'Station Name']].drop_duplicates().head(10)
    return jsonify(matches.to_dict('records'))

@app.route('/get_stops')
def get_stops():
    try:
        t_no = int(request.args.get('train_no'))
        s_seq = int(request.args.get('start_seq'))
        e_seq = int(request.args.get('end_seq'))
        
        # Filtering with guaranteed integers
        stops = df[(df['Train No'] == t_no) & (df['SEQ'] >= s_seq) & (df['SEQ'] <= e_seq)].sort_values('SEQ')
        return jsonify(stops[['Station Name', 'Arrival time', 'Departure Time']].to_dict('records'))
    except Exception as e:
        print(f"Error in get_stops: {e}")
        return jsonify([])

@app.route('/search', methods=['POST'])
def search():
    data = request.json
    src, dst = data.get('source', '').upper(), data.get('destination', '').upper()

    # --- DIRECT ---
    s_data = df[df['Station Code'] == src][['Train No', 'Train Name', 'SEQ', 'Departure Time', 'Station Name']]
    d_data = df[df['Station Code'] == dst][['Train No', 'SEQ', 'Arrival time', 'Station Name']]
    direct_df = pd.merge(s_data, d_data, on='Train No', suffixes=('_s', '_d'))
    direct_df = direct_df[direct_df['SEQ_s'] < direct_df['SEQ_d']]

    # --- INDIRECT ---
    t1_all = pd.merge(df, s_data, on='Train No', suffixes=('', '_src'))
    t1_after = t1_all[t1_all['SEQ'] > t1_all['SEQ_src']]
    t2_all = pd.merge(df, d_data, on='Train No', suffixes=('', '_dst'))
    t2_before = t2_all[t2_all['SEQ'] < t2_all['SEQ_dst']]

    junc_df = pd.merge(t1_after, t2_before, on='Station Code', suffixes=('_1', '_2'))
    junc_df = junc_df[junc_df['Train No_1'] != junc_df['Train No_2']]

    indirect = []
    for _, row in junc_df.iterrows():
        t1_arr_j = get_delta(row['Arrival time_1'])
        t2_dep_j = get_delta(row['Departure Time_2'])

        wait_td = t2_dep_j - t1_arr_j
        if wait_td.total_seconds() < 0: wait_td += timedelta(days=1)
        
        if wait_td.total_seconds() >= 7200:
            indirect.append({
                "junc": row['Station Name_1'], "wait": format_td(wait_td),
                "total_sec": wait_td.total_seconds(), # Simplified for sorting
                "leg1": {"no": int(row['Train No_1']), "name": row['Train Name_1'], "from": row['Station Name_src'], "to": row['Station Name_1'], "dep": str(row['Departure Time_src']), "arr": str(row['Arrival time_1']), "s_seq": int(row['SEQ_src']), "e_seq": int(row['SEQ_1'])},
                "leg2": {"no": int(row['Train No_2']), "name": row['Train Name_2'], "from": row['Station Name_1'], "to": row['Station Name_dst'], "dep": str(row['Departure Time_2']), "arr": str(row['Arrival time_dst']), "s_seq": int(row['SEQ_2']), "e_seq": int(row['SEQ_dst'])}
            })

    if indirect:
        indirect = sorted(indirect, key=lambda x: x['total_sec'])
        indirect[0]['best_value'] = True

    return jsonify({"direct": direct_df.to_dict('records'), "indirect": indirect[:10]})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)