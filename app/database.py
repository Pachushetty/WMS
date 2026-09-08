"""
EcoCycle AI — PostgreSQL Database Module
========================================

PostgreSQL database integration for:
    - User authentication (passwords hashed with Werkzeug scrypt)
    - Classification history logging
    - Disposal requests and locations
    - Collection requests and schedules
    - In-app notifications
"""

import os
import json
import math
import secrets
from datetime import datetime, date, timedelta
from pathlib import Path
from contextlib import contextmanager

# Load environment variables early
try:
    from dotenv import load_dotenv
    for env_path in [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]:
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
            break
    else:
        load_dotenv()
except ImportError:
    pass

import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash, check_password_hash

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set. PostgreSQL connection cannot be established.")


@contextmanager
def get_db_connection():
    """Yields a psycopg2 connection with RealDictCursor and safely closes it on exit."""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initializes the PostgreSQL database schema and seeds default data."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Users Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                location_area TEXT,
                location_pincode TEXT,
                location_address TEXT,
                location_lat DOUBLE PRECISION,
                location_lng DOUBLE PRECISION,
                location_updated_at TIMESTAMP WITH TIME ZONE
            )
        """)

        # 2. Classifications Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS classifications (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
                image_filename TEXT NOT NULL,
                object_name TEXT NOT NULL,
                condition TEXT NOT NULL,
                category TEXT NOT NULL,
                is_waste BOOLEAN NOT NULL,
                confidence REAL NOT NULL,
                probabilities_json TEXT NOT NULL,
                reason TEXT,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. Disposal Locations Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS disposal_locations (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                address TEXT NOT NULL,
                city TEXT DEFAULT 'Metro Area',
                latitude DOUBLE PRECISION NOT NULL,
                longitude DOUBLE PRECISION NOT NULL,
                phone TEXT,
                operating_hours TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 4. Disposal Requests Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS disposal_requests (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
                classification_id INTEGER NULL REFERENCES classifications (id) ON DELETE CASCADE,
                user_name TEXT NOT NULL,
                object_name TEXT NOT NULL,
                category TEXT NOT NULL,
                user_lat DOUBLE PRECISION NOT NULL,
                user_lng DOUBLE PRECISION NOT NULL,
                user_location_text TEXT,
                status TEXT NOT NULL DEFAULT 'Pending',
                assigned_location_id INTEGER NULL REFERENCES disposal_locations (id) ON DELETE SET NULL,
                admin_notes TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                image_url TEXT,
                admin_verified BOOLEAN NOT NULL DEFAULT FALSE,
                verified_at TIMESTAMP WITH TIME ZONE,
                target_date TEXT,
                target_time TEXT
            )
        """)

        # 5. Waste Collection Requests Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS collection_requests (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
                classification_id INTEGER NULL REFERENCES classifications (id) ON DELETE SET NULL,
                user_name TEXT NOT NULL,
                waste_type TEXT NOT NULL,
                quantity TEXT NOT NULL,
                pickup_lat DOUBLE PRECISION NOT NULL,
                pickup_lng DOUBLE PRECISION NOT NULL,
                pickup_location_text TEXT,
                address TEXT,
                note TEXT,
                status TEXT NOT NULL DEFAULT 'Pending',
                admin_notes TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                area TEXT,
                scheduled_day TEXT,
                scheduled_date TEXT,
                scheduled_time_start TEXT,
                scheduled_time_end TEXT
            )
        """)

        # 6. Notifications Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
                request_id INTEGER NULL REFERENCES disposal_requests (id) ON DELETE CASCADE,
                message TEXT NOT NULL,
                is_read BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 7. Collection Schedules Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS collection_schedules (
                id SERIAL PRIMARY KEY,
                area TEXT NOT NULL,
                pincode TEXT,
                collector_name TEXT DEFAULT 'EcoCycle Municipal Collector',
                day_of_week TEXT NOT NULL,
                time_start TEXT NOT NULL,
                time_end TEXT NOT NULL,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Ensure optional columns exist for seamless backwards compatibility
        migration_columns = [
            ("disposal_requests", "classification_id", "INTEGER REFERENCES classifications(id) ON DELETE CASCADE"),
            ("disposal_requests", "image_url", "TEXT"),
            ("disposal_requests", "admin_verified", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("disposal_requests", "verified_at", "TIMESTAMP WITH TIME ZONE"),
            ("disposal_requests", "target_date", "TEXT"),
            ("disposal_requests", "target_time", "TEXT"),
            ("collection_requests", "classification_id", "INTEGER REFERENCES classifications(id) ON DELETE CASCADE"),
            ("collection_requests", "area", "TEXT"),
            ("collection_requests", "scheduled_day", "TEXT"),
            ("collection_requests", "scheduled_date", "TEXT"),
            ("collection_requests", "scheduled_time_start", "TEXT"),
            ("collection_requests", "scheduled_time_end", "TEXT"),
            ("collection_schedules", "pincode", "TEXT"),
            ("collection_schedules", "collector_name", "TEXT DEFAULT 'EcoCycle Municipal Collector'"),
            ("users", "location_area", "TEXT"),
            ("users", "location_pincode", "TEXT"),
            ("users", "location_address", "TEXT"),
            ("users", "location_lat", "DOUBLE PRECISION"),
            ("users", "location_lng", "DOUBLE PRECISION"),
            ("users", "location_updated_at", "TIMESTAMP WITH TIME ZONE"),
        ]
        for table, col, col_def in migration_columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_def}")
        conn.commit()

        # Seed sample collection schedules if empty
        cursor.execute("SELECT COUNT(*) AS count FROM collection_schedules")
        sched_count = cursor.fetchone()["count"]
        if sched_count == 0:
            sample_schedules = [
                ("Kotekar", "575025", "EcoCycle Coastal Fleet Alpha", "Monday", "09:00", "13:00", True),
                ("Indiranagar", "560038", "Indiranagar Green Team", "Wednesday", "08:30", "12:30", True),
                ("Whitefield", "560066", "Whitefield Eco Logistics", "Friday", "10:00", "14:00", True),
                ("Koramangala", "560034", "Koramangala Clean Squad", "Thursday", "09:00", "13:00", True),
                ("Metro Central", "110001", "Capital Clean Collective", "Tuesday", "09:00", "15:00", True),
            ]
            cursor.executemany("""
                INSERT INTO collection_schedules (area, pincode, collector_name, day_of_week, time_start, time_end, active)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, sample_schedules)
            conn.commit()

        # Seed default admin if no admin exists.
        # SECURITY: never hardcode a known admin password. Use ADMIN_PASSWORD
        # from the environment if provided, otherwise generate a strong random
        # one-time password and print it ONCE so it can be captured and changed.
        cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
        admin_row = cursor.fetchone()
        if not admin_row:
            admin_password = os.environ.get("ADMIN_PASSWORD")
            generated = False
            if not admin_password:
                admin_password = secrets.token_urlsafe(12)
                generated = True

            admin_email = os.environ.get("ADMIN_EMAIL", "admin@ecocycle.ai")
            admin_username = os.environ.get("ADMIN_USERNAME", "admin")

            admin_pwd_hash = generate_password_hash(admin_password, method="scrypt")
            cursor.execute("""
                INSERT INTO users (username, email, password_hash, role)
                VALUES (%s, %s, %s, 'admin')
            """, (admin_username, admin_email, admin_pwd_hash))
            conn.commit()

            print("=" * 70)
            print("Initial admin account created.")
            print(f"  Username: {admin_username}")
            print(f"  Email:    {admin_email}")
            if generated:
                print(f"  Password: {admin_password}  (auto-generated, one-time only)")
                print("  This password is NOT stored anywhere else — copy it now and")
                print("  change it after your first login. To set your own instead,")
                print("  set ADMIN_PASSWORD (and optionally ADMIN_EMAIL/ADMIN_USERNAME)")
                print("  in your .env before first run.")
            else:
                print("  Password: (taken from ADMIN_PASSWORD environment variable)")
            print("=" * 70)

        # Seed sample disposal locations if empty
        cursor.execute("SELECT COUNT(*) as count FROM disposal_locations")
        loc_count = cursor.fetchone()["count"]
        if loc_count == 0:
            sample_locations = [
                (
                    "Bangalore Ewaste Recycle Center",
                    "Hazardous",
                    "154, 4th A Cross Rd, Seethappa Layout, Chamundi Nagar, Bengaluru 560032",
                    "Bengaluru",
                    13.0288,
                    77.5655,
                    "Doorstep pickup service",
                    "Open 24 hours"
                ),
                (
                    "Saahas Waste Management",
                    "Universal",
                    "32, 5th B Cross, 16th Main Rd, BTM Layout, Bengaluru 560076",
                    "Bengaluru",
                    12.9166,
                    77.6101,
                    "1800 258 6676",
                    "Mon-Fri 9:30AM-6PM, Sat 9:30AM-4PM"
                ),
                (
                    "Dry Waste Collection Center",
                    "Recyclable",
                    "Milk Booth, Jeevan Griha, 2nd Phase, J.P. Nagar, Bengaluru 560078",
                    "Bengaluru",
                    12.9084,
                    77.5964,
                    "-",
                    "Varies"
                ),
                (
                    "WasteCycle - Doorstep Scrap Collection",
                    "Recyclable",
                    "1st Main, HAL, Kaggadasapura, Bengaluru 560017",
                    "Bengaluru",
                    12.9825,
                    77.679,
                    "63625 03005",
                    "Open 24 hours"
                ),
                (
                    "Escrappy Recyclers E-waste",
                    "Hazardous",
                    "Shushruti Nagar, Byraveshwara Industrial Estate, Bengaluru 560091",
                    "Bengaluru",
                    13.0247,
                    77.5108,
                    "93640 05055",
                    "Mon-Sat 9AM-6:30PM"
                ),
                (
                    "BBMP Waste Collection Centre",
                    "Universal",
                    "Devarachikkanahalli Rd, Begur, Bengaluru 560114",
                    "Bengaluru",
                    12.8778,
                    77.6205,
                    "-",
                    "Varies"
                ),
                (
                    "Bengaluru Solid Waste Management Ltd",
                    "Universal",
                    "Millers Tank Bund Rd, Vasanth Nagar, Bengaluru 560001",
                    "Bengaluru",
                    12.9935,
                    77.5897,
                    "99804 17644",
                    "Mon-Sat 10AM-7PM"
                ),
                (
                    "Maridi Bio Industries Pvt Ltd",
                    "Hazardous",
                    "Sunaga Arcade, Sampangi Rama Nagar, Bengaluru 560027",
                    "Bengaluru",
                    12.9688,
                    77.5756,
                    "-",
                    "Varies"
                ),
                (
                    "Saveeco Waste Management Pvt Ltd",
                    "Universal",
                    "Bannerghatta Main Rd, Gottigere, Bengaluru 560083",
                    "Bengaluru",
                    12.8557,
                    77.5962,
                    "72045 11222",
                    "Mon-Sat 10AM-6PM"
                ),
                (
                    "Electronic Waste Management (E-Waste)",
                    "Hazardous",
                    "Sun Pure Garden, Hanchya, Rammanahalli, Mysuru 570019",
                    "Mysuru",
                    12.2616,
                    76.683,
                    "94815 45728",
                    "Mon-Fri open 24 hrs, Sat-Sun closed"
                ),
                (
                    "Mysore Scrap Traders",
                    "Recyclable",
                    "3146 Convent Road, L. Mohalla, Tilak Nagar, Mysuru 570001",
                    "Mysuru",
                    12.3052,
                    76.6552,
                    "98804 44722",
                    "Open 24 hours"
                ),
                (
                    "Zero Waste Management Plant",
                    "Universal",
                    "Lokanayaka Nagar, Hebbal 1st Stage, Mysuru 570016",
                    "Mysuru",
                    12.3482,
                    76.6394,
                    "-",
                    "Varies"
                ),
                (
                    "Namma Mysore Foundation",
                    "Recyclable",
                    "1255 Krishnaraja Road, Krishnamurthy Puram, Mysuru 570014",
                    "Mysuru",
                    12.2871,
                    76.6436,
                    "98450 84416",
                    "Daily 9:30AM-6:30PM"
                ),
                (
                    "Mother Nature Waste Management & Recycling Industry",
                    "Universal",
                    "Baikampady Industrial Area, New Mangalore 575011",
                    "Mangaluru",
                    12.9475,
                    74.8219,
                    "90359 49904",
                    "Varies"
                ),
                (
                    "Mangala Resource Management Pvt Ltd",
                    "Universal",
                    "Sahyadri Campus, Adyar, Mangaluru 575007",
                    "Mangaluru",
                    12.8858,
                    74.9234,
                    "90197 02501",
                    "Varies"
                ),
                (
                    "MCC Solid Waste Management Plant",
                    "Universal",
                    "Vamanjoor, Mangaluru 575028",
                    "Mangaluru",
                    12.9184,
                    74.9026,
                    "-",
                    "Varies"
                ),
                (
                    "Poly Shakthi Recycling",
                    "Recyclable",
                    "Port Town, Industrial Area, Baikampady, Mangaluru 575011",
                    "Mangaluru",
                    12.9488,
                    74.8213,
                    "63618 56955",
                    "Open 24 hours"
                ),
                (
                    "Moogambigai Metal Refineries",
                    "Recyclable",
                    "Industrial Area Rd, New Mangalore, Baikampady 575011",
                    "Mangaluru",
                    12.9495,
                    74.824,
                    "99011 48952",
                    "Mon-Sat 9:30AM-6:30PM"
                ),
                (
                    "Dharwad Plastic Hubballi",
                    "Recyclable",
                    "Gokul Rd, Industrial Estate, Hubballi 580030",
                    "Hubballi",
                    15.3746,
                    75.124,
                    "85533 88821",
                    "Mon-Sat 9AM-9PM"
                ),
                (
                    "RecyclEarth Foundation",
                    "Universal",
                    "Anusharan Arcade, Vidya Nagar, Hubballi 580031",
                    "Hubballi",
                    15.3618,
                    75.136,
                    "0836 425 3769",
                    "Mon-Sat 10AM-4PM"
                ),
                (
                    "Go Green Associates",
                    "Universal",
                    "Tarihal Industrial Area, Hubballi 580026",
                    "Hubballi",
                    15.3356,
                    75.0838,
                    "-",
                    "Open 24 hours"
                ),
                (
                    "Ecologix Recycling",
                    "Recyclable",
                    "JB Mudakannavar Building, Raviwar Peth, Belagavi 590001",
                    "Belagavi",
                    15.8497,
                    74.4977,
                    "-",
                    "Mon 11AM-5:30PM, Tue-Sat 11AM-5PM"
                ),
                (
                    "Nuvicta Ecoplast Pvt Ltd",
                    "Recyclable",
                    "KIADB Industrial Area, Honaga, Belagavi 591156",
                    "Belagavi",
                    15.886,
                    74.559,
                    "-",
                    "Mon-Sat 9:30AM-5:30PM"
                ),
                (
                    "Kabadi Man",
                    "Universal",
                    "Shahu Nagar, Belagavi 590010",
                    "Belagavi",
                    15.871,
                    74.506,
                    "88611 83111",
                    "Varies"
                ),
                (
                    "Common Bio Medical Waste Treatment Facility",
                    "Hazardous",
                    "APMC Yard, Bagalkot 587103",
                    "Bagalkot",
                    16.1867,
                    75.6961,
                    "63647 64791",
                    "Varies"
                ),
                (
                    "The Shushrutha Bio-Medical Waste Management Society",
                    "Hazardous",
                    "KIADB Industrial Area, Machenahalli, Bhadravathi, Shivamogga 577222",
                    "Shivamogga",
                    13.842,
                    75.705,
                    "81822 46090",
                    "Varies"
                ),
                (
                    "Dry Waste Collection Center",
                    "Recyclable",
                    "Ring Rd, Jayapura, Tumakuru 572101",
                    "Tumakuru",
                    13.335,
                    77.101,
                    "-",
                    "Varies"
                ),
                (
                    "Epragathi Recycling",
                    "Hazardous",
                    "KIADB Industrial Area, Antharasanahalli, Tumakuru 572106",
                    "Tumakuru",
                    13.3575,
                    77.1105,
                    "-",
                    "Varies"
                ),
                (
                    "Balaji Rubber and Reclaims Pvt Ltd",
                    "Recyclable",
                    "Industrial Area, Satyamangala, Tumakuru 572104",
                    "Tumakuru",
                    13.331,
                    77.118,
                    "-",
                    "Varies"
                ),
                (
                    "Karnataka Waste Management Project",
                    "Hazardous",
                    "NH 207, Dobbaspet, KIADB Industrial Area, Sompura 562111",
                    "Sompura",
                    13.1735,
                    77.491,
                    "080 2773 5399",
                    "Mon-Sat 9AM-6PM"
                ),
                (
                    "Daniya Traders and Scrap Buyers",
                    "Recyclable",
                    "Old Iron Market, Ring Rd, Gubbi Gate, Tumakuru 572101",
                    "Tumakuru",
                    13.339,
                    77.1018,
                    "86601 42919",
                    "Mon 9AM-8:30PM, Tue-Sun 9AM-7PM"
                ),
                (
                    "Smart City Dumping Yard",
                    "Universal",
                    "Kundavada Rd, Vinobha Nagar, Davangere 577006",
                    "Davanagere",
                    14.478,
                    75.916,
                    "-",
                    "Open 24 hours"
                ),
                (
                    "Parkar Pillows & Cotton Waste",
                    "Recyclable",
                    "Bismillah Layout, Millath Extension Area, Davangere 577001",
                    "Davanagere",
                    14.4645,
                    75.918,
                    "99011 77707",
                    "Daily 9:30AM-9PM (closed Fri)"
                ),
                (
                    "Carbasket Vehicle Scrapping Platform",
                    "Recyclable",
                    "Railway Station Approach Rd, Cowl Bazaar, Ballari 583101",
                    "Ballari",
                    15.145,
                    76.923,
                    "-",
                    "Open 24 hours"
                ),
                (
                    "Roshan Traders",
                    "Recyclable",
                    "UHTC Ranithota, Ballari 583101",
                    "Ballari",
                    15.1465,
                    76.927,
                    "-",
                    "Daily 9:30AM-6:30PM"
                ),
                (
                    "Revive Waste Management",
                    "Recyclable",
                    "KIADB IInd Stage, Humnabad Rd, Kapnoor, Kalaburagi 585104",
                    "Kalaburagi",
                    17.347,
                    76.833,
                    "73826 80786",
                    "Mon-Sat, varies; closed some days"
                ),
                (
                    "Gulbarga Scrap Traders",
                    "Universal",
                    "Humnabad Rd, Kapnoor, Kalaburagi 585104",
                    "Kalaburagi",
                    17.348,
                    76.835,
                    "78978 91967",
                    "Varies"
                ),
                (
                    "Bharat Plastic Udyog",
                    "Recyclable",
                    "KIADB 1st Stage, Kapnoor Industrial Area, Kalaburagi 585104",
                    "Kalaburagi",
                    17.349,
                    76.829,
                    "78168 90009",
                    "Daily 9AM-9PM"
                ),
                (
                    "Dyaberi Multitrade",
                    "Recyclable",
                    "Station Back Rd, Shikarkhane, APMC, Vijayapura 586104",
                    "Vijayapura",
                    16.83,
                    75.71,
                    "97312 66525",
                    "Daily 9AM-9PM"
                ),
                (
                    "Vagdevi Traders",
                    "Recyclable",
                    "Station Back Rd, Shikarkhane, Jadar Galli, Vijayapura 586104",
                    "Vijayapura",
                    16.831,
                    75.712,
                    "72043 94024",
                    "Daily, hours vary"
                ),
                (
                    "OURS Services",
                    "Universal",
                    "Bailoor, Bima Nagar, Udupi 576101",
                    "Udupi",
                    13.341,
                    74.742,
                    "75592 96521",
                    "Daily 8AM-8PM"
                ),
                (
                    "Yaseen Traders",
                    "Recyclable",
                    "Near Clay Art, Adi Udipi, Udupi 576103",
                    "Udupi",
                    13.36,
                    74.746,
                    "96320 02522",
                    "Daily 9AM-6:30PM"
                ),
                (
                    "Eshwari Battery Buyers",
                    "Hazardous",
                    "80 Feet Rd, Penshan Mohalla, Hassan 573202",
                    "Hassan",
                    13.0068,
                    76.1,
                    "-",
                    "Varies"
                ),
                (
                    "Amoggh Mandya Garbage Services",
                    "Universal",
                    "Tirumakudalu Narasipura - Sira Rd, Vidya Nagar, Mandya 571401",
                    "Mandya",
                    12.5222,
                    76.895,
                    "-",
                    "Varies"
                ),
                (
                    "Enviro Biotech",
                    "Hazardous",
                    "MIG 82, New KHB Colony, Pratap Nagar, Bidar 585402",
                    "Bidar",
                    17.91,
                    77.517,
                    "83102 85507",
                    "Mon-Sat 9AM-6PM, Sun 7AM-3PM"
                ),
                (
                    "Chitradurga Waste Disposal Centre",
                    "Universal",
                    "Hosa Dyamavanahalli, Chitradurga 577524",
                    "Chitradurga",
                    14.236,
                    76.39,
                    "-",
                    "Varies"
                ),
                (
                    "Royal Scrap Buyers",
                    "Recyclable",
                    "Santhe Marahalli Circle, Galipur, Chamarajanagar 571313",
                    "Chamarajanagar",
                    11.923,
                    76.943,
                    "-",
                    "Daily 9AM-7:30PM"
                ),
                (
                    "Ramu Enterprises",
                    "Recyclable",
                    "Gundlupet-Chamarajanagara Rd, Chamarajanagar 571313",
                    "Chamarajanagar",
                    11.9245,
                    76.945,
                    "-",
                    "Varies"
                ),
                (
                    "Madikeri SWM Site",
                    "Universal",
                    "Madikeri 571201",
                    "Madikeri",
                    12.4244,
                    75.7382,
                    "-",
                    "Varies"
                ),
                (
                    "Karnataka State Pollution Control Board - Regional Office Madikeri",
                    "Universal",
                    "St Joseph's Convent Road, Bhagavathi Nagar, Madikeri 571201",
                    "Madikeri",
                    12.4265,
                    75.7395,
                    "-",
                    "Mon-Sat 10AM-5:30PM"
                ),
            ]
            cursor.executemany("""
                INSERT INTO disposal_locations (
                    name, category, address, city, latitude, longitude, phone, operating_hours
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, sample_locations)
            conn.commit()

        # Seed sample classifications if empty for immediate rich dashboard visualization
        cursor.execute("SELECT COUNT(*) as count FROM classifications")
        count = cursor.fetchone()["count"]
        if count == 0:
            sample_records = [
                (None, "banana_peel_sample.jpg", "Banana Peel", "Discarded", "Organic", True, 98.4,
                 json.dumps({"Hazardous": 0.4, "Organic": 98.4, "Recyclable": 1.2}),
                 "Discarded fruit peel suitable for organic composting.", "2026-08-27 10:15:30"),
                (None, "plastic_water_bottle.jpg", "Plastic Water Bottle", "Crushed / Empty", "Recyclable", True, 95.8,
                 json.dumps({"Hazardous": 1.1, "Organic": 3.1, "Recyclable": 95.8}),
                 "PET polymer bottle suitable for secondary mechanical recycling.", "2026-08-27 11:20:12"),
                (None, "lithium_battery.jpg", "Lithium Battery", "Depleted / Used", "Hazardous", True, 99.1,
                 json.dumps({"Hazardous": 99.1, "Organic": 0.2, "Recyclable": 0.7}),
                 "Contains toxic heavy chemical cells requiring municipal e-waste containment.", "2026-08-27 12:05:44"),
                (None, "fresh_green_apple.jpg", "Fresh Green Apple", "Fresh / Edible", "Food / Organic Material", False, 96.5,
                 json.dumps({"Hazardous": 0.1, "Organic": 96.5, "Recyclable": 3.4}),
                 "Fresh edible fruit suitable for consumption, not classified as waste.", "2026-08-27 13:10:00"),
                (None, "cardboard_box.jpg", "Cardboard Shipping Box", "Flattened", "Recyclable", True, 94.2,
                 json.dumps({"Hazardous": 0.5, "Organic": 5.3, "Recyclable": 94.2}),
                 "Clean dry corrugated cardboard suitable for pulping.", "2026-08-27 14:02:18"),
                (None, "household_pet_dog.jpg", "Golden Retriever", "Living Animal", "Human/Animal", False, 99.8,
                 json.dumps({"Hazardous": 0.0, "Organic": 99.8, "Recyclable": 0.2}),
                 "Living domestic canine, protected from waste classification.", "2026-08-27 14:35:50"),
            ]
            cursor.executemany("""
                INSERT INTO classifications (
                    user_id, image_filename, object_name, condition, category,
                    is_waste, confidence, probabilities_json, reason, timestamp
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, sample_records)
            conn.commit()


# ---------------------------------------------------------------------------
# User Query Helpers
# ---------------------------------------------------------------------------

def create_user(username: str, email: str, password: str, role: str = "user"):
    """Registers a new user with secure password hashing."""
    password_hash = generate_password_hash(password, method="scrypt")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (username, email, password_hash, role)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (username.strip(), email.strip().lower(), password_hash, role))
            user_id = cursor.fetchone()["id"]
            conn.commit()
            return user_id, None
    except psycopg2.IntegrityError as e:
        msg = str(e).lower()
        if "username" in msg:
            return None, "Username is already taken."
        if "email" in msg:
            return None, "Email address is already registered."
        return None, "A user with these details already exists."
    except Exception as e:
        return None, f"Database error: {e}"


