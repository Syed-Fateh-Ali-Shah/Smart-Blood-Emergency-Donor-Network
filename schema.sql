-- Database schema (SQLite). The app creates these tables automatically on first run.
create table if not exists users(id integer primary key, name text, email text unique, pw text, role text, phone text, status text default 'active');

create table if not exists donors(user_id integer primary key, blood_group text, area text, city text, lat real, lng real, last_donation text, available integer default 1, total_donations integer default 0, response_rate real default 0.5);

create table if not exists requests(id integer primary key, requester_id integer, patient text, blood_group text, units_required integer, units_arranged integer default 0, hospital text, city text, lat real, lng real, required_before text, urgency text, description text, verification_status text default 'pending', status text default 'Pending Verification', radius real default 10, created_at text, fulfilled_at text, last_wave_at text);

create table if not exists responses(id integer primary key, donor_id integer, request_id integer, match_score real, distance real, status text default 'notified', notified_at text, response_time text, donation_confirmed integer default 0);

create table if not exists notifications(id integer primary key, user_id integer, request_id integer, message text, created_at text, is_read integer default 0);

create table if not exists reports(id integer primary key, request_id integer, reporter_id integer, reason text, created_at text);
