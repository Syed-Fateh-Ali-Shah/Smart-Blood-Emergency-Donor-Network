import sqlite3, math, os, re, random
from datetime import datetime, timedelta, date
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory, g
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "blood.db")
app = Flask(__name__, static_folder=os.path.join(BASE, "static"))
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-in-production")
ESCALATE_SECONDS = int(os.environ.get("ESCALATE_SECONDS", "60"))  # wait before next donor wave
MIN_GAP_DAYS = 90  # minimum days between donations
OPEN = ("Active", "Donors Contacted", "Partially Fulfilled")

COMPAT = {  # recipient -> compatible donor groups
    "A+": ["A+", "A-", "O+", "O-"], "A-": ["A-", "O-"], "B+": ["B+", "B-", "O+", "O-"],
    "B-": ["B-", "O-"], "AB+": ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"],
    "AB-": ["A-", "B-", "AB-", "O-"], "O+": ["O+", "O-"], "O-": ["O-"]}
HOSP = {"PIMS Hospital": ("Islamabad", 33.7050, 73.0527), "Polyclinic Hospital": ("Islamabad", 33.6938, 73.0651),
        "Shifa International": ("Islamabad", 33.6990, 73.0780), "Holy Family Hospital": ("Rawalpindi", 33.6330, 73.0630),
        "Benazir Bhutto Hospital": ("Rawalpindi", 33.6420, 73.0670), "Civil Hospital": ("Rawalpindi", 33.6007, 73.0679)}
AREAS = {"F-10 Islamabad": ("Islamabad", 33.6940, 73.0120), "G-9 Islamabad": ("Islamabad", 33.6860, 73.0310),
         "I-8 Islamabad": ("Islamabad", 33.6650, 73.0750), "Blue Area": ("Islamabad", 33.7100, 73.0560),
         "Saddar Rawalpindi": ("Rawalpindi", 33.5970, 73.0480), "Satellite Town": ("Rawalpindi", 33.6370, 73.0680),
         "Chaklala": ("Rawalpindi", 33.6050, 73.0930), "Bahria Town": ("Rawalpindi", 33.5200, 73.1200)}

# ---------- db helpers ----------
def _c():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c
def qa(sql, a=()):
    c = _c(); r = [dict(x) for x in c.execute(sql, a).fetchall()]; c.close(); return r
def q1(sql, a=()):
    r = qa(sql, a); return r[0] if r else None
def ex(sql, a=()):
    c = _c(); cur = c.execute(sql, a); c.commit(); i = cur.lastrowid; c.close(); return i
def now(): return datetime.now().isoformat(timespec="seconds")
def jerr(m, c=400): return jsonify(error=m), c
def km(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))
def notify(uid, rid, msg): ex("insert into notifications(user_id,request_id,message,created_at) values(?,?,?,?)", (uid, rid, msg, now()))

SCHEMA = """
create table if not exists users(id integer primary key, name text, email text unique, pw text, role text, phone text, status text default 'active');
create table if not exists donors(user_id integer primary key, blood_group text, area text, city text, lat real, lng real, last_donation text, available integer default 1, total_donations integer default 0, response_rate real default 0.5);
create table if not exists requests(id integer primary key, requester_id integer, patient text, blood_group text, units_required integer, units_arranged integer default 0, hospital text, city text, lat real, lng real, required_before text, urgency text, description text, verification_status text default 'pending', status text default 'Pending Verification', radius real default 10, created_at text, fulfilled_at text, last_wave_at text);
create table if not exists responses(id integer primary key, donor_id integer, request_id integer, match_score real, distance real, status text default 'notified', notified_at text, response_time text, donation_confirmed integer default 0);
create table if not exists notifications(id integer primary key, user_id integer, request_id integer, message text, created_at text, is_read integer default 0);
create table if not exists reports(id integer primary key, request_id integer, reporter_id integer, reason text, created_at text);
"""