def authenticate_user(login_identifier: str, password: str, require_admin: bool = False):
    """Authenticates a user or admin by username/email and password."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, email, password_hash, role, created_at
            FROM users
            WHERE LOWER(username) = LOWER(%s) OR LOWER(email) = LOWER(%s)
            LIMIT 1
        """, (login_identifier.strip(), login_identifier.strip()))
        user = cursor.fetchone()

        if not user:
            return None, "Invalid username or password."

        if not check_password_hash(user["password_hash"], password):
            return None, "Invalid username or password."

        if require_admin and user["role"] != "admin":
            return None, "Access denied. Administrator privileges required."

        return dict(user), None


def get_user_by_id(user_id: int):
    """Fetches user details by ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, role, created_at FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        return dict(user) if user else None


def get_all_users(limit: int = 50, exclude_admin: bool = True):
    """Fetches list of registered users for the admin console (excluding admin accounts by default)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        where_clause = "WHERE u.role != 'admin' AND u.username != 'admin'" if exclude_admin else ""
        cursor.execute(f"""
            SELECT u.id, u.username, u.email, u.role, u.created_at,
                   COUNT(c.id) AS classification_count
            FROM users u
            LEFT JOIN classifications c ON u.id = c.user_id
            {where_clause}
            GROUP BY u.id
            ORDER BY u.created_at DESC
            LIMIT %s
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Classification Query Helpers
# ---------------------------------------------------------------------------

def save_classification(
    image_filename: str,
    object_name: str,
    condition: str,
    category: str,
    is_waste: bool,
    confidence: float,
    probabilities: dict,
    reason: str,
    user_id: int = None
):
    """Logs a classification scan into the database."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO classifications (
                user_id, image_filename, object_name, condition, category,
                is_waste, confidence, probabilities_json, reason
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            user_id,
            image_filename,
            object_name,
            condition,
            category,
            bool(is_waste),
            confidence,
            json.dumps(probabilities or {}),
            reason
        ))
        row = cursor.fetchone()
        conn.commit()
        return row["id"]


