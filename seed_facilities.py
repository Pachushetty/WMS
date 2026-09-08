import os
import sys
import json

# Ensure ecocycle root is at head of sys.path and remove parent Downloads dir from path to prevent app.py collision
sys.path = [p for p in sys.path if os.path.abspath(p).lower() != r'c:\users\hemal\downloads']
sys.path.insert(0, os.path.abspath('.'))

from app.database import get_db_connection

facilities_data = [
  {
    "id": 1,
    "name": "Bangalore Ewaste Recycle Center",
    "city": "Bengaluru",
    "type": "hazardous",
    "address": "154, 4th A Cross Rd, Seethappa Layout, Chamundi Nagar, Bengaluru 560032",
    "phone": "Doorstep pickup service",
    "hours": "Open 24 hours",
    "latitude": 13.0288,
    "longitude": 77.5655,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 2,
    "name": "Saahas Waste Management",
    "city": "Bengaluru",
    "type": "universal",
    "address": "32, 5th B Cross, 16th Main Rd, BTM Layout, Bengaluru 560076",
    "phone": "1800 258 6676",
    "hours": "Mon-Fri 9:30AM-6PM, Sat 9:30AM-4PM",
    "latitude": 12.9166,
    "longitude": 77.6101,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 3,
    "name": "Dry Waste Collection Center",
    "city": "Bengaluru",
    "type": "recyclable",
    "address": "Milk Booth, Jeevan Griha, 2nd Phase, J.P. Nagar, Bengaluru 560078",
    "phone": "-",
    "hours": "Varies",
    "latitude": 12.9084,
    "longitude": 77.5964,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 4,
    "name": "WasteCycle - Doorstep Scrap Collection",
    "city": "Bengaluru",
    "type": "recyclable",
    "address": "1st Main, HAL, Kaggadasapura, Bengaluru 560017",
    "phone": "63625 03005",
    "hours": "Open 24 hours",
    "latitude": 12.9825,
    "longitude": 77.6790,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 5,
    "name": "Escrappy Recyclers E-waste",
    "city": "Bengaluru",
    "type": "hazardous",
    "address": "Shushruti Nagar, Byraveshwara Industrial Estate, Bengaluru 560091",
    "phone": "93640 05055",
    "hours": "Mon-Sat 9AM-6:30PM",
    "latitude": 13.0247,
    "longitude": 77.5108,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 6,
    "name": "BBMP Waste Collection Centre",
    "city": "Bengaluru",
    "type": "universal",
    "address": "Devarachikkanahalli Rd, Begur, Bengaluru 560114",
    "phone": "-",
    "hours": "Varies",
    "latitude": 12.8778,
    "longitude": 77.6205,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 7,
    "name": "Bengaluru Solid Waste Management Ltd",
    "city": "Bengaluru",
    "type": "universal",
    "address": "Millers Tank Bund Rd, Vasanth Nagar, Bengaluru 560001",
    "phone": "99804 17644",
    "hours": "Mon-Sat 10AM-7PM",
    "latitude": 12.9935,
    "longitude": 77.5897,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 8,
    "name": "Maridi Bio Industries Pvt Ltd",
    "city": "Bengaluru",
    "type": "hazardous",
    "address": "Sunaga Arcade, Sampangi Rama Nagar, Bengaluru 560027",
    "phone": "-",
    "hours": "Varies",
    "latitude": 12.9688,
    "longitude": 77.5756,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 9,
    "name": "Saveeco Waste Management Pvt Ltd",
    "city": "Bengaluru",
    "type": "universal",
    "address": "Bannerghatta Main Rd, Gottigere, Bengaluru 560083",
    "phone": "72045 11222",
    "hours": "Mon-Sat 10AM-6PM",
    "latitude": 12.8557,
    "longitude": 77.5962,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 10,
    "name": "Electronic Waste Management (E-Waste)",
    "city": "Mysuru",
    "type": "hazardous",
    "address": "Sun Pure Garden, Hanchya, Rammanahalli, Mysuru 570019",
    "phone": "94815 45728",
    "hours": "Mon-Fri open 24 hrs, Sat-Sun closed",
    "latitude": 12.2616,
    "longitude": 76.6830,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 11,
    "name": "Mysore Scrap Traders",
    "city": "Mysuru",
    "type": "recyclable",
    "address": "3146 Convent Road, L. Mohalla, Tilak Nagar, Mysuru 570001",
    "phone": "98804 44722",
    "hours": "Open 24 hours",
    "latitude": 12.3052,
    "longitude": 76.6552,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 12,
    "name": "Zero Waste Management Plant",
    "city": "Mysuru",
    "type": "universal",
    "address": "Lokanayaka Nagar, Hebbal 1st Stage, Mysuru 570016",
    "phone": "-",
    "hours": "Varies",
    "latitude": 12.3482,
    "longitude": 76.6394,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 13,
    "name": "Namma Mysore Foundation",
    "city": "Mysuru",
    "type": "recyclable",
    "address": "1255 Krishnaraja Road, Krishnamurthy Puram, Mysuru 570014",
    "phone": "98450 84416",
    "hours": "Daily 9:30AM-6:30PM",
    "latitude": 12.2871,
    "longitude": 76.6436,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 14,
    "name": "Mother Nature Waste Management & Recycling Industry",
    "city": "Mangaluru",
    "type": "universal",
    "address": "Baikampady Industrial Area, New Mangalore 575011",
    "phone": "90359 49904",
    "hours": "Varies",
    "latitude": 12.9475,
    "longitude": 74.8219,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 15,
    "name": "Mangala Resource Management Pvt Ltd",
    "city": "Mangaluru",
    "type": "universal",
    "address": "Sahyadri Campus, Adyar, Mangaluru 575007",
    "phone": "90197 02501",
    "hours": "Varies",
    "latitude": 12.8858,
    "longitude": 74.9234,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 16,
    "name": "MCC Solid Waste Management Plant",
    "city": "Mangaluru",
    "type": "universal",
    "address": "Vamanjoor, Mangaluru 575028",
    "phone": "-",
    "hours": "Varies",
    "latitude": 12.9184,
    "longitude": 74.9026,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 17,
    "name": "Poly Shakthi Recycling",
    "city": "Mangaluru",
    "type": "recyclable",
    "address": "Port Town, Industrial Area, Baikampady, Mangaluru 575011",
    "phone": "63618 56955",
    "hours": "Open 24 hours",
    "latitude": 12.9488,
    "longitude": 74.8213,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 18,
    "name": "Moogambigai Metal Refineries",
    "city": "Mangaluru",
    "type": "recyclable",
    "address": "Industrial Area Rd, New Mangalore, Baikampady 575011",
    "phone": "99011 48952",
    "hours": "Mon-Sat 9:30AM-6:30PM",
    "latitude": 12.9495,
    "longitude": 74.8240,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 19,
    "name": "Dharwad Plastic Hubballi",
    "city": "Hubballi",
    "type": "recyclable",
    "address": "Gokul Rd, Industrial Estate, Hubballi 580030",
    "phone": "85533 88821",
    "hours": "Mon-Sat 9AM-9PM",
    "latitude": 15.3746,
    "longitude": 75.1240,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 20,
    "name": "RecyclEarth Foundation",
    "city": "Hubballi",
    "type": "universal",
    "address": "Anusharan Arcade, Vidya Nagar, Hubballi 580031",
    "phone": "0836 425 3769",
    "hours": "Mon-Sat 10AM-4PM",
    "latitude": 15.3618,
    "longitude": 75.1360,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 21,
    "name": "Go Green Associates",
    "city": "Hubballi",
    "type": "universal",
    "address": "Tarihal Industrial Area, Hubballi 580026",
    "phone": "-",
    "hours": "Open 24 hours",
    "latitude": 15.3356,
    "longitude": 75.0838,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 22,
    "name": "Ecologix Recycling",
    "city": "Belagavi",
    "type": "recyclable",
    "address": "JB Mudakannavar Building, Raviwar Peth, Belagavi 590001",
    "phone": "-",
    "hours": "Mon 11AM-5:30PM, Tue-Sat 11AM-5PM",
    "latitude": 15.8497,
    "longitude": 74.4977,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 23,
    "name": "Nuvicta Ecoplast Pvt Ltd",
    "city": "Belagavi",
    "type": "recyclable",
    "address": "KIADB Industrial Area, Honaga, Belagavi 591156",
    "phone": "-",
    "hours": "Mon-Sat 9:30AM-5:30PM",
    "latitude": 15.8860,
    "longitude": 74.5590,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 24,
    "name": "Kabadi Man",
    "city": "Belagavi",
    "type": "universal",
    "address": "Shahu Nagar, Belagavi 590010",
    "phone": "88611 83111",
    "hours": "Varies",
    "latitude": 15.8710,
    "longitude": 74.5060,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 25,
    "name": "Common Bio Medical Waste Treatment Facility",
    "city": "Bagalkot",
    "type": "hazardous",
    "address": "APMC Yard, Bagalkot 587103",
    "phone": "63647 64791",
    "hours": "Varies",
    "latitude": 16.1867,
    "longitude": 75.6961,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 26,
    "name": "The Shushrutha Bio-Medical Waste Management Society",
    "city": "Shivamogga",
    "type": "hazardous",
    "address": "KIADB Industrial Area, Machenahalli, Bhadravathi, Shivamogga 577222",
    "phone": "81822 46090",
    "hours": "Varies",
    "latitude": 13.8420,
    "longitude": 75.7050,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 27,
    "name": "Dry Waste Collection Center",
    "city": "Tumakuru",
    "type": "recyclable",
    "address": "Ring Rd, Jayapura, Tumakuru 572101",
    "phone": "-",
    "hours": "Varies",
    "latitude": 13.3350,
    "longitude": 77.1010,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 28,
    "name": "Epragathi Recycling",
    "city": "Tumakuru",
    "type": "hazardous",
    "address": "KIADB Industrial Area, Antharasanahalli, Tumakuru 572106",
    "phone": "-",
    "hours": "Varies",
    "latitude": 13.3575,
    "longitude": 77.1105,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 29,
    "name": "Balaji Rubber and Reclaims Pvt Ltd",
    "city": "Tumakuru",
    "type": "recyclable",
    "address": "Industrial Area, Satyamangala, Tumakuru 572104",
    "phone": "-",
    "hours": "Varies",
    "latitude": 13.3310,
    "longitude": 77.1180,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 30,
    "name": "Karnataka Waste Management Project",
    "city": "Sompura",
    "type": "hazardous",
    "address": "NH 207, Dobbaspet, KIADB Industrial Area, Sompura 562111",
    "phone": "080 2773 5399",
    "hours": "Mon-Sat 9AM-6PM",
    "latitude": 13.1735,
    "longitude": 77.4910,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 31,
    "name": "Daniya Traders and Scrap Buyers",
    "city": "Tumakuru",
    "type": "recyclable",
    "address": "Old Iron Market, Ring Rd, Gubbi Gate, Tumakuru 572101",
    "phone": "86601 42919",
    "hours": "Mon 9AM-8:30PM, Tue-Sun 9AM-7PM",
    "latitude": 13.3390,
    "longitude": 77.1018,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 32,
    "name": "Smart City Dumping Yard",
    "city": "Davanagere",
    "type": "universal",
    "address": "Kundavada Rd, Vinobha Nagar, Davangere 577006",
    "phone": "-",
    "hours": "Open 24 hours",
    "latitude": 14.4780,
    "longitude": 75.9160,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 33,
    "name": "Parkar Pillows & Cotton Waste",
    "city": "Davanagere",
    "type": "recyclable",
    "address": "Bismillah Layout, Millath Extension Area, Davangere 577001",
    "phone": "99011 77707",
    "hours": "Daily 9:30AM-9PM (closed Fri)",
    "latitude": 14.4645,
    "longitude": 75.9180,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 34,
    "name": "Carbasket Vehicle Scrapping Platform",
    "city": "Ballari",
    "type": "recyclable",
    "address": "Railway Station Approach Rd, Cowl Bazaar, Ballari 583101",
    "phone": "-",
    "hours": "Open 24 hours",
    "latitude": 15.1450,
    "longitude": 76.9230,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 35,
    "name": "Roshan Traders",
    "city": "Ballari",
    "type": "recyclable",
    "address": "UHTC Ranithota, Ballari 583101",
    "phone": "-",
    "hours": "Daily 9:30AM-6:30PM",
    "latitude": 15.1465,
    "longitude": 76.9270,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 36,
    "name": "Revive Waste Management",
    "city": "Kalaburagi",
    "type": "recyclable",
    "address": "KIADB IInd Stage, Humnabad Rd, Kapnoor, Kalaburagi 585104",
    "phone": "73826 80786",
    "hours": "Mon-Sat, varies; closed some days",
    "latitude": 17.3470,
    "longitude": 76.8330,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 37,
    "name": "Gulbarga Scrap Traders",
    "city": "Kalaburagi",
    "type": "universal",
    "address": "Humnabad Rd, Kapnoor, Kalaburagi 585104",
    "phone": "78978 91967",
    "hours": "Varies",
    "latitude": 17.3480,
    "longitude": 76.8350,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 38,
    "name": "Bharat Plastic Udyog",
    "city": "Kalaburagi",
    "type": "recyclable",
    "address": "KIADB 1st Stage, Kapnoor Industrial Area, Kalaburagi 585104",
    "phone": "78168 90009",
    "hours": "Daily 9AM-9PM",
    "latitude": 17.3490,
    "longitude": 76.8290,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 39,
    "name": "Dyaberi Multitrade",
    "city": "Vijayapura",
    "type": "recyclable",
    "address": "Station Back Rd, Shikarkhane, APMC, Vijayapura 586104",
    "phone": "97312 66525",
    "hours": "Daily 9AM-9PM",
    "latitude": 16.8300,
    "longitude": 75.7100,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 40,
    "name": "Vagdevi Traders",
    "city": "Vijayapura",
    "type": "recyclable",
    "address": "Station Back Rd, Shikarkhane, Jadar Galli, Vijayapura 586104",
    "phone": "72043 94024",
    "hours": "Daily, hours vary",
    "latitude": 16.8310,
    "longitude": 75.7120,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 41,
    "name": "OURS Services",
    "city": "Udupi",
    "type": "universal",
    "address": "Bailoor, Bima Nagar, Udupi 576101",
    "phone": "75592 96521",
    "hours": "Daily 8AM-8PM",
    "latitude": 13.3410,
    "longitude": 74.7420,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 42,
    "name": "Yaseen Traders",
    "city": "Udupi",
    "type": "recyclable",
    "address": "Near Clay Art, Adi Udipi, Udupi 576103",
    "phone": "96320 02522",
    "hours": "Daily 9AM-6:30PM",
    "latitude": 13.3600,
    "longitude": 74.7460,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 43,
    "name": "Eshwari Battery Buyers",
    "city": "Hassan",
    "type": "hazardous",
    "address": "80 Feet Rd, Penshan Mohalla, Hassan 573202",
    "phone": "-",
    "hours": "Varies",
    "latitude": 13.0068,
    "longitude": 76.1000,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 44,
    "name": "Amoggh Mandya Garbage Services",
    "city": "Mandya",
    "type": "universal",
    "address": "Tirumakudalu Narasipura - Sira Rd, Vidya Nagar, Mandya 571401",
    "phone": "-",
    "hours": "Varies",
    "latitude": 12.5222,
    "longitude": 76.8950,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 45,
    "name": "Enviro Biotech",
    "city": "Bidar",
    "type": "hazardous",
    "address": "MIG 82, New KHB Colony, Pratap Nagar, Bidar 585402",
    "phone": "83102 85507",
    "hours": "Mon-Sat 9AM-6PM, Sun 7AM-3PM",
    "latitude": 17.9100,
    "longitude": 77.5170,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 46,
    "name": "Chitradurga Waste Disposal Centre",
    "city": "Chitradurga",
    "type": "universal",
    "address": "Hosa Dyamavanahalli, Chitradurga 577524",
    "phone": "-",
    "hours": "Varies",
    "latitude": 14.2360,
    "longitude": 76.3900,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 47,
    "name": "Royal Scrap Buyers",
    "city": "Chamarajanagar",
    "type": "recyclable",
    "address": "Santhe Marahalli Circle, Galipur, Chamarajanagar 571313",
    "phone": "-",
    "hours": "Daily 9AM-7:30PM",
    "latitude": 11.9230,
    "longitude": 76.9430,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 48,
    "name": "Ramu Enterprises",
    "city": "Chamarajanagar",
    "type": "recyclable",
    "address": "Gundlupet-Chamarajanagara Rd, Chamarajanagar 571313",
    "phone": "-",
    "hours": "Varies",
    "latitude": 11.9245,
    "longitude": 76.9450,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 49,
    "name": "Madikeri SWM Site",
    "city": "Madikeri",
    "type": "universal",
    "address": "Madikeri 571201",
    "phone": "-",
    "hours": "Varies",
    "latitude": 12.4244,
    "longitude": 75.7382,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  },
  {
    "id": 50,
    "name": "Karnataka State Pollution Control Board - Regional Office Madikeri",
    "city": "Madikeri",
    "type": "universal",
    "address": "St Joseph's Convent Road, Bhagavathi Nagar, Madikeri 571201",
    "phone": "-",
    "hours": "Mon-Sat 10AM-5:30PM",
    "latitude": 12.4265,
    "longitude": 75.7395,
    "coordinate_precision": "Approximate/locality-level; verify before production use"
  }
]