def seed():
    if q1("select 1 x from users"): return
    random.seed(7)
    def user(n, e, p, r, ph): return ex("insert into users(name,email,pw,role,phone) values(?,?,?,?,?)", (n, e, p, r, ph))
    h = lambda p: generate_password_hash(p)
    user("Admin", "admin@demo.com", h("admin123"), "admin", "0300-0000001")
    user("Coordinator Sara", "coord@demo.com", h("coord123"), "coordinator", "0300-0000002")
    rq = user("Ali Raza", "req@demo.com", h("req123"), "requester", "0300-1234567")
    dh = h("donor123")
    first = ["Ahmed", "Bilal", "Hina", "Usman", "Ayesha", "Zain", "Fatima", "Hamza", "Sana", "Omar", "Maryam", "Talha"]
    last = ["Khan", "Malik", "Butt", "Shah", "Iqbal", "Chaudhry", "Raza", "Qureshi"]
    groups = ["O+"] * 9 + ["B+"] * 8 + ["A+"] * 7 + ["AB+"] * 3 + ["O-"] * 2 + ["A-"] * 2 + ["B-"] * 2 + ["AB-"]
    for i in range(45):
        uid = user(f"{random.choice(first)} {random.choice(last)}", f"donor{i+1}@demo.com", dh, "donor", f"03{random.randint(0,4)}{random.randint(10000000,99999999)}")
        a = random.choice(list(AREAS)); city, lat, lng = AREAS[a]
        ld = None if random.random() < .25 else (date.today() - timedelta(days=random.randint(20, 300))).isoformat()
        ex("insert into donors values(?,?,?,?,?,?,?,?,?,?)", (uid, random.choice(groups), a, city, lat + random.uniform(-.01, .01), lng + random.uniform(-.01, .01), ld, int(random.random() < .85), random.randint(0, 6), round(random.uniform(.2, .95), 2)))
    for i in range(10):  # historical completed requests so the dashboard shows patterns
        hn = random.choice(list(HOSP)); city, lat, lng = HOSP[hn]; ago = datetime.now() - timedelta(days=random.randint(1, 20), hours=random.randint(0, 8))
        u = random.choice([1, 2])
        bg = random.choice(["B+", "O+", "A+", "B+", "O-", "AB+"])
        rid = ex("insert into requests(requester_id,patient,blood_group,units_required,units_arranged,hospital,city,lat,lng,required_before,urgency,description,verification_status,status,created_at,fulfilled_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (rq, "Patient", bg, u, u, hn, city, lat, lng, (ago + timedelta(hours=12)).isoformat(timespec="seconds"), random.choice(["critical", "urgent", "normal"]), "Past request", "verified", "Completed", ago.isoformat(timespec="seconds"), (ago + timedelta(minutes=random.randint(25, 240))).isoformat(timespec="seconds")))
        for d in random.sample(qa("select user_id from donors where blood_group in (%s)" % ",".join("?" * len(COMPAT[bg])), COMPAT[bg]), u):
            ex("insert into responses(donor_id,request_id,match_score,distance,status,notified_at,response_time,donation_confirmed) values(?,?,?,?,?,?,?,1)", (d["user_id"], rid, 70, 5, "donated", ago.isoformat(timespec="seconds"), (ago + timedelta(minutes=random.randint(3, 40))).isoformat(timespec="seconds")))

def init():
    c = _c(); c.executescript(SCHEMA); c.commit(); c.close(); seed()

# ---------- matching & escalation ----------
def rank(r, radius, exclude):
    ids = COMPAT[r["blood_group"]]
    rows = qa("select u.id uid,u.name,d.* from donors d join users u on u.id=d.user_id where u.status='active' and d.available=1 and d.blood_group in (%s)" % ",".join("?" * len(ids)), ids)
    out = []
    for d in rows:
        if d["uid"] in exclude or d["uid"] == r["requester_id"]: continue
        gap = (date.today() - date.fromisoformat(d["last_donation"])).days if d["last_donation"] else 999
        dist = km(r["lat"], r["lng"], d["lat"], d["lng"])
        if gap < MIN_GAP_DAYS or dist > radius: continue
        exact = 5 if d["blood_group"] == r["blood_group"] else 0
        score = 50 * (1 - dist / radius) + 20 * min(gap / 180, 1) + 25 * d["response_rate"] + exact
        out.append((round(score, 1), round(dist, 1), d))
    return sorted(out, key=lambda x: -x[0])

def wave(rid, n):
    r = q1("select * from requests where id=?", (rid,))
    done = {x["donor_id"] for x in qa("select donor_id from responses where request_id=?", (rid,))}
    picks = rank(r, r["radius"], done)[:n]
    for score, dist, d in picks:
        ex("insert into responses(donor_id,request_id,match_score,distance,notified_at) values(?,?,?,?,?)", (d["uid"], rid, score, dist, now()))
        notify(d["uid"], rid, f"URGENT {r['blood_group']} BLOOD REQUIRED - {r['hospital']}, approx {dist} km away, {r['units_required']} unit(s), needed within {r['required_before'].replace('T',' ')}")
    ex("update requests set last_wave_at=?, status=case when status='Active' then 'Donors Contacted' else status end where id=?", (now(), rid))
    return len(picks)

def escalate(rid):
    """Top 5 -> next 10 -> widen radius. Stops once enough donors have accepted."""
    r = q1("select * from requests where id=?", (rid,))
    if not r or r["status"] not in OPEN: return 0
    pending_acc = q1("select count(*) c from responses where request_id=? and status='accepted'", (rid,))["c"]
    if r["units_arranged"] + pending_acc >= r["units_required"]: return 0
    first = q1("select count(*) c from responses where request_id=?", (rid,))["c"] == 0
    n = wave(rid, 5 if first else 10)
    while n == 0 and r["radius"] < 50:
        r["radius"] += 10; ex("update requests set radius=? where id=?", (r["radius"], rid)); n = wave(rid, 10)
    return n

def tick():
    for r in qa("select * from requests where status in ('Pending Verification','Active','Donors Contacted','Partially Fulfilled')"):
        if datetime.fromisoformat(r["required_before"]) < datetime.now():
            ex("update requests set status='Expired' where id=?", (r["id"],))
            ex("update responses set status='expired' where request_id=? and status='notified'", (r["id"],))
            notify(r["requester_id"], r["id"], f"Your {r['blood_group']} request at {r['hospital']} expired.")
        elif r["status"] in OPEN and r["last_wave_at"] and (datetime.now() - datetime.fromisoformat(r["last_wave_at"])).total_seconds() >= ESCALATE_SECONDS:
            escalate(r["id"])

# ---------- auth ----------
def auth(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u = q1("select * from users where id=?", (session.get("uid"),)) if session.get("uid") else None
            if not u or u["status"] != "active": return jerr("Please log in", 401)
            if roles and u["role"] not in roles: return jerr("Not allowed", 403)
            g.user = u; return f(*a, **k)
        return w
    return deco
def staff(): return g.user["role"] in ("coordinator", "admin")
def owner_or_staff(r): return staff() or r["requester_id"] == g.user["id"]

def me_payload(u):
    o = {k: u[k] for k in ("id", "name", "email", "role", "phone")}
    if u["role"] == "donor": o["donor"] = q1("select * from donors where user_id=?", (u["id"],))
    return o

@app.get("/")
def home(): return send_from_directory(app.static_folder, "index.html")

@app.get("/api/meta")
def meta(): return jsonify(groups=list(COMPAT), hospitals=list(HOSP), areas=list(AREAS), cities=["Islamabad", "Rawalpindi"])

@app.post("/api/register")
def register():
    d = request.get_json(silent=True) or {}
    role, name, email = d.get("role"), str(d.get("name", "")).strip(), str(d.get("email", "")).strip().lower()
    pw, ph = str(d.get("password", "")), str(d.get("phone", "")).strip()
    if role not in ("requester", "donor"): return jerr("Choose requester or donor")
    if not name or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email): return jerr("Enter your name and a valid email")
    if len(pw) < 6: return jerr("Password must be at least 6 characters")
    if not re.fullmatch(r"[0-9+\- ]{10,16}", ph): return jerr("Enter a valid phone number")
    if q1("select 1 x from users where email=?", (email,)): return jerr("Email already registered", 409)
    if role == "donor":
        ld = d.get("last_donation") or None
        try:
            if ld: date.fromisoformat(ld)
        except ValueError: return jerr("Invalid last donation date")
        if d.get("blood_group") not in COMPAT or d.get("area") not in AREAS: return jerr("Choose blood group and area")
    uid = ex("insert into users(name,email,pw,role,phone) values(?,?,?,?,?)", (name, email, generate_password_hash(pw), role, ph))
    if role == "donor":
        city, lat, lng = AREAS[d["area"]]
        ex("insert into donors(user_id,blood_group,area,city,lat,lng,last_donation) values(?,?,?,?,?,?,?)", (uid, d["blood_group"], d["area"], city, lat, lng, ld))
    session["uid"] = uid
    return jsonify(me_payload(q1("select * from users where id=?", (uid,))))

@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    u = q1("select * from users where email=?", (str(d.get("email", "")).strip().lower(),))
    if not u or not check_password_hash(u["pw"], str(d.get("password", ""))): return jerr("Wrong email or password", 401)
    if u["status"] != "active": return jerr("Account suspended", 403)
    session["uid"] = u["id"]; return jsonify(me_payload(u))

@app.post("/api/logout")
def logout(): session.clear(); return jsonify(ok=1)

@app.get("/api/me")
@auth()
def me(): return jsonify(me_payload(g.user))

# ---------- requests ----------
@app.post("/api/requests")
@auth("requester")
def req_create():
    d = request.get_json(silent=True) or {}
    try: units, hours = int(d.get("units")), int(d.get("hours"))
    except (TypeError, ValueError): return jerr("Units and hours must be numbers")
    bg, hosp, urg = d.get("blood_group"), d.get("hospital"), d.get("urgency")
    if bg not in COMPAT or hosp not in HOSP or urg not in ("critical", "urgent", "normal"): return jerr("Check blood group, hospital and urgency")
    if not 1 <= units <= 10 or not 1 <= hours <= 168: return jerr("Units must be 1-10 and hours 1-168")
    if q1("select 1 x from requests where requester_id=? and blood_group=? and hospital=? and status in ('Pending Verification','Active','Donors Contacted','Partially Fulfilled')", (g.user["id"], bg, hosp)):
        return jerr("You already have an open request for this blood group at this hospital", 409)
    city, lat, lng = HOSP[hosp]
    rid = ex("insert into requests(requester_id,patient,blood_group,units_required,hospital,city,lat,lng,required_before,urgency,description,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?)",
             (g.user["id"], str(d.get("patient", ""))[:80], bg, units, hosp, city, lat, lng, (datetime.now() + timedelta(hours=hours)).isoformat(timespec="seconds"), urg, str(d.get("description", ""))[:300], now()))
    for s in qa("select id from users where role='coordinator'"): notify(s["id"], rid, f"New {urg} {bg} request at {hosp} needs verification.")
    return jsonify(id=rid)

@app.get("/api/requests")
@auth("requester", "coordinator", "admin")
def req_list():
    tick(); w, a = [], []
    if g.user["role"] == "requester": w.append("requester_id=?"); a.append(g.user["id"])
    for k, col in (("blood_group", "blood_group"), ("hospital", "hospital"), ("status", "status"), ("urgency", "urgency"), ("verification", "verification_status"), ("city", "city")):
        if request.args.get(k): w.append(f"{col}=?"); a.append(request.args[k])
    if request.args.get("date"): w.append("created_at like ?"); a.append(request.args["date"] + "%")
    return jsonify(qa("select * from requests" + (" where " + " and ".join(w) if w else "") + " order by id desc limit 200", a))

@app.get("/api/requests/<int:rid>")
@auth("requester", "coordinator", "admin")
def req_get(rid):
    tick(); r = q1("select * from requests where id=?", (rid,))
    if not r or not owner_or_staff(r): return jerr("Not found", 404)
    resp = qa("select s.*,u.name,u.phone from responses s join users u on u.id=s.donor_id where request_id=? order by match_score desc", (rid,))
    for x in resp:
        if x["status"] not in ("accepted", "donated"): x.pop("phone")  # privacy: phone only after acceptance
    rq = q1("select name,phone from users where id=?", (r["requester_id"],))
    r["requester"] = {"name": rq["name"], "phone": rq["phone"] if staff() else None}
    r["responses"] = resp
    r["reports"] = q1("select count(*) c from reports where request_id=?", (rid,))["c"]
    return jsonify(r)

def _change(rid, allow_status, new, fn=None):
    r = q1("select * from requests where id=?", (rid,))
    if not r or not owner_or_staff(r): return None, jerr("Not found", 404)
    if r["status"] not in allow_status: return None, jerr(f"Not possible while request is '{r['status']}'", 409)
    ex("update requests set status=? where id=?", (new, rid)); return r, None

@app.post("/api/requests/<int:rid>/verify")
@auth("coordinator", "admin")
def verify(rid):
    r, e = _change(rid, ("Pending Verification",), "Active")
    if e: return e
    ex("update requests set verification_status='verified' where id=?", (rid,))
    notify(r["requester_id"], rid, "Your request is verified and donors are being contacted.")
    return jsonify(contacted=escalate(rid))

@app.post("/api/requests/<int:rid>/reject")
@auth("coordinator", "admin")
def reject(rid):
    r, e = _change(rid, ("Pending Verification", "Active", "Donors Contacted", "Partially Fulfilled"), "Rejected")
    if e: return e
    ex("update requests set verification_status='rejected' where id=?", (rid,))
    ex("update responses set status='cancelled' where request_id=? and status='notified'", (rid,))
    notify(r["requester_id"], rid, "Your request was rejected by a coordinator."); return jsonify(ok=1)

@app.post("/api/requests/<int:rid>/cancel")
@auth("requester", "coordinator", "admin")
def cancel(rid):
    r, e = _change(rid, ("Pending Verification", "Active", "Donors Contacted", "Partially Fulfilled"), "Cancelled")
    if e: return e
    ex("update responses set status='cancelled' where request_id=? and status in ('notified','accepted')", (rid,)); return jsonify(ok=1)

@app.post("/api/requests/<int:rid>/complete")
@auth("requester", "coordinator", "admin")
def complete(rid):
    r, e = _change(rid, ("Fulfilled", "Partially Fulfilled"), "Completed")
    if e: return e
    ex("update responses set status='cancelled' where request_id=? and status in ('notified','accepted')", (rid,)); return jsonify(ok=1)

@app.post("/api/requests/<int:rid>/escalate")
@auth("coordinator", "admin")
def esc(rid): return jsonify(contacted=escalate(rid))

@app.post("/api/requests/<int:rid>/report")
@auth()
def report(rid):
    if not q1("select 1 x from requests where id=?", (rid,)): return jerr("Not found", 404)
    ex("insert into reports(request_id,reporter_id,reason,created_at) values(?,?,?,?)", (rid, g.user["id"], str((request.get_json(silent=True) or {}).get("reason", "Suspicious"))[:200], now()))
    if q1("select count(*) c from reports where request_id=?", (rid,))["c"] >= 2:
        ex("update requests set verification_status='suspicious' where id=?", (rid,))
    return jsonify(ok=1)

# ---------- donor side ----------
@app.get("/api/offers")
@auth("donor")
def offers():
    tick()
    return jsonify(qa("select s.id,s.request_id,s.match_score,s.distance,s.status,s.notified_at,r.blood_group,r.hospital,r.city,r.units_required,r.urgency,r.required_before,r.description,r.verification_status,r.status req_status from responses s join requests r on r.id=s.request_id where s.donor_id=? order by s.id desc", (g.user["id"],)))

@app.post("/api/responses/<int:sid>/respond")
@auth("donor")
def respond(sid):
    s = q1("select * from responses where id=? and donor_id=?", (sid, g.user["id"]))
    if not s or s["status"] != "notified": return jerr("This offer is no longer open", 409)
    r = q1("select * from requests where id=?", (s["request_id"],))
    if r["status"] not in OPEN: return jerr("This request is closed", 409)
    acc = bool((request.get_json(silent=True) or {}).get("accept"))
    ex("update responses set status=?,response_time=? where id=?", ("accepted" if acc else "declined", now(), sid))
    ex("update donors set response_rate=round(0.8*response_rate+0.2*?,3) where user_id=?", (1 if acc else 0, g.user["id"]))
    if acc: notify(r["requester_id"], r["id"], f"{g.user['name']} accepted your {r['blood_group']} request at {r['hospital']}. Contact details are now visible.")
    return jsonify(ok=1)

@app.post("/api/donor/profile")
@auth("donor")
def donor_profile():
    d = request.get_json(silent=True) or {}
    ld = d.get("last_donation") or None
    try:
        if ld: date.fromisoformat(ld)
    except ValueError: return jerr("Invalid date")
    if d.get("area") not in AREAS: return jerr("Choose an area")
    city, lat, lng = AREAS[d["area"]]
    ex("update donors set available=?,last_donation=?,area=?,city=?,lat=?,lng=? where user_id=?", (1 if d.get("available") else 0, ld, d["area"], city, lat, lng, g.user["id"]))
    return jsonify(ok=1)

@app.post("/api/responses/<int:sid>/confirm")
@auth("requester", "coordinator", "admin")
def confirm(sid):
    s = q1("select * from responses where id=?", (sid,))
    r = q1("select * from requests where id=?", (s["request_id"],)) if s else None
    if not r or not owner_or_staff(r): return jerr("Not found", 404)
    if s["status"] != "accepted": return jerr("Only accepted donors can be confirmed", 409)
    ex("update responses set status='donated',donation_confirmed=1 where id=?", (sid,))
    ex("update donors set total_donations=total_donations+1,last_donation=? where user_id=?", (date.today().isoformat(), s["donor_id"]))
    arr = r["units_arranged"] + 1
    if arr >= r["units_required"]:
        ex("update requests set units_arranged=?,status='Fulfilled',fulfilled_at=? where id=?", (arr, now(), r["id"]))
        ex("update responses set status='cancelled' where request_id=? and status='notified'", (r["id"],))  # stop extra notifications
    else:
        ex("update requests set units_arranged=?,status='Partially Fulfilled' where id=?", (arr, r["id"]))
    notify(s["donor_id"], r["id"], "Thank you! Your donation was confirmed.")
    notify(r["requester_id"], r["id"], f"{arr}/{r['units_required']} units arranged for your request.")
    return jsonify(ok=1)

@app.get("/api/donors")
@auth("coordinator", "admin")
def donors():
    rows = qa("select u.id,u.name,u.status,d.blood_group,d.area,d.city,d.last_donation,d.available,d.total_donations,d.response_rate from donors d join users u on u.id=d.user_id order by u.id")
    f = request.args; out = []
    for x in rows:
        gap = (date.today() - date.fromisoformat(x["last_donation"])).days if x["last_donation"] else None
        x["eligible"] = bool(x["available"]) and (gap is None or gap >= MIN_GAP_DAYS) and x["status"] == "active"
        if f.get("blood_group") and x["blood_group"] != f["blood_group"]: continue
        if f.get("city") and x["city"] != f["city"]: continue
        if f.get("available") in ("0", "1") and str(x["available"]) != f["available"]: continue
        if f.get("eligible") in ("0", "1") and str(int(x["eligible"])) != f["eligible"]: continue
        if f.get("donated_before") and x["last_donation"] and x["last_donation"] > f["donated_before"]: continue
        out.append(x)
    return jsonify(out)

# ---------- notifications, admin, stats ----------
@app.get("/api/notifications")
@auth()
def notes():
    rows = qa("select * from notifications where user_id=? order by id desc limit 50", (g.user["id"],))
    if request.args.get("read"): ex("update notifications set is_read=1 where user_id=?", (g.user["id"],))
    return jsonify(rows)

@app.get("/api/admin/users")
@auth("admin")
def users(): return jsonify(qa("select id,name,email,role,phone,status from users order by id"))

@app.post("/api/admin/users/<int:uid>/toggle")
@auth("admin")
def toggle(uid):
    if uid == g.user["id"]: return jerr("You cannot suspend yourself")
    ex("update users set status=case when status='active' then 'suspended' else 'active' end where id=?", (uid,)); return jsonify(ok=1)

@app.get("/api/admin/reports")
@auth("admin")
def reports(): return jsonify(qa("select p.*,u.name reporter,r.blood_group,r.hospital,r.verification_status from reports p join users u on u.id=p.reporter_id join requests r on r.id=p.request_id order by p.id desc"))

@app.get("/api/stats")
@auth()
def stats():
    tick(); n = lambda s, a=(): q1(s, a)["c"]
    total = n("select count(*) c from requests"); done = n("select count(*) c from requests where status in ('Fulfilled','Completed')")
    judged = n("select count(*) c from requests where status not in ('Pending Verification','Rejected','Cancelled')")
    grp = lambda col: qa(f"select {col} k,count(*) n from requests group by {col} order by n desc")
    return jsonify(total=total, active=n("select count(*) c from requests where status in ('Active','Donors Contacted','Partially Fulfilled')"),
        completed=done, critical=n("select count(*) c from requests where urgency='critical' and status in ('Active','Donors Contacted','Partially Fulfilled')"),
        donors=n("select count(*) c from donors"), available=n("select count(*) c from donors where available=1"),
        donations=n("select count(*) c from responses where donation_confirmed=1"),
        avg_fulfil_min=round(q1("select avg((julianday(fulfilled_at)-julianday(created_at))*1440) c from requests where fulfilled_at is not null")["c"] or 0),
        avg_response_min=round(q1("select avg((julianday(response_time)-julianday(notified_at))*1440) c from responses where response_time is not null")["c"] or 0, 1),
        fulfil_rate=round(100 * done / judged) if judged else 0,
        by_group=grp("blood_group"), by_hospital=grp("hospital"), by_city=grp("city"))

if __name__ == "__main__":
    init()
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)), debug=False)