def get_classifications(
    search: str = "",
    category_filter: str = "",
    waste_filter: str = "",
    limit: int = 50,
    offset: int = 0,
    user_id_filter: int = None,
):
    """Fetches filtered classification logs for the admin dashboard.

    `user_id_filter` is optional and additive: when omitted (default),
    behavior is identical to before (all users' records, used by the admin
    dashboard). When provided, results are scoped to that single user's own
    classification history (used by the user-facing Requests page).
    """
    query = """
        SELECT c.id, c.user_id, c.image_filename, c.object_name, c.condition,
               c.category, c.is_waste, c.confidence, c.probabilities_json,
               c.reason, c.timestamp, u.username AS user_name
        FROM classifications c
        LEFT JOIN users u ON c.user_id = u.id
        WHERE 1=1
    """
    params = []

    if user_id_filter is not None:
        query += " AND c.user_id = %s"
        params.append(user_id_filter)

    if search:
        query += " AND (c.object_name ILIKE %s OR c.reason ILIKE %s OR c.condition ILIKE %s)"
        s = f"%{search.strip()}%"
        params.extend([s, s, s])

    if category_filter and category_filter != "all":
        query += " AND c.category ILIKE %s"
        params.append(f"%{category_filter.strip()}%")

    if waste_filter == "waste":
        query += " AND c.is_waste = TRUE"
    elif waste_filter == "not_waste":
        query += " AND c.is_waste = FALSE"

    query += " ORDER BY c.id DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["probabilities"] = json.loads(item["probabilities_json"])
            except Exception:
                item["probabilities"] = {}
            result.append(item)
        return result