def seed_facilities():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Upsert the 50 facilities with exact IDs
        upsert_query = """
            INSERT INTO disposal_locations (
                id, name, category, address, city, latitude, longitude, phone, operating_hours
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                category = EXCLUDED.category,
                address = EXCLUDED.address,
                city = EXCLUDED.city,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                phone = EXCLUDED.phone,
                operating_hours = EXCLUDED.operating_hours;
        """
        
        for item in facilities_data:
            cursor.execute(upsert_query, (
                item["id"],
                item["name"].strip(),
                item["type"].strip().capitalize(),
                item["address"].strip(),
                item["city"].strip(),
                float(item["latitude"]),
                float(item["longitude"]),
                item["phone"].strip(),
                item["hours"].strip()
            ))
            
        # 2. If there are any facilities with id > 50, clean them up
        cursor.execute("DELETE FROM disposal_locations WHERE id > 50")
        
        # 3. Reset the primary key sequence so future additions get ID 51+
        cursor.execute("SELECT setval(pg_get_serial_sequence('disposal_locations', 'id'), COALESCE((SELECT MAX(id) FROM disposal_locations), 1))")
        
        conn.commit()
        
        cursor.execute("SELECT COUNT(*) as cnt FROM disposal_locations")
        count = cursor.fetchone()["cnt"]
        print(f"Successfully seeded! Total facilities in database: {count}")
        
        # Show first 5 and last 5 facilities
        cursor.execute("SELECT id, name, city, category, phone FROM disposal_locations ORDER BY id ASC LIMIT 5")
        print("\nFirst 5 facilities:")
        for r in cursor.fetchall():
            print(f"  #{r['id']}: {r['name']} ({r['city']}) - [{r['category']}]")
            
        cursor.execute("SELECT id, name, city, category, phone FROM disposal_locations ORDER BY id DESC LIMIT 5")
        print("\nLast 5 facilities:")
        for r in cursor.fetchall():
            print(f"  #{r['id']}: {r['name']} ({r['city']}) - [{r['category']}]")

if __name__ == "__main__":
    seed_facilities()