def delete_classification_record(record_id: int):
    """Deletes a classification record by ID (Admin only)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM classifications WHERE id = %s", (record_id,))
        conn.commit()
        return cursor.rowcount > 0


def delete_classification_for_user(record_id: int, user_id: int):
    """Deletes only a classification belonging to the logged-in user, along with any linked disposal and collection requests."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Clean up any disposal requests and collection requests linked to this scan
        cursor.execute(
            "DELETE FROM disposal_requests WHERE classification_id = %s AND user_id = %s",
            (record_id, user_id),
        )
        cursor.execute(
            "DELETE FROM collection_requests WHERE classification_id = %s AND user_id = %s",
            (record_id, user_id),
        )
        cursor.execute(
            "DELETE FROM classifications WHERE id = %s AND user_id = %s",
            (record_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_admin_dashboard_stats():
    """Calculates all live database counts and chart metrics for the admin dashboard."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. Total Users
        cursor.execute("SELECT COUNT(*) AS count FROM users WHERE role != 'admin'")
        total_users = cursor.fetchone()["count"]

        # 2. Total Images Classified
        cursor.execute("SELECT COUNT(*) AS count FROM classifications")
        total_classified = cursor.fetchone()["count"]

        # 3. Organic Waste Count
        cursor.execute("""
            SELECT COUNT(*) AS count FROM classifications
            WHERE is_waste = TRUE AND (category LIKE '%Organic%' OR category = 'Organic')
        """)
        organic_count = cursor.fetchone()["count"]

        # 4. Recyclable Waste Count
        cursor.execute("""
            SELECT COUNT(*) AS count FROM classifications
            WHERE is_waste = TRUE AND (category LIKE '%Recyclable%' OR category = 'Recyclable')
        """)
        recyclable_count = cursor.fetchone()["count"]

        # 5. Hazardous Waste Count
        cursor.execute("""
            SELECT COUNT(*) AS count FROM classifications
            WHERE is_waste = TRUE AND (category LIKE '%Hazardous%' OR category = 'Hazardous')
        """)
        hazardous_count = cursor.fetchone()["count"]

        # 6. Not Waste Count
        cursor.execute("SELECT COUNT(*) AS count FROM classifications WHERE is_waste = FALSE")
        not_waste_count = cursor.fetchone()["count"]

        # 7. Average Model Confidence
        cursor.execute("SELECT AVG(confidence) AS avg_conf FROM classifications")
        avg_conf_row = cursor.fetchone()
        avg_confidence = round(avg_conf_row["avg_conf"], 1) if avg_conf_row["avg_conf"] else 0.0

        return {
            "total_users": total_users,
            "total_classified": total_classified,
            "organic_count": organic_count,
            "recyclable_count": recyclable_count,
            "hazardous_count": hazardous_count,
            "not_waste_count": not_waste_count,
            "avg_confidence": avg_confidence,
        }


# ---------------------------------------------------------------------------
# Disposal Locations & Requests Query Helpers
# ---------------------------------------------------------------------------

def calculate_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two GPS points using Haversine formula in kilometers."""
    try:
        r = 6371.0  # Earth's radius in kilometers
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return round(r * c, 2)
    except Exception:
        return 0.0


def create_disposal_request(
    user_name: str,
    object_name: str,
    category: str,
    user_lat: float,
    user_lng: float,
    user_location_text: str = None,
    user_id: int = None,
    image_url: str = None,
    classification_id: int = None
):
    """Creates a new disposal request from user scan."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO disposal_requests (
                user_id, classification_id, user_name, object_name, category,
                user_lat, user_lng, user_location_text, status, image_url
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Pending', %s)
            RETURNING id
        """, (
            user_id,
            classification_id,
            user_name.strip(),
            object_name.strip(),
            category.strip(),
            float(user_lat),
            float(user_lng),
            (user_location_text or "").strip(),
            (image_url or "").strip() or None
        ))
        row = cursor.fetchone()
        conn.commit()
        return row["id"]


def get_user_disposal_requests(user_id: int = None, user_name: str = None, limit: int = 50):
    """Fetches disposal request history for a specific user with assigned location details."""
    query = """
        SELECT r.id, r.user_id, r.classification_id, r.user_name, r.object_name, r.category,
               r.user_lat, r.user_lng, r.user_location_text, r.status,
               r.assigned_location_id, r.admin_notes, r.created_at, r.updated_at,
               r.image_url, r.admin_verified, r.verified_at,
               l.name AS location_name, l.category AS location_category,
               l.address AS location_address, l.city AS location_city,
               l.latitude AS location_lat, l.longitude AS location_lng,
               l.phone AS location_phone, l.operating_hours AS location_hours
        FROM disposal_requests r
        LEFT JOIN disposal_locations l ON r.assigned_location_id = l.id
        WHERE 1=1
    """
    params = []
    if user_id:
        query += " AND r.user_id = %s"
        params.append(user_id)
    elif user_name:
        query += " AND LOWER(r.user_name) = LOWER(%s)"
        params.append(user_name.strip())

    query += " ORDER BY r.id DESC LIMIT %s"
    params.append(limit)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        results = []
        for row in rows:
            item = dict(row)
            if item.get("location_lat") and item.get("location_lng") and item.get("user_lat") and item.get("user_lng"):
                item["distance_km"] = calculate_distance_km(
                    item["user_lat"], item["user_lng"],
                    item["location_lat"], item["location_lng"]
                )
            else:
                item["distance_km"] = None
            results.append(item)
        return results


def get_disposal_request_by_id(request_id: int):
    """Fetches a single disposal request with full details and assigned location."""
    query = """
        SELECT r.id, r.user_id, r.classification_id, r.user_name, r.object_name, r.category,
               r.user_lat, r.user_lng, r.user_location_text, r.status,
               r.assigned_location_id, r.admin_notes, r.created_at, r.updated_at,
               r.image_url, r.admin_verified, r.verified_at,
               u.email AS user_email,
               l.name AS location_name, l.category AS location_category,
               l.address AS location_address, l.city AS location_city,
               l.latitude AS location_lat, l.longitude AS location_lng,
               l.phone AS location_phone, l.operating_hours AS location_hours
        FROM disposal_requests r
        LEFT JOIN users u ON r.user_id = u.id
        LEFT JOIN disposal_locations l ON r.assigned_location_id = l.id
        WHERE r.id = %s
        LIMIT 1
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (request_id,))
        row = cursor.fetchone()
        if not row:
            return None
        item = dict(row)
        if item.get("location_lat") and item.get("location_lng") and item.get("user_lat") and item.get("user_lng"):
            item["distance_km"] = calculate_distance_km(
                item["user_lat"], item["user_lng"],
                item["location_lat"], item["location_lng"]
            )
        else:
            item["distance_km"] = None
        return item


def get_disposal_request_by_classification_id(classification_id: int, user_id: int = None):
    """Fetches existing disposal request linked to a specific scanned classification ID."""
    if not classification_id:
        return None
    query = """
        SELECT r.id, r.user_id, r.classification_id, r.user_name, r.object_name, r.category,
               r.user_lat, r.user_lng, r.user_location_text, r.status,
               r.assigned_location_id, r.admin_notes, r.created_at, r.updated_at,
               r.image_url, r.admin_verified, r.verified_at,
               l.name AS location_name, l.category AS location_category,
               l.address AS location_address, l.city AS location_city,
               l.latitude AS location_lat, l.longitude AS location_lng,
               l.phone AS location_phone, l.operating_hours AS location_hours
        FROM disposal_requests r
        LEFT JOIN disposal_locations l ON r.assigned_location_id = l.id
        WHERE r.classification_id = %s
    """
    params = [classification_id]
    if user_id:
        query += " AND r.user_id = %s"
        params.append(user_id)
    query += " ORDER BY r.id DESC LIMIT 1"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        if not row:
            return None
        item = dict(row)
        if item.get("location_lat") and item.get("location_lng") and item.get("user_lat") and item.get("user_lng"):
            item["distance_km"] = calculate_distance_km(
                item["user_lat"], item["user_lng"],
                item["location_lat"], item["location_lng"]
            )
        else:
            item["distance_km"] = None
        return item


def update_disposal_request_location_and_center(
    request_id: int,
    user_lat: float,
    user_lng: float,
    user_location_text: str = None,
    assigned_location_id: int = None,
    admin_notes: str = None
) -> bool:
    """Updates the user GPS coordinates and re-assigns the nearest disposal facility for a request."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE disposal_requests
            SET user_lat = %s, user_lng = %s,
                user_location_text = COALESCE(%s, user_location_text),
                assigned_location_id = %s,
                admin_notes = COALESCE(%s, admin_notes),
                status = CASE WHEN %s IS NOT NULL THEN 'Location Assigned' ELSE status END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (
            float(user_lat),
            float(user_lng),
            user_location_text,
            assigned_location_id,
            admin_notes,
            assigned_location_id,
            request_id
        ))
        conn.commit()
        return cursor.rowcount > 0


def reassign_user_disposal_requests_to_location(
    user_id: int,
    lat: float,
    lng: float,
    location_text: str = None
) -> int:
    """When a user updates their saved location, re-calculates distances and
    re-assigns all their active disposal requests to the nearest facility."""
    if not user_id or lat is None or lng is None:
        return 0

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, category, status
            FROM disposal_requests
            WHERE user_id = %s AND status != 'Completed'
            """,
            (user_id,)
        )
        requests = [dict(r) for r in cursor.fetchall()]

    updated_count = 0
    for req in requests:
        nearby = get_nearby_disposal_locations(user_lat=lat, user_lng=lng, category=req.get("category"))
        best = nearby[0] if nearby else None
        assigned_loc_id = best["id"] if best else None
        admin_notes = (
            f"Auto-assigned to the nearest {'matching' if best.get('is_category_match') else 'available'} "
            f"center: {best['name']} (~{best['distance_km']} km away)."
        ) if best else "No disposal facilities available for updated location."

        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                """
                UPDATE disposal_requests
                SET user_lat = %s, user_lng = %s,
                    user_location_text = COALESCE(%s, user_location_text),
                    assigned_location_id = %s,
                    admin_notes = %s,
                    status = CASE WHEN %s IS NOT NULL THEN 'Location Assigned' ELSE status END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (float(lat), float(lng), location_text, assigned_loc_id, admin_notes, assigned_loc_id, req["id"])
            )
            conn.commit()
            updated_count += 1

    return updated_count


def get_all_disposal_requests(
    status_filter: str = "all",
    category_filter: str = "all",
    search: str = "",
    limit: int = 100,
    offset: int = 0
):
    """Fetches filtered disposal requests for admin console."""
    query = """
        SELECT r.id, r.user_id, r.classification_id, r.user_name, r.object_name, r.category,
               r.user_lat, r.user_lng, r.user_location_text, r.status,
               r.assigned_location_id, r.admin_notes, r.created_at, r.updated_at,
               r.image_url, r.admin_verified, r.verified_at,
               u.email AS user_email,
               l.name AS location_name, l.address AS location_address,
               l.latitude AS location_lat, l.longitude AS location_lng
        FROM disposal_requests r
        LEFT JOIN users u ON r.user_id = u.id
        LEFT JOIN disposal_locations l ON r.assigned_location_id = l.id
        WHERE 1=1
    """
    params = []

    if search:
        query += " AND (r.user_name ILIKE %s OR r.object_name ILIKE %s OR r.category ILIKE %s OR r.user_location_text ILIKE %s)"
        s = f"%{search.strip()}%"
        params.extend([s, s, s, s])

    if status_filter and status_filter != "all":
        query += " AND r.status = %s"
        params.append(status_filter)

    if category_filter and category_filter != "all":
        query += " AND r.category ILIKE %s"
        params.append(f"%{category_filter.strip()}%")

    query += " ORDER BY CASE r.status WHEN 'Pending' THEN 1 WHEN 'Reviewed' THEN 2 WHEN 'Location Assigned' THEN 3 ELSE 4 END, r.id DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_all_disposal_locations(category_filter: str = "all"):
    """Fetches all verified disposal facilities."""
    query = "SELECT * FROM disposal_locations WHERE 1=1"
    params = []
    if category_filter and category_filter != "all":
        query += " AND (category = %s OR category = 'Universal')"
        params.append(category_filter)
    query += " ORDER BY name ASC"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_disposal_location_by_id(loc_id: int):
    """Fetches a disposal location by its ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM disposal_locations WHERE id = %s", (loc_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def add_disposal_location(
    name: str,
    category: str,
    address: str,
    latitude: float,
    longitude: float,
    phone: str = None,
    operating_hours: str = None,
    city: str = "Metro Area"
):
    """Adds a new disposal location center to database."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO disposal_locations (
                name, category, address, city, latitude, longitude, phone, operating_hours
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            name.strip(),
            category.strip(),
            address.strip(),
            city.strip(),
            float(latitude),
            float(longitude),
            (phone or "").strip(),
            (operating_hours or "").strip()
        ))
        row = cursor.fetchone()
        conn.commit()
        return row["id"]


def update_disposal_location(
    loc_id: int,
    name: str,
    category: str,
    address: str,
    latitude: float,
    longitude: float,
    phone: str = None,
    operating_hours: str = None,
    city: str = "Metro Area"
) -> bool:
    """Updates an existing disposal location center in database."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE disposal_locations
            SET name = %s, category = %s, address = %s, city = %s,
                latitude = %s, longitude = %s, phone = %s, operating_hours = %s
            WHERE id = %s
        """, (
            name.strip(),
            category.strip(),
            address.strip(),
            city.strip(),
            float(latitude),
            float(longitude),
            (phone or "").strip(),
            (operating_hours or "").strip(),
            int(loc_id)
        ))
        conn.commit()
        return cursor.rowcount > 0


def delete_disposal_location(loc_id: int) -> bool:
    """Deletes a disposal location facility by ID (Admin only)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM disposal_locations WHERE id = %s", (loc_id,))
        conn.commit()
        return cursor.rowcount > 0


def update_disposal_request_status(
    request_id: int,
    status: str,
    assigned_location_id: int = None,
    admin_notes: str = None
):
    """Updates status, recommended location assignment, and notes for a request."""
    valid_statuses = {"Pending", "Reviewed", "Location Assigned", "Completed"}
    if status not in valid_statuses:
        return False

    with get_db_connection() as conn:
        cursor = conn.cursor()
        if assigned_location_id is not None:
            cursor.execute("""
                UPDATE disposal_requests
                SET status = %s, assigned_location_id = %s, admin_notes = COALESCE(%s, admin_notes), updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (status, assigned_location_id, admin_notes, request_id))
        else:
            cursor.execute("""
                UPDATE disposal_requests
                SET status = %s, admin_notes = COALESCE(%s, admin_notes), updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (status, admin_notes, request_id))
        conn.commit()
        return cursor.rowcount > 0


def verify_disposal_request(request_id: int):
    """Marks a request as reviewed/verified by an admin.

    This does NOT change the auto-selected facility — the system already
    picks the nearest matching disposal center when the request is created.
    Verifying just records that a human admin has inspected the details
    (image, GPS, category) and confirms the auto-assignment is correct.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE disposal_requests
            SET admin_verified = TRUE, verified_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (request_id,))
        conn.commit()
        return cursor.rowcount > 0


def delete_disposal_request(request_id: int):
    """Deletes a disposal request (Admin only)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM disposal_requests WHERE id = %s", (request_id,))
        conn.commit()
        return cursor.rowcount > 0


def create_user_notification(user_id: int, request_id: int, message: str):
    """Creates a notification for a user when a request changes meaningfully."""
    if not user_id or not message:
        return None
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO notifications (user_id, request_id, message) VALUES (%s, %s, %s) RETURNING id",
            (user_id, request_id, message.strip()),
        )
        row = cursor.fetchone()
        conn.commit()
        return row["id"]


def get_user_notifications(user_id: int, unread_only: bool = False, limit: int = 20):
    """Returns recent notifications scoped to the logged-in user."""
    query = """
        SELECT id, request_id, message, is_read, created_at
        FROM notifications
        WHERE user_id = %s
    """
    params = [user_id]
    if unread_only:
        query += " AND is_read = FALSE"
    query += " ORDER BY id DESC LIMIT %s"
    params.append(limit)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]



def mark_user_notifications_read(user_id: int, notification_ids=None):
    """Marks all or selected notifications as read for the current user."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if notification_ids:
            clean_ids = [int(item) for item in notification_ids]
            placeholders = ','.join('%s' for _ in clean_ids)
            cursor.execute(
                f"UPDATE notifications SET is_read = TRUE WHERE user_id = %s AND id IN ({placeholders})",
                [user_id, *clean_ids],
            )
        else:
            cursor.execute("UPDATE notifications SET is_read = TRUE WHERE user_id = %s", (user_id,))
        conn.commit()
        return cursor.rowcount


def delete_user_notifications(user_id: int):
    """Hard-deletes all notifications for the given user (used by 'Clear all')."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM notifications WHERE user_id = %s", (user_id,))
        conn.commit()
        return cursor.rowcount


def get_nearby_disposal_locations(user_lat: float, user_lng: float, category: str = None):
    """Returns available disposal locations sorted by Haversine proximity to user GPS coordinates."""
    locations = get_all_disposal_locations(category_filter="all")
    results = []

    clean_category = (category or "").lower()

    for loc in locations:
        loc_cat = loc["category"].lower()
        dist = calculate_distance_km(user_lat, user_lng, loc["latitude"], loc["longitude"])
        item = dict(loc)
        item["distance_km"] = dist

        # Exact or compatible category match flag
        is_match = False
        if "universal" in loc_cat:
            is_match = True
        elif clean_category and ("hazard" in clean_category and "hazard" in loc_cat):
            is_match = True
        elif clean_category and ("organic" in clean_category and "organic" in loc_cat):
            is_match = True
        elif clean_category and ("recycl" in clean_category and "recycl" in loc_cat):
            is_match = True

        item["is_category_match"] = is_match
        results.append(item)

    # Sort by: category matches first, then shortest distance
    results.sort(key=lambda x: (not x["is_category_match"], x["distance_km"]))
    return results


def get_disposal_requests_stats():
    """Returns summary stats for disposal requests for admin dashboards."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM disposal_requests")
        total = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS pending FROM disposal_requests WHERE status = 'Pending'")
        pending = cursor.fetchone()["pending"]

        cursor.execute("SELECT COUNT(*) AS reviewed FROM disposal_requests WHERE status = 'Reviewed'")
        reviewed = cursor.fetchone()["reviewed"]

        cursor.execute("SELECT COUNT(*) AS assigned FROM disposal_requests WHERE status = 'Location Assigned'")
        assigned = cursor.fetchone()["assigned"]

        cursor.execute("SELECT COUNT(*) AS completed FROM disposal_requests WHERE status = 'Completed'")
        completed = cursor.fetchone()["completed"]

        cursor.execute("SELECT COUNT(*) AS total_locations FROM disposal_locations")
        total_locations = cursor.fetchone()["total_locations"]

        return {
            "total": total,
            "pending": pending,
            "reviewed": reviewed,
            "assigned": assigned,
            "completed": completed,
            "total_locations": total_locations,
        }


# ---------------------------------------------------------------------------
# Waste Collection (Pickup) Requests
# ---------------------------------------------------------------------------
def create_collection_request(
    user_name: str,
    waste_type: str,
    quantity: str,
    pickup_lat: float,
    pickup_lng: float,
    pickup_location_text: str = None,
    address: str = None,
    note: str = None,
    user_id: int = None,
    area: str = None,
    scheduled_day: str = None,
    scheduled_date: str = None,
    scheduled_time_start: str = None,
    scheduled_time_end: str = None,
    classification_id: int = None,
):
    """Creates a new waste collection (pickup) request. The scheduled_*
    fields are auto-assigned from the admin's area collection schedule
    (see find_matching_schedule_for_area / next_occurrence_date) — the
    user never picks a date manually."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO collection_requests (
                user_id, classification_id, user_name, waste_type, quantity,
                pickup_lat, pickup_lng, pickup_location_text, address, note,
                area, scheduled_day, scheduled_date, scheduled_time_start, scheduled_time_end,
                status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Pending')
            RETURNING id
        """, (
            user_id,
            classification_id,
            user_name.strip(),
            waste_type.strip(),
            quantity.strip(),
            float(pickup_lat),
            float(pickup_lng),
            (pickup_location_text or "").strip(),
            (address or "").strip(),
            (note or "").strip(),
            (area or "").strip() or None,
            scheduled_day,
            scheduled_date,
            scheduled_time_start,
            scheduled_time_end,
        ))
        row = cursor.fetchone()
        conn.commit()
        return row["id"]


def get_collection_request_by_id(request_id: int):
    """Fetches a single collection request with full details."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.*, u.email AS user_email
            FROM collection_requests c
            LEFT JOIN users u ON c.user_id = u.id
            WHERE c.id = %s
            LIMIT 1
        """, (request_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_collection_requests(user_id: int = None, user_name: str = None, limit: int = 50):
    """Fetches collection request history for a specific user."""
    query = "SELECT * FROM collection_requests WHERE 1=1"
    params = []
    if user_id:
        query += " AND user_id = %s"
        params.append(user_id)
    elif user_name:
        query += " AND LOWER(user_name) = LOWER(%s)"
        params.append(user_name.strip())

    query += " ORDER BY id DESC LIMIT %s"
    params.append(limit)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_all_collection_requests(
    status_filter: str = "all",
    search: str = "",
    limit: int = 100,
    offset: int = 0
):
    """Fetches filtered collection requests for the admin console."""
    query = "SELECT * FROM collection_requests WHERE 1=1"
    params = []

    if search:
        query += " AND (user_name ILIKE %s OR waste_type ILIKE %s OR address ILIKE %s)"
        s = f"%{search.strip()}%"
        params.extend([s, s, s])

    if status_filter and status_filter != "all":
        query += " AND status = %s"
        params.append(status_filter)

    query += (
        " ORDER BY CASE status WHEN 'Pending' THEN 1 WHEN 'Accepted' THEN 2 "
        "WHEN 'Rejected' THEN 3 ELSE 4 END, id DESC LIMIT %s OFFSET %s"
    )
    params.extend([limit, offset])

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def update_collection_request_status(request_id: int, status: str, admin_notes: str = None):
    """Updates the status (and optional admin notes) of a collection request."""
    valid_statuses = {"Pending", "Accepted", "Rejected", "Collected"}
    if status not in valid_statuses:
        return False

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE collection_requests
            SET status = %s, admin_notes = COALESCE(%s, admin_notes), updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (status, admin_notes, request_id))
        conn.commit()
        return cursor.rowcount > 0


def delete_collection_request(request_id: int):
    """Deletes a collection request (Admin only)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM collection_requests WHERE id = %s", (request_id,))
        conn.commit()
        return cursor.rowcount > 0


def get_collection_requests_stats():
    """Returns summary stats for collection (pickup) requests for admin dashboards."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM collection_requests")
        total = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS pending FROM collection_requests WHERE status = 'Pending'")
        pending = cursor.fetchone()["pending"]

        cursor.execute("SELECT COUNT(*) AS accepted FROM collection_requests WHERE status = 'Accepted'")
        accepted = cursor.fetchone()["accepted"]

        cursor.execute("SELECT COUNT(*) AS rejected FROM collection_requests WHERE status = 'Rejected'")
        rejected = cursor.fetchone()["rejected"]

        cursor.execute("SELECT COUNT(*) AS collected FROM collection_requests WHERE status = 'Collected'")
        collected = cursor.fetchone()["collected"]

        return {
            "total": total,
            "pending": pending,
            "accepted": accepted,
            "rejected": rejected,
            "collected": collected,
        }


# ---------------------------------------------------------------------------
# Area-Based Waste Collection Schedule (Admin-managed)
# ---------------------------------------------------------------------------

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAY_INDEX = {name: idx for idx, name in enumerate(WEEKDAYS)}


def get_all_collection_schedules():
    """Fetches every collection schedule row (active and inactive) for the
    admin's Collection Schedule management table, grouped alphabetically."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM collection_schedules ORDER BY LOWER(area) ASC, id ASC")
        return [dict(row) for row in cursor.fetchall()]


def get_collection_schedule_by_id(schedule_id: int):
    """Fetches a single collection schedule row."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM collection_schedules WHERE id = %s", (schedule_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def create_collection_schedule(
    area: str,
    day_of_week: str,
    time_start: str,
    time_end: str,
    pincode: str = "",
    collector_name: str = "EcoCycle Municipal Collector",
    active: bool = True
):
    """Adds a new area -> pickup-day/time schedule row with PIN code and collector name (Admin only)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO collection_schedules (area, pincode, collector_name, day_of_week, time_start, time_end, active)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            area.strip(),
            (pincode or "").strip(),
            (collector_name or "EcoCycle Municipal Collector").strip(),
            day_of_week.strip().title(),
            time_start.strip(),
            time_end.strip(),
            bool(active),
        ))
        row = cursor.fetchone()
        conn.commit()
        return row["id"]


def update_collection_schedule(
    schedule_id: int,
    area: str,
    day_of_week: str,
    time_start: str,
    time_end: str,
    pincode: str = "",
    collector_name: str = "EcoCycle Municipal Collector",
    active: bool = True
):
    """Edits an existing collection schedule row with PIN code and collector name (Admin only)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE collection_schedules
            SET area = %s, pincode = %s, collector_name = %s, day_of_week = %s,
                time_start = %s, time_end = %s, active = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (
            area.strip(),
            (pincode or "").strip(),
            (collector_name or "EcoCycle Municipal Collector").strip(),
            day_of_week.strip().title(),
            time_start.strip(),
            time_end.strip(),
            1 if active else 0,
            schedule_id,
        ))
        conn.commit()
        return cursor.rowcount > 0


def toggle_collection_schedule(schedule_id: int):
    """Flips a schedule row's active/disabled flag (Admin only)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT active FROM collection_schedules WHERE id = %s", (schedule_id,))
        row = cursor.fetchone()
        if not row:
            return False
        new_value = not bool(row["active"])
        cursor.execute(
            "UPDATE collection_schedules SET active = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (new_value, schedule_id)
        )
        conn.commit()
        return True


def delete_collection_schedule(schedule_id: int):
    """Deletes a collection schedule row (Admin only)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM collection_schedules WHERE id = %s", (schedule_id,))
        conn.commit()
        return cursor.rowcount > 0


def save_user_location(user_id: int, area: str, pincode: str, address: str, lat: float, lng: float) -> bool:
    """Saves (or overwrites) the user's permanent location details —
    area, pincode, address, latitude, and longitude."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE users
            SET location_area = %s, location_pincode = %s, location_address = %s,
                location_lat = %s, location_lng = %s, location_updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (area.strip(), (pincode or "").strip(), (address or "").strip(), lat, lng, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_user_location(user_id: int):
    """Returns the user's saved location as a dict, or None if they
    haven't set one yet (location_area is empty/NULL)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT location_area AS area, location_pincode AS pincode,
                   location_address AS address, location_lat AS lat,
                   location_lng AS lng, location_updated_at AS updated_at
            FROM users WHERE id = %s
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if not row or not row["area"]:
            return None
        return dict(row)


def find_matching_schedule_for_area(area_text: str, pincode: str = None):
    """Finds the best-matching *active* collection schedule and collector
    availability for a user's location based on PIN code and Area name.

    Matching precedence:
    1. Exact match on both PIN Code and Area (if PIN code provided)
    2. Exact match on PIN Code (if PIN code is configured in schedule)
    3. Exact case-insensitive match on Area / Locality name
    4. Substring match on Area / Locality name in either direction

    Returns the schedule dict (with collector_name, day_of_week, time window),
    or None if no collector is currently configured for this area.
    """
    area_needle = (area_text or "").strip().lower()
    pin_needle = (pincode or "").strip().replace(" ", "")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM collection_schedules WHERE active = TRUE")
        rows = [dict(row) for row in cursor.fetchall()]

    if not rows:
        return None

    # 1. Match both Area and PIN Code
    if area_needle and pin_needle:
        for row in rows:
            row_area = (row.get("area") or "").strip().lower()
            row_pin = (row.get("pincode") or "").strip().replace(" ", "")
            if row_pin and row_pin == pin_needle and (row_area == area_needle or row_area in area_needle or area_needle in row_area):
                return row

    # 2. Match PIN Code if available
    if pin_needle:
        for row in rows:
            row_pin = (row.get("pincode") or "").strip().replace(" ", "")
            if row_pin and row_pin == pin_needle:
                return row

    # 3. Exact Area name match
    if area_needle:
        for row in rows:
            row_area = (row.get("area") or "").strip().lower()
            if row_area == area_needle:
                return row

    # 4. Substring Area name match
    if area_needle:
        for row in rows:
            row_area = (row.get("area") or "").strip().lower()
            if row_area and (row_area in area_needle or area_needle in row_area):
                return row

    return None


def next_occurrence_date(day_of_week: str, time_start: str = None) -> str:
    """Returns the ISO date (YYYY-MM-DD) of the next occurrence of the given
    weekday. Today is included if that weekday is today and time_start
    hasn't passed yet; otherwise it rolls forward to next week."""
    if not day_of_week:
        return None
    target = WEEKDAY_INDEX.get(day_of_week.strip().title())
    if target is None:
        return None

    now = datetime.now()
    days_ahead = (target - now.weekday()) % 7
    candidate = now.date()
    candidate = candidate.fromordinal(candidate.toordinal() + days_ahead)

    if days_ahead == 0 and time_start:
        try:
            hh, mm = [int(part) for part in time_start.strip().split(":")]
            start_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if now > start_dt:
                candidate = candidate.fromordinal(candidate.toordinal() + 7)
        except (ValueError, TypeError):
            pass

    return candidate.isoformat()

