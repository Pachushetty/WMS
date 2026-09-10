"""
EcoCycle AI — Flask Web App
============================

A simple web interface for the trained waste-classification CNN.

Pages:
    /            Home
    /detect      Upload an image and get a live prediction
    /guide       Recycling / disposal guidance for each category
    /about       About the project

API:
    POST /predict   Accepts an uploaded image, returns JSON:
                     { "class": ..., "confidence": ..., "probabilities": {...} }

This app only READS the trained model from ../model/waste_model.h5.
It does not modify the dataset, the training script, or the model.
"""

import base64
import json
import os
import re
import secrets
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

try:
    from dotenv import load_dotenv
    # Load .env from project root or current directory
    for env_candidate in [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]:
        if env_candidate.exists():
            load_dotenv(dotenv_path=env_candidate, override=False)
            break
    else:
        load_dotenv()
except ImportError:
    pass

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    session,
    redirect,
    url_for,
    flash,
    abort,
)
from werkzeug.utils import secure_filename

import numpy as np
from PIL import Image, UnidentifiedImageError
from tensorflow.keras.models import load_model
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input

from groq import Groq

from database import (
    init_db,
    create_user,
    authenticate_user,
    get_user_by_id,
    get_all_users,
    save_classification,
    get_classifications,
    delete_classification_record,
    delete_classification_for_user,
    get_admin_dashboard_stats,
    create_disposal_request,
    get_user_disposal_requests,
    get_disposal_request_by_id,
    get_all_disposal_requests,
    get_all_disposal_locations,
    get_disposal_location_by_id,
    add_disposal_location,
    update_disposal_location,
    delete_disposal_location,
    update_disposal_request_status,
    verify_disposal_request,
    delete_disposal_request,
    get_nearby_disposal_locations,
    get_disposal_requests_stats,
    create_user_notification,
    get_user_notifications,
    mark_user_notifications_read,
    delete_user_notifications,
    create_collection_request,
    get_user_collection_requests,
    get_collection_request_by_id,
    get_all_collection_requests,
    update_collection_request_status,
    delete_collection_request,
    get_collection_requests_stats,
    get_all_collection_schedules,
    get_collection_schedule_by_id,
    create_collection_schedule,
    update_collection_schedule,
    toggle_collection_schedule,
    delete_collection_schedule,
    find_matching_schedule_for_area,
    next_occurrence_date,
    save_user_location,
    get_user_location,
    get_disposal_request_by_classification_id,
    update_disposal_request_location_and_center,
    reassign_user_disposal_requests_to_location,
    WEEKDAYS,
)

def _format_time_12h(hhmm: str) -> str:
    """Formats "09:00" -> "9:00 AM" for display."""
    try:
        hh, mm = [int(part) for part in (hhmm or "").strip().split(":")]
    except (ValueError, TypeError):
        return hhmm or ""
    suffix = "PM" if hh >= 12 else "AM"
    h12 = hh % 12 or 12
    return f"{h12}:{mm:02d} {suffix}"


def _format_date_display(iso_date: str) -> str:
    """Formats an ISO date "2026-09-07" -> "Mon, Sep 7" for display."""
    if not iso_date:
        return ""
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d")
    except ValueError:
        return iso_date
    return f"{d.strftime('%a, %b')} {d.day}"


def geocode_location(area: str, pincode: str = "", address: str = ""):
    """Geocodes Area + PIN Code + Address into Latitude and Longitude using
    OpenStreetMap Nominatim with cascading fallback queries.
    Returns (lat, lng, display_name) on success, or None on failure.
    """
    area = (area or "").strip()
    pincode = (pincode or "").strip()
    address = (address or "").strip()

    if not area and not pincode:
        return None

    queries = []
    if address and area and pincode:
        queries.append(f"{address}, {area}, {pincode}")
    if address and area:
        queries.append(f"{address}, {area}")
    if area and pincode:
        queries.append(f"{area}, {pincode}")
    if pincode and not area:
        queries.append(pincode)
    if area:
        queries.append(area)
    if pincode:
        queries.append(pincode)

    # Remove duplicates while preserving order
    seen = set()
    unique_queries = []
    for q in queries:
        cleaned = q.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            unique_queries.append(cleaned)

    headers = {
        "User-Agent": "EcoCycle-WasteManagement/2.0 (contact: admin@ecocycle.ai)",
        "Accept": "application/json"
    }

    for query in unique_queries:
        try:
            params = urllib.parse.urlencode({"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1})
            url = f"https://nominatim.openstreetmap.org/search?{params}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data and len(data) > 0:
                        lat = float(data[0]["lat"])
                        lng = float(data[0]["lon"])
                        display_name = data[0].get("display_name", query)
                        if -90 <= lat <= 90 and -180 <= lng <= 180:
                            return lat, lng, display_name
        except Exception:
            continue

    return None


def reverse_geocode_location(lat: float, lng: float):
    """Reverse geocodes Latitude and Longitude into Area, PIN Code, and Address
    using OpenStreetMap Nominatim. Returns dict with area, pincode, address, lat, lng,
    or None on failure.
    """
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None

    headers = {
        "User-Agent": "EcoCycle-WasteManagement/2.0 (contact: admin@ecocycle.ai)",
        "Accept": "application/json"
    }
    url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={lat}&lon={lng}&zoom=16&addressdetails=1"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                addr = data.get("address") or {}
                area = (
                    addr.get("suburb")
                    or addr.get("neighbourhood")
                    or addr.get("village")
                    or addr.get("town")
                    or addr.get("city_district")
                    or addr.get("hamlet")
                    or addr.get("locality")
                    or addr.get("municipality")
                    or addr.get("city")
                    or ""
                ).strip()
                pincode = (addr.get("postcode") or "").strip()
                address_parts = [
                    addr.get("road"),
                    addr.get("suburb"),
                    addr.get("city") or addr.get("town") or addr.get("village")
                ]
                address_parts = [p.strip() for p in address_parts if p and p.strip()]
                address_text = ", ".join(address_parts) if address_parts else (data.get("display_name") or "")

                return {
                    "area": area,
                    "pincode": pincode,
                    "address": address_text,
                    "display_name": data.get("display_name") or "",
                    "lat": lat,
                    "lng": lng,
                }
    except Exception:
        pass

    return None


try:
    from dotenv import load_dotenv
    load_dotenv()  # loads GROQ_API_KEY from a local .env file, if present
except ImportError:
    pass  # python-dotenv is optional; env vars can also be set directly


# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "model" / "waste_model.h5"
UPLOAD_DIR = Path(__file__).resolve().parent / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Must match the class order used during training (EXPECTED_CLASSES in
# training/train_model.py): Hazardous=0, Organic=1, Recyclable=2
CLASS_NAMES = ["Hazardous", "Organic", "Recyclable"]

IMAGE_SIZE = (224, 224)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB upload limit

# If the model's top prediction confidence is below this, we warn the user
# that the image may not be a clear/recognizable waste item. This is a
# heuristic safeguard, not a guarantee — the model can still be confidently
# wrong on images outside its 3 known classes (see README for details).
CONFIDENCE_THRESHOLD = 70.0

# Short, general disposal / recycling guidance per class.
# NOTE: this is general educational guidance written for this project,
# not sourced from the model or any specific local authority. Always
# check local municipal rules for anything hazardous.
# Short, general disposal / recycling / material guidance.
GUIDANCE = {
    "Hazardous": {
        "icon": "⚠️",
        "color": "#D64550",
        "summary": "Do not place in regular household trash.",
        "tips": [
            "Take it to a designated hazardous waste collection center or e-waste drop-off point.",
            "Keep batteries, chemicals, paints, and electronics separate from other waste.",
            "Never pour hazardous liquids down the drain.",
            "Store safely (upright, sealed) until proper disposal is possible.",
        ],
    },
    "Organic": {
        "icon": "🌱",
        "color": "#52B788",
        "summary": "Suitable for composting.",
        "tips": [
            "Place in a compost bin or municipal organic waste collection if available.",
            "Avoid mixing with plastic or non-biodegradable packaging.",
            "Food scraps and garden waste break down naturally into compost.",
            "Keep organic waste separate to avoid contaminating recyclables.",
        ],
    },
    "Recyclable": {
        "icon": "♻️",
        "color": "#457B9D",
        "summary": "Can be processed and reused.",
        "tips": [
            "Rinse containers before recycling to remove food residue.",
            "Flatten cardboard and plastic bottles to save space.",
            "Check local recycling guidelines, as accepted materials vary by area.",
            "Keep recyclables dry and free of contamination for best results.",
        ],
    },
}

NON_WASTE_GUIDANCE = {
    "Human/Animal": {
        "icon": "🐾",
        "color": "#10B981",
        "summary": "Living human or animal — not waste under any circumstance.",
        "tips": [
            "Living beings are never classified or handled as waste.",
            "Ensure a safe, healthy, and humane living environment.",
            "Provide appropriate nutrition, hydration, and care for domestic pets.",
            "Contact local animal welfare organizations if an animal requires assistance.",
        ],
    },
    "Food / Organic Material": {
        "icon": "🍎",
        "color": "#10B981",
        "summary": "Fresh edible food or organic material — suitable for consumption.",
        "tips": [
            "Store in clean, dry, or refrigerated conditions to maintain freshness.",
            "Consume before expiration to prevent unnecessary food waste.",
            "When preparing, collect peelings and scraps for organic composting.",
            "Do not discard edible food unnecessarily.",
        ],
    },
    "Battery / Hazardous Material": {
        "icon": "🔋",
        "color": "#F59E0B",
        "summary": "Active battery or electrical storage device — handle with safety.",
        "tips": [
            "Store in a cool, dry place away from direct sunlight and metal objects.",
            "Do not puncture, crush, or expose to excessive heat.",
            "When depleted or damaged in the future, take to a dedicated hazardous e-waste drop-off.",
            "Never incinerate or throw batteries into ordinary household bins.",
        ],
    },
    "Plastic / Recyclable Material": {
        "icon": "🧴",
        "color": "#2563EB",
        "summary": "Usable plastic product or material — preserve for continued use.",
        "tips": [
            "Reuse plastic containers when clean to reduce single-use plastic consumption.",
            "Keep clean and store in dry conditions for repeated usage.",
            "When discarded at end-of-life, rinse and sort into Recyclable collection.",
            "Check resin identification code for municipal recycling suitability.",
        ],
    },
    "Paper/Cardboard / Recyclable Material": {
        "icon": "📦",
        "color": "#2563EB",
        "summary": "Usable paper or cardboard material — preserve in dry conditions.",
        "tips": [
            "Reuse boxes and packaging for household storage or shipping.",
            "Keep away from moisture and oil to maintain material fiber strength.",
            "When discarded at end of life, flatten and place into paper recycling.",
            "Remove plastic adhesive tape and metal staples where possible.",
        ],
    },
    "Metal / Recyclable Material": {
        "icon": "🥫",
        "color": "#2563EB",
        "summary": "Usable metal item or container — maintain in dry conditions.",
        "tips": [
            "Keep clean and dry to prevent surface corrosion or oxidation.",
            "Suitable for multiple reuses or refilling where appropriate.",
            "When discarded, place in dedicated metal recycling collection.",
            "Metals can be recycled infinitely without degradation.",
        ],
    },
    "Glass / Recyclable Material": {
        "icon": "🫙",
        "color": "#2563EB",
        "summary": "Usable glass container or product — handle with care.",
        "tips": [
            "Wash and sterilize for food storage or household organisation.",
            "Handle carefully to prevent chipping or sharp breakage hazards.",
            "When discarded, rinse thoroughly and place in designated glass recycling bins.",
            "Glass is 100% recyclable and can be processed repeatedly.",
        ],
    },
}


def get_guidance_for_item(
    category: str,
    is_waste: bool,
    item_name: str = "",
    condition: str = "",
    custom_warning: str = "",
    custom_instructions: list = None,
):
    """Returns appropriate visual styling and dynamic, item-specific guidance directives."""
    item_lower = (item_name or "").strip().lower()
    cat_lower = (category or "").strip().lower()

    # Primary: If the AI API generated an item-specific warning & instructions, use them directly
    if custom_warning and custom_instructions and len(custom_instructions) >= 2:
        is_hazard = is_waste and ("hazard" in cat_lower or "hazard" in item_lower)
        is_organic = "organic" in cat_lower or "food" in cat_lower or "organic" in item_lower
        icon = "⚠️" if is_hazard else ("🌱" if is_organic else ("♻️" if is_waste else "✨"))
        color = "#EF4444" if is_hazard else ("#059669" if is_organic else ("#2563EB" if is_waste else "#10B981"))
        return {
            "icon": icon,
            "color": color,
            "summary": custom_warning,
            "tips": custom_instructions,
        }

    if is_waste:
        # 1. Battery (High priority)
        if re.search(r"\b(batter(y|ies)|lithium|li-ion|button\s*cell|coin\s*cell|accumulator|power\s*cell)\b", item_lower) or (
            re.search(r"\b(battery|batteries)\b", cat_lower) and not item_lower
        ):
            return {
                "icon": "🔋",
                "color": "#EF4444",
                "summary": "Do not place batteries in regular household trash.",
                "tips": [
                    "Take the battery to a designated battery/e-waste collection center.",
                    "Keep batteries separate from other waste.",
                    "Do not crush, puncture, burn, or dismantle the battery.",
                    "Store safely until proper disposal is possible.",
                ],
            }

        # 2. Chemical / Paint / Hazardous Waste
        if re.search(r"\b(paint|paints|paint\s*can|solvent|solvents|thinner|motor\s*oil|engine\s*oil|pesticide|pesticides|insecticide|insecticides|fertilizer|bleach|varnish|chemical|chemicals|corrosive|toxic|flammable|poison)\b", item_lower) or re.search(r"\b(chemical|paint)\b", cat_lower):
            return {
                "icon": "⚠️",
                "color": "#EF4444",
                "summary": "Toxic and hazardous! Never pour chemicals or paint down household drains, gutters, or onto soil.",
                "tips": [
                    "Keep in original labeled container with cap sealed tightly to prevent vapor leaks.",
                    "Store safely in an upright position in a well-ventilated, secure location away from heat.",
                    "Never mix different chemical remnants or household solvents together.",
                    "Take directly to an authorized municipal household hazardous waste (HHW) collection facility.",
                ],
            }

        # 3. Electronic Waste / Laptop / Gadgets
        if re.search(r"\b(e-waste|electronic|electronics|laptop|laptops|computer|computers|pc|desktop|smartphone|smartphones|cell\s*phone|mobile\s*phone|tablet|tablets|ipad|circuit|motherboard|printer|printers|monitor|monitors|television|tv|charger|chargers|keyboard|mouse|headphones|earbuds|hard\s*drive)\b", item_lower) or re.search(r"\b(electronic|e-waste)\b", cat_lower):
            return {
                "icon": "💻",
                "color": "#EF4444",
                "summary": "Do not discard electronics in municipal trash; contains toxic heavy metals and recyclable rare components.",
                "tips": [
                    "Back up personal data and perform a permanent factory wipe on digital storage devices.",
                    "Remove batteries if detachable and dispose of them in dedicated battery drop-offs.",
                    "Bring to certified e-waste drop-off centers, electronics retailers, or municipal collection events.",
                    "Never dismantle, crush screens, or burn electronic circuit boards.",
                ],
            }

        # 4. Medical / Biomedical Waste
        if re.search(r"\b(syringe|syringes|needle|needles|sharps|medicine|medicines|pill|pills|blister\s*pack|mask|masks|bandage|bandages|biomedical|clinical)\b", item_lower):
            return {
                "icon": "🩺",
                "color": "#EF4444",
                "summary": "Biohazard risk! Keep protected to prevent pathogen transmission or needle injury.",
                "tips": [
                    "Place sharps and needles in a puncture-proof, rigid biohazard container.",
                    "Return unused or expired medications to pharmacy drop-off collection boxes.",
                    "Never flush medications down toilets or discard loose sharps in household trash.",
                    "Follow municipal biohazard disposal protocols for specialized clinical handling.",
                ],
            }

        # 5. Plastic Bottle
        if re.search(r"\b(plastic\s*bottle|pet\s*bottle|water\s*bottle|soda\s*bottle|beverage\s*bottle|plastic\s*jug|milk\s*jug|detergent\s*bottle|shampoo\s*bottle)\b", item_lower) or (
            "bottle" in item_lower and ("plastic" in item_lower or "pet" in item_lower or "plastic" in cat_lower or "pet" in cat_lower)
        ) or (item_lower == "bottle" and "glass" not in cat_lower):
            return {
                "icon": "🧴",
                "color": "#2563EB",
                "summary": "Empty and rinse before placing in plastic recycling.",
                "tips": [
                    "Empty all residual liquids and rinse the bottle clean.",
                    "Remove plastic caps and non-recyclable wraps if required locally.",
                    "Crush or flatten the bottle to reduce volume and save bin space.",
                    "Deposit into designated plastic or blue recycling stream.",
                ],
            }

        # 6a. Picture Frame / Mirror / Broken Glass
        if re.search(r"\b(picture\s*frame|photo\s*frame|picture\s*frames|photo\s*frames|mirror|mirrors|framed\s*glass|broken\s*frame|broken\s*glass|window\s*glass|window\s*pane|glass\s*frame|frame)\b", item_lower):
            return {
                "icon": "🖼️",
                "color": "#EF4444",
                "summary": "Broken glass is sharp and hazardous — wrap securely before disposal and never place loose shards in recycling bins.",
                "tips": [
                    "Wear thick gloves when handling broken glass to avoid cuts and lacerations.",
                    "Wrap all glass fragments tightly in several layers of newspaper, seal with tape, and label as 'Broken Glass'.",
                    "Separate the wooden, plastic, or metal frame from the glass and recycle frame materials individually.",
                    "Dispose of sealed glass waste in a rigid container or at a designated glass/hazardous waste drop-off site.",
                ],
            }

        # 6b. Glass / Glass Bottle
        if re.search(r"\b(glass|glasses|glass\s*bottle|glass\s*jar|wine\s*bottle|beer\s*bottle|glassware|mason\s*jar)\b", item_lower) or (
            "glass" in cat_lower and "plastic" not in item_lower
        ):
            return {
                "icon": "🫙",
                "color": "#2563EB",
                "summary": "Handle carefully to avoid breakage; do not mix window glass or ceramics with bottle recycling.",
                "tips": [
                    "Empty and rinse the glass bottle or jar with clean water.",
                    "Remove plastic or metal lids and corks (recycle metal/plastic separately).",
                    "Keep glass colors separated (flint/clear, amber/brown, green) if required locally.",
                    "Place unbroken in designated glass bottle banks or curbside collection.",
                ],
            }

        # 7. Metal / Aluminium Can
        if re.search(r"\b(metal|metals|aluminium|aluminum|tin|tins|steel|can|cans|soda\s*can|beer\s*can|beverage\s*can|food\s*can|tin\s*can|aerosol|foil|scrap\s*metal|brass|copper|iron)\b", item_lower) or (
            "metal" in cat_lower and "plastic" not in item_lower
        ):
            return {
                "icon": "🥫",
                "color": "#2563EB",
                "summary": "Rinse metal containers thoroughly to eliminate food, grease, or chemical residue.",
                "tips": [
                    "Rinse out liquids, food residue, or oils completely.",
                    "Do not crush aerosol cans or puncture pressurized canisters.",
                    "Recycle metal lids inside the can or attach securely to prevent sharp edges.",
                    "Place in designated metal recycling or curbside dry recyclables collection.",
                ],
            }

        # 8. Paper / Cardboard
        if re.search(r"\b(paper|cardboard|carton|cartons|newspaper|newspapers|magazine|magazines|paper\s*bag|office\s*paper|kraft|envelope|envelopes|flyer|flyers|box|boxes)\b", item_lower) or (
            "paper" in cat_lower or "cardboard" in cat_lower
        ):
            return {
                "icon": "📦",
                "color": "#2563EB",
                "summary": "Keep paper clean, dry, and free of food grease, wax, or oil.",
                "tips": [
                    "Flatten cardboard boxes and remove plastic packing tape or bubble wrap.",
                    "Keep paper dry; soiled or greasy paper (e.g. pizza boxes) must be composted, not recycled.",
                    "Remove plastic window films, spiral bindings, and large metal clips.",
                    "Deposit in the dedicated paper and cardboard recycling bin.",
                ],
            }

        # 9. General Plastic
        if re.search(r"\b(plastic|plastics|polythene|polyethylene|polypropylene|styrofoam|polystyrene|pvc|tupperware)\b", item_lower) or "plastic" in cat_lower:
            return {
                "icon": "♻️",
                "color": "#2563EB",
                "summary": "Clean thoroughly and check resin identification code (1-7) before recycling.",
                "tips": [
                    "Scrape out and rinse all food, oil, or chemical residue.",
                    "Separate flexible soft film and bags from rigid plastic containers.",
                    "Keep plastic clean and dry to avoid contaminating recycling batches.",
                    "Deposit in dedicated municipal plastic recycling or drop-off bins.",
                ],
            }

        # 10a. Fish / Meat / Animal-based Food Waste (before generic organic)
        if re.search(r"\b(fish|fishes|fish\s*head|fish\s*heads|viscera|entrails|guts|offal|shellfish|shrimp|prawn|crab|lobster|squid|meat|chicken|poultry|mutton|pork|beef|lamb|bone|bones|carcass)\b", item_lower):
            return {
                "icon": "🐟",
                "color": "#EF4444",
                "summary": "Fish and meat waste decomposes rapidly, produces strong odours, and attracts pests \u2014 handle with urgency and hygiene.",
                "tips": [
                    "Wrap tightly in newspaper or biodegradable bags to contain odour and prevent leakage.",
                    "Store in a sealed, lidded container and keep refrigerated or frozen until collection day if possible.",
                    "Place in organic/wet waste bins on scheduled collection days \u2014 never leave exposed in open bins.",
                    "Do not mix with dry recyclables; dispose separately to avoid contaminating recycling streams.",
                ],
            }

        # 10b. Organic Waste / Food Waste (generic plant-based / compostable)
        if re.search(r"\b(organic|food|fruit|fruits|vegetable|vegetables|banana|apple|orange|peel|peels|scraps|leftover|leftovers|compost|compostable|biodegradable|egg\s*shell|eggshell|coffee\s*grounds|tea\s*bag|leaves|plant|plants|garden\s*waste)\b", item_lower) or (
            "organic" in cat_lower or "food" in cat_lower or "compost" in cat_lower
        ):
            return {
                "icon": "🌱",
                "color": "#059669",
                "summary": "Keep organic materials separated from plastics, glass, and non-biodegradable packaging.",
                "tips": [
                    "Collect food scraps, fruit peels, and garden trimmings in a dedicated compost bin.",
                    "Do not include plastic bags, synthetic stickers, or chemically treated wrappers.",
                    "Deposit into green composting bins, backyard compost piles, or municipal bio-waste.",
                    "Layer with dry carbon materials (leaves, sawdust) to accelerate natural aerobic breakdown.",
                ],
            }

        # 11. Textile / Clothing
        if re.search(r"\b(clothes|clothing|textile|textiles|fabric|fabrics|shirt|pants|shoe|shoes|jacket|towel|apparel)\b", item_lower):
            return {
                "icon": "👕",
                "color": "#2563EB",
                "summary": "Keep textiles clean and dry to allow fabric recycling or charitable donation.",
                "tips": [
                    "If wearable, donate to local charities, clothing drives, or thrift organizations.",
                    "Ensure items are clean and completely dry to prevent mold growth.",
                    "For torn or unwearable fabrics, deposit in designated textile recycling bins.",
                    "Do not discard into mixed landfill trash.",
                ],
            }

        # 12. Dynamic Item-Specific Fallback for Any Detected Waste Item
        display = item_name.strip() if item_name.strip() else ("Hazardous Waste" if "hazard" in cat_lower else ("Organic Waste" if "organic" in cat_lower else "Recyclable Item"))
        display_lower = display.lower()

        if "hazard" in cat_lower:
            return {
                "icon": "⚠️",
                "color": "#EF4444",
                "summary": f"Potentially hazardous {display_lower} — handle with protective care and never mix with domestic trash.",
                "tips": [
                    f"Take {display_lower} to a designated municipal hazardous waste collection facility.",
                    f"Keep {display_lower} sealed and isolated from domestic waste streams to prevent chemical reactions.",
                    f"Avoid direct skin contact, inhalation of fumes, or puncturing the item.",
                    f"Consult local hazardous waste disposal schedules for specialized collection days.",
                ],
            }
        if "organic" in cat_lower or "food" in cat_lower:
            return {
                "icon": "🌱",
                "color": "#059669",
                "summary": f"Separate {display_lower} from plastics, glass, and non-biodegradable packaging.",
                "tips": [
                    f"Collect {display_lower} in a dedicated organic or compost container.",
                    f"Keep free of plastic bags, synthetic wrappers, or chemical contaminants.",
                    f"Deposit into green municipal bio-waste bins or suitable composting systems.",
                    f"Dispose promptly or refrigerate to prevent odour buildup and attracting pests.",
                ],
            }

        return {
            "icon": "♻️",
            "color": "#2563EB",
            "summary": f"Prepare {display_lower} properly to support material recycling and circular recovery.",
            "tips": [
                f"Empty and rinse {display_lower} thoroughly to eliminate liquid or food residue.",
                f"Separate composite parts, lids, or wrapping if required locally.",
                f"Flatten or consolidate {display_lower} to maximize recycling bin capacity.",
                f"Place into designated curbside recycling or authorized material recovery drop-off.",
            ],
        }

    # =========================================================================
    # NON-WASTE SECTION: Checked first by specific item, then category
    # =========================================================================

    # --- NON-WASTE item-specific rules (item name-based, checked before generic fallback) ---

    # NON-WASTE: Curtains / Drapes / Blinds / Rugs / Carpets
    if re.search(r"\b(curtain|curtains|drape|drapes|blind|blinds|valance|sheer|rug|rugs|carpet|carpets|mat|mats|drapery)\b", item_lower) or \
            re.search(r"\b(curtain|drape|blind|drapery)\b", cat_lower):
        return {
            "icon": "🏠",
            "color": "#10B981",
            "summary": "Curtains and home textiles are usable household items \u2014 care for them properly to maximise their lifespan.",
            "tips": [
                "Wash according to fabric care label instructions (machine wash, hand wash, or dry-clean only).",
                "Store in a cool, dry, ventilated space to prevent mildew, dust buildup, and colour fading.",
                "When replacing, donate to charity shops, thrift stores, or community donation drives if in good condition.",
                "At end-of-life, deposit in designated textile recycling bins \u2014 do not place in general household waste.",
            ],
        }

    # NON-WASTE: Furniture / Chair / Sofa / Table / Shelf / Bed / Cabinet / Desk
    if re.search(r"\b(furniture|chair|sofa|couch|table|desk|shelf|shelves|cabinet|wardrobe|bed|drawer|bench|stool|rack|bookcase|cupboard)\b", item_lower) or "furniture" in cat_lower:
        return {
            "icon": "🪑",
            "color": "#10B981",
            "summary": "Usable furniture \u2014 maintain in good condition and explore donation or resale before disposal.",
            "tips": [
                "Clean and maintain regularly (polish surfaces, tighten joints, treat scratches) to extend functional lifespan.",
                "Repair minor damage \u2014 scratches, loose screws, and worn upholstery are often cost-effective to fix.",
                "Donate to charity, second-hand shops, or list on community marketplace platforms if no longer needed.",
                "At end-of-life, arrange for a bulk waste collection or furniture recycling \u2014 do not leave on street.",
            ],
        }

    # NON-WASTE: Clothing / Apparel / Shoes / Bags / Accessories
    if re.search(r"\b(clothes|clothing|shirt|dress|trousers|jeans|skirt|jacket|coat|sweater|shoe|shoes|boot|sandal|bag|handbag|backpack|purse|wallet|belt|hat|cap|scarf|socks|gloves|apparel|garment|uniform)\b", item_lower) or \
            re.search(r"\b(cloth|textile|apparel|fashion)\b", cat_lower):
        return {
            "icon": "👕",
            "color": "#10B981",
            "summary": "Wearable clothing and accessories in good condition \u2014 donate or resell before considering disposal.",
            "tips": [
                "Wash and store according to the garment care label to maintain fabric quality.",
                "Donate to charity organisations, clothing banks, or thrift stores if no longer needed.",
                "Sell or swap through second-hand platforms and community groups to extend useful life.",
                "At end-of-life, deposit in designated textile or clothing recycling collection points.",
            ],
        }

    # NON-WASTE: Books / Magazines / Notebooks
    if re.search(r"\b(book|books|magazine|novel|textbook|notebook|journal|comic|manual|guide|encyclopedia|dictionary)\b", item_lower) or "book" in cat_lower:
        return {
            "icon": "📚",
            "color": "#10B981",
            "summary": "Usable books and publications \u2014 donate, swap, or share rather than discard.",
            "tips": [
                "Donate to local libraries, schools, literacy programmes, or community book-swap shelves.",
                "Sell or exchange through second-hand bookshops, online platforms, or neighbourhood groups.",
                "Keep dry and away from direct sunlight to prevent yellowing, warping, and mould.",
                "At end-of-life, remove hard covers or metal rings and place paper content in paper recycling.",
            ],
        }

    # NON-WASTE: Toys / Games / Sporting goods
    if re.search(r"\b(toy|toys|game|games|puzzle|doll|action\s*figure|board\s*game|teddy|stuffed|lego|playset|ball|bicycle|bike|scooter|skateboard|sport)\b", item_lower) or "toy" in cat_lower:
        return {
            "icon": "🧸",
            "color": "#10B981",
            "summary": "Usable toys and games \u2014 clean, donate, or resell to give a second life before disposal.",
            "tips": [
                "Clean and sanitise thoroughly before donating to charities, schools, or children's programmes.",
                "Check for and remove batteries, disposing of them separately at battery collection points.",
                "Donate to charity organisations, toy drives, or community centres.",
                "At end-of-life, separate plastic, metal, and fabric components for appropriate recycling streams.",
            ],
        }

    # NON-WASTE: Kitchen items / Cookware / Utensils / Appliances
    if re.search(r"\b(kitchen|utensil|cookware|pot|pan|plate|bowl|cup|mug|cutlery|fork|spoon|knife|tray|container|blender|toaster|kettle|microwave|oven|fridge|refrigerator)\b", item_lower) or \
            re.search(r"\b(kitchen|cookware|utensil|appliance)\b", cat_lower):
        return {
            "icon": "🍳",
            "color": "#10B981",
            "summary": "Usable kitchen items \u2014 maintain in clean, hygienic condition and consider donating when replacing.",
            "tips": [
                "Clean thoroughly after each use and store in dry, covered, hygienic conditions.",
                "Donate to charity kitchens, community organisations, or second-hand shops when replacing.",
                "Repair handles, seals, and minor damage before replacing items prematurely.",
                "At end-of-life, separate metal, plastic, glass, and ceramic components for appropriate recycling.",
            ],
        }

    # NON-WASTE: Electronics / Gadgets (usable, not waste)
    if re.search(r"\b(phone|smartphone|tablet|laptop|computer|camera|television|tv|headphones|speaker|remote|charger|keyboard|mouse|gadget|device|console|gaming)\b", item_lower) or \
            (re.search(r"\b(electronic|device|gadget)\b", cat_lower) and "waste" not in cat_lower):
        return {
            "icon": "💻",
            "color": "#10B981",
            "summary": "Working electronics \u2014 maintain properly, and donate or resell rather than discard.",
            "tips": [
                "Keep software updated and perform regular maintenance to extend device lifespan.",
                "Protect with suitable cases and avoid exposure to moisture, heat, or physical shock.",
                "Donate, resell, or trade in through manufacturer or retailer take-back programmes when upgrading.",
                "At end-of-life, take to a certified e-waste collection centre \u2014 never place in general waste.",
            ],
        }

    # NON-WASTE: Plants / Flowers / Potted Plants
    if re.search(r"\b(plant|plants|flower|flowers|potted\s*plant|tree|sapling|herb|herbs|cactus|succulent|shrub|fern|garden)\b", item_lower) or "plant" in cat_lower:
        return {
            "icon": "🌿",
            "color": "#10B981",
            "summary": "Living plant \u2014 care for it properly to maintain health and longevity.",
            "tips": [
                "Water regularly as per species requirements \u2014 avoid over or under-watering.",
                "Place in an appropriate light environment (direct sun, indirect light, or shade).",
                "Repot when roots outgrow current container using suitable, nutrient-rich potting mix.",
                "Prune dead leaves and stems to promote healthy growth and prevent disease spread.",
            ],
        }

    # NON-WASTE: Named item fallback — item name known but no specific rule matched
    display_name = item_name if item_name else category
    return {
        "icon": "✨",
        "color": "#10B981",
        "summary": f"{display_name} is identified as a usable, non-waste item \u2014 care for it properly to extend its lifespan.",
        "tips": [
            f"Clean and maintain {display_name.lower()} regularly according to manufacturer or care guidelines.",
            "Store in appropriate conditions (dry, cool, ventilated) to prevent deterioration.",
            "Donate, sell, or give away when no longer personally needed rather than discarding.",
            "At end-of-life, separate materials and place in the correct recycling or disposal stream.",
        ],
    }


# ---------------------------------------------------------------------------
# Flask app setup & Database Initialization
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# --- SECRET_KEY -------------------------------------------------------------
# SECURITY: never fall back to a hardcoded string here. A fixed secret key
# baked into source code would let anyone who has read the code forge signed
# session cookies (e.g. a cookie claiming role=admin). If SECRET_KEY isn't
# set in the environment, generate a random one for this process instead —
# sessions just won't survive a restart, which is safe, whereas a guessable
# fixed key is not.
_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    _secret_key = secrets.token_hex(32)
    print(
        "WARNING: SECRET_KEY is not set in the environment. Using a random "
        "per-process key (all sessions will be invalidated on restart). Set "
        "SECRET_KEY in your .env for a stable, production-ready secret."
    )
app.secret_key = _secret_key

# --- Session cookie hardening ------------------------------------------------
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Only mark cookies "Secure" (HTTPS-only) when explicitly running in
# production, so local http://localhost development still works.
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV") == "production"

# Initialize database schema and default admin
try:
    init_db()
except Exception:  # noqa: BLE001
    # IMPORTANT: previously this only printed str(exc), which hides *where*
    # init_db() failed. If it fails partway through — e.g. on one of the
    # ALTER TABLE migrations — everything after that point in init_db()
    # (including seeding the default disposal_locations rows the
    # auto-assign feature depends on) never runs, and the app starts up
    # anyway with an incomplete schema. Logging the full traceback makes
    # that failure visible in the server logs instead of silently leaving
    # auto-assign broken with no explanation.
    import traceback
    print("=" * 70)
    print("DATABASE INIT FAILED — see traceback below.")
    print("Auto-assign and other features may not work until this is fixed.")
    print("=" * 70)
    traceback.print_exc()


# ---------------------------------------------------------------------------
# CSRF protection (lightweight, no extra dependency)
# ---------------------------------------------------------------------------
def generate_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = generate_csrf_token


@app.before_request
def enforce_csrf_protection():
    if request.method == "POST":
        submitted = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
        expected = session.get("csrf_token")
        if not expected or not submitted or not secrets.compare_digest(expected, submitted):
            abort(400, description="Invalid or missing CSRF token. Please refresh and try again.")


# ---------------------------------------------------------------------------
# Basic login rate limiting (in-memory, per-process)
# ---------------------------------------------------------------------------
_LOGIN_ATTEMPTS = {}
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300  # 5 minutes


def _login_rate_limited(key: str) -> bool:
    now = time.time()
    attempts = [t for t in _LOGIN_ATTEMPTS.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
    _LOGIN_ATTEMPTS[key] = attempts
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


def _record_login_attempt(key: str) -> None:
    _LOGIN_ATTEMPTS.setdefault(key, []).append(time.time())


@app.context_processor
def inject_auth_context():
    """Injects user authentication state into all rendered templates."""
    user_id = session.get("user_id")
    user = get_user_by_id(user_id) if user_id else None
    return {
        "current_user": user,
        "is_admin": session.get("is_admin", False),
    }


def admin_required(f):
    """Decorator to enforce administrator authentication on protected routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_admin") or not session.get("user_id"):
            flash("Administrator sign-in required to access this portal.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def login_required(f):
    """Decorator to enforce standard user authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in to access this page.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# Load the trained model once, at startup, so predictions are fast.
model = None
model_load_error = None
try:
    if not MODEL_PATH.exists():
        model_load_error = (
            f"Trained model not found at: {MODEL_PATH}\n"
            "Please run 'python train_model.py' inside the training/ folder "
            "first, so a model file is created."
        )
    else:
        model = load_model(MODEL_PATH)
except Exception as exc:  # noqa: BLE001 - we want to surface any load error clearly
    model_load_error = f"Failed to load model: {exc}"

# --- Groq vision model: 7-step waste & material classification ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_VISION_MODEL = "qwen/qwen3.6-27b"

groq_client = None
groq_load_error = None
if GROQ_API_KEY:
    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
    except Exception as exc:  # noqa: BLE001
        groq_load_error = f"Could not initialize Groq client: {exc}"
        print("WARNING:", groq_load_error)
else:
    groq_load_error = (
        "GROQ_API_KEY environment variable not set. Comprehensive vision pre-analysis "
        "will be skipped."
    )
    print("WARNING:", groq_load_error)

# --- Gemini vision model: fallback provider used only if Groq fails ---
# Called over plain HTTPS (no extra SDK dependency needed) so it stays
# lightweight — we already depend on `requests`.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
# "gemini-flash-latest" is a Google-maintained alias that always points at
# the current fast Gemini model, so this doesn't need to be hand-updated
# every time a specific dated model is deprecated.
GEMINI_VISION_MODEL = os.environ.get("GEMINI_VISION_MODEL", "gemini-flash-latest")
GEMINI_ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_VISION_MODEL}:generateContent"
)

if not GEMINI_API_KEY:
    print(
        "WARNING: GEMINI_API_KEY environment variable not set. "
        "Groq-outage fallback to Gemini will be skipped."
    )


def allowed_file(filename: str) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def preprocess_image(image_path: Path) -> np.ndarray:
    """
    Load an image and preprocess it exactly like training:
    resize to 224x224 and apply MobileNetV2's preprocess_input.
    """
    img = Image.open(image_path).convert("RGB")
    img = img.resize(IMAGE_SIZE)
    array = np.array(img).astype("float32")
    array = preprocess_input(array)
    array = np.expand_dims(array, axis=0)  # add batch dimension
    return array


class GroqAnalysisUnavailable(Exception):
    """
    Raised when the Groq vision pre-analysis step (Human/Animal + waste
    material check) could not be completed after retrying — e.g. a network
    connection error to the Groq API. This is distinct from
    "GROQ_API_KEY not configured", which is treated as an intentional
    degraded-mode deployment and silently falls back to the CNN-only path.

    We surface this separately so /predict can tell the user to retry
    instead of silently classifying an unrecognized subject (like a human
    face) as waste just because the safety-check step failed to run.
    """
    pass


class GeminiAnalysisUnavailable(Exception):
    """Same idea as GroqAnalysisUnavailable, but for the Gemini fallback path."""
    pass


class AllProvidersUnavailable(Exception):
    """
    Raised only when EVERY vision provider (Groq, then Gemini, then Groq
    again) has been tried and failed. /predict treats this exactly like
    GroqAnalysisUnavailable used to be treated: surface a 503 instead of
    silently falling back to CNN-only classification.
    """
    pass


def _parse_vision_analysis_json(raw: str) -> dict:
    """
    Shared response cleanup/parsing used by both analyze_image_groq and
    analyze_image_gemini, since both providers are prompted for the exact
    same JSON shape. Raises if the text can't be parsed as the expected
    object, so callers can treat that the same as any other provider
    failure (and retry / fall back to the next provider).
    """
    # Defensive: strip <think>...</think> if present
    if "<think>" in raw and "</think>" in raw:
        raw = raw.split("</think>", 1)[1].strip()

    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]

    data = json.loads(raw)

    obj = str(data.get("object", "Object")).strip()
    cond = str(data.get("condition", "Unknown")).strip()
    is_waste = data.get("is_waste")
    if not isinstance(is_waste, bool):
        is_waste = True if str(is_waste).lower() in ["true", "yes", "1"] else False
    cat = str(data.get("category", "General Material")).strip()
    reason = str(data.get("reason", "")).strip()

    warning = str(data.get("warning", "")).strip()
    raw_instructions = data.get("instructions")
    instructions = []
    if isinstance(raw_instructions, list):
        instructions = [str(x).strip() for x in raw_instructions if str(x).strip()]

    return {
        "object": obj,
        "condition": cond,
        "is_waste": is_waste,
        "category": cat,
        "reason": reason,
        "warning": warning,
        "instructions": instructions,
    }


VISION_ANALYSIS_PROMPT = (
    "You are an AI image-classification system for a waste-management application.\n"
    "Your job is NOT only to decide whether an item is waste. You must also identify what the item is and what category/material it belongs to.\n\n"
    "Follow this decision process exactly:\n\n"
    "STEP 1 — IDENTIFY THE OBJECT\n"
    "Look at the uploaded image and identify the main object clearly.\n\n"
    "STEP 2 — CHECK FOR HUMAN OR ANIMAL\n"
    "If the image contains a human or an animal as the main subject:\n"
    "- is_waste: false\n"
    "- object: \"Human\" or \"Animal\" (or specific name, e.g. \"Person\", \"Dog\", \"Cat\")\n"
    "- condition: \"Living\"\n"
    "- category: \"Human/Animal\"\n"
    "- reason: \"The image contains a living human/animal, which is not waste.\"\n"
    "STOP processing. Do NOT classify a human or animal as Organic, Recyclable, or Hazardous.\n\n"
    "STEP 3 — FOR ALL OTHER OBJECTS\n"
    "If the image contains an object, DO NOT stop just because the object is not waste.\n"
    "First identify:\n"
    "- object: name of the object (e.g. \"Banana\", \"Plastic Bottle\", \"Battery\", \"Cardboard Box\", \"Carrot\", \"Aluminum Can\")\n"
    "- condition: visible condition (e.g. \"Fresh\", \"New\", \"Used\", \"Rotten\", \"Damaged\", \"Empty\", \"Broken\", \"Discarded\", \"Spoiled\", \"Used/Discarded\")\n\n"
    "STEP 4 — DETERMINE WHETHER IT IS WASTE\n"
    "Decide whether the object is actually waste based on its visible condition and context.\n"
    "IMPORTANT: An object can belong to an organic, recyclable, or hazardous MATERIAL category even when it is NOT waste.\n"
    "- A fresh banana is organic material but is not waste.\n"
    "- A new plastic bottle is recyclable material but is not waste.\n"
    "- A new battery is a hazardous material but is not waste.\n\n"
    "STEP 5 — CLASSIFY THE CATEGORY\n"
    "If the object IS WASTE (is_waste: true), classify category as exactly one of:\n"
    "- \"Organic Waste\"\n"
    "- \"Recyclable Waste\"\n"
    "- \"Hazardous Waste\"\n\n"
    "If the object IS NOT WASTE (is_waste: false), classify what type of material/category it belongs to (e.g. \"Food / Organic Material\", \"Plastic / Recyclable Material\", \"Paper/Cardboard / Recyclable Material\", \"Battery / Hazardous Material\", \"Glass / Recyclable Material\", \"Metal / Recyclable Material\", etc.).\n\n"
    "STEP 6 — DO NOT CONFUSE MATERIAL WITH WASTE\n"
    "- Fresh banana -> object: \"Banana\", condition: \"Fresh\", is_waste: false, category: \"Food / Organic Material\", reason: \"Fresh edible fruit, currently usable food not waste.\"\n"
    "- Rotten banana -> object: \"Banana\", condition: \"Rotten\", is_waste: true, category: \"Organic Waste\", reason: \"Decomposed fruit unfit for consumption, suitable for composting.\"\n"
    "- Banana peel -> object: \"Banana Peel\", condition: \"Used/Discarded\", is_waste: true, category: \"Organic Waste\", reason: \"Discarded fruit peel suitable for composting.\"\n"
    "- New plastic bottle -> object: \"Plastic Bottle\", condition: \"New\", is_waste: false, category: \"Plastic / Recyclable Material\", reason: \"New intact bottle, not discarded waste.\"\n"
    "- Discarded plastic bottle -> object: \"Plastic Bottle\", condition: \"Used/Discarded\", is_waste: true, category: \"Recyclable Waste\", reason: \"Empty used plastic container suitable for recycling.\"\n"
    "- Battery (used/discarded) -> object: \"Battery\", condition: \"Used/Discarded\", is_waste: true, category: \"Hazardous Waste\", reason: \"Contains hazardous chemicals requiring safe e-waste disposal.\"\n\n"
    "STEP 7 — ACTIONABLE DISPOSAL / HANDLING PROTOCOL\n"
    "Generate an item-specific actionable disposal or handling protocol tailored DIRECTLY to the detected object:\n"
    "- warning: A concise 1-sentence safety or disposal warning specific to this exact item.\n"
    "- instructions: An array of exactly 3 to 4 concise, actionable, step-by-step instructions for disposing or handling this specific item.\n"
    "Do NOT give generic instructions. The warning and instructions must directly address the identified object.\n\n"
    "STEP 8 — FINAL RESPONSE\n"
    "Respond with ONLY a JSON object on a single line of the exact format:\n"
    "{\"object\": \"...\", \"condition\": \"...\", \"is_waste\": true/false, \"category\": \"...\", \"reason\": \"...\", \"warning\": \"...\", \"instructions\": [\"...\", \"...\", \"...\", \"...\"]}\n"
    "Do not include markdown code fences, backticks, or any other text before or after the JSON."
)


def _load_image_as_base64(image_path: Path) -> tuple[str, str]:
    """Returns (base64_data, normalized_extension) for embedding in a vision API call."""
    with open(image_path, "rb") as f:
        b64_image = base64.b64encode(f.read()).decode("utf-8")
    ext = image_path.suffix.lower().lstrip(".") or "jpeg"
    if ext == "jpg":
        ext = "jpeg"
    return b64_image, ext


def analyze_image_groq(image_path: Path, max_retries: int = 2, retry_delay_seconds: float = 0.8):
    """
    Executes the 7-step waste & material identification decision process
    using Groq's vision model. See VISION_ANALYSIS_PROMPT for the exact
    instructions (shared with the Gemini fallback in analyze_image_gemini,
    so both providers are held to the same output contract).

    Retries transient failures (e.g. connection errors) up to `max_retries`
    times with a short backoff before giving up. If every attempt fails,
    raises GroqAnalysisUnavailable instead of silently returning None, so
    callers can distinguish "temporarily unreachable" from "not configured".
    """
    if groq_client is None:
        print("Groq image analysis skipped: groq_client is None (GROQ_API_KEY missing or invalid).")
        return None

    try:
        b64_image, ext = _load_image_as_base64(image_path)
    except Exception as exc:  # noqa: BLE001 - reading/encoding the file failed, not a connection issue
        print("Groq image analysis failed (could not read image file):", exc)
        return None

    last_error = None
    for attempt in range(1, max_retries + 2):  # e.g. max_retries=2 -> attempts 1, 2, 3
        try:
            completion = groq_client.chat.completions.create(
                model=GROQ_VISION_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": VISION_ANALYSIS_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/{ext};base64,{b64_image}"},
                            },
                        ],
                    }
                ],
                temperature=0.1,
                max_completion_tokens=600,
                reasoning_effort="none",
                timeout=20,  # hard cap per attempt so a stalled call fails fast
                              # instead of hanging until gunicorn's worker timeout
                              # kills the whole request (which drops the
                              # connection and surfaces as a generic frontend
                              # "could not communicate with backend" error)
            )

            raw = (completion.choices[0].message.content or "").strip()
            print(f"Groq raw response (attempt {attempt}):", repr(raw))

            result = _parse_vision_analysis_json(raw)
            print("Groq parsed result:", result)
            return result
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"Groq image analysis attempt {attempt} failed:", exc)
            if attempt <= max_retries:
                time.sleep(retry_delay_seconds * attempt)  # simple linear backoff

    # Every attempt (including retries) failed — this is a transient
    # availability problem, not a "no API key configured" situation, so we
    # raise instead of quietly falling back to the CNN-only path.
    print("Groq image analysis failed after", max_retries + 1, "attempts:", last_error)
    raise GroqAnalysisUnavailable(str(last_error))


def analyze_image_gemini(image_path: Path, max_retries: int = 1, retry_delay_seconds: float = 0.6):
    """
    Same 7-step decision process as analyze_image_groq, but called against
    Gemini's REST API instead. This exists purely as a fallback for when
    Groq is unreachable/erroring — see analyze_image_multi_provider below
    for how the two are combined.

    Uses urllib.request (already used elsewhere in this file) rather than
    adding a new HTTP client dependency.
    """
    if not GEMINI_API_KEY:
        print("Gemini image analysis skipped: GEMINI_API_KEY not set.")
        return None

    try:
        b64_image, ext = _load_image_as_base64(image_path)
    except Exception as exc:  # noqa: BLE001
        print("Gemini image analysis failed (could not read image file):", exc)
        return None

    mime_type = f"image/{ext}"
    payload = json.dumps({
        "contents": [{
            "parts": [
                {"text": VISION_ANALYSIS_PROMPT},
                {"inline_data": {"mime_type": mime_type, "data": b64_image}},
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 600,
        },
    }).encode("utf-8")

    last_error = None
    for attempt in range(1, max_retries + 2):
        try:
            req = urllib.request.Request(
                f"{GEMINI_ENDPOINT}?key={GEMINI_API_KEY}",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            # Hard cap per attempt for the same reason as Groq's timeout=20
            # above: fail fast instead of risking gunicorn's worker timeout
            # killing the whole request.
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            raw = (
                body.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            ).strip()
            print(f"Gemini raw response (attempt {attempt}):", repr(raw))

            result = _parse_vision_analysis_json(raw)
            print("Gemini parsed result:", result)
            return result
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"Gemini image analysis attempt {attempt} failed:", exc)
            if attempt <= max_retries:
                time.sleep(retry_delay_seconds * attempt)

    print("Gemini image analysis failed after", max_retries + 1, "attempts:", last_error)
    raise GeminiAnalysisUnavailable(str(last_error))


def analyze_image_multi_provider(image_path: Path):
    """
    Provider fallback chain, in order: Groq -> Gemini -> Groq (one last
    retry), matching the requested behavior of "if one fails, try the
    other, and if that also fails, go back to the first one before giving
    up." Each individual attempt uses a small max_retries so the combined
    worst case still comfortably fits inside gunicorn's --timeout.

    Returns the same dict shape as analyze_image_groq / analyze_image_gemini,
    or None if neither provider is configured at all (falls back to
    CNN-only classification, same as the original single-provider
    behavior). Raises AllProvidersUnavailable only if both providers are
    configured but every attempt across both still failed.
    """
    if groq_client is None and not GEMINI_API_KEY:
        # Neither provider configured — this is an intentional degraded
        # deployment, not a runtime failure, so behave like the original
        # analyze_image_groq did when GROQ_API_KEY was unset.
        return None

    errors = []

    # 1) Groq first (primary provider).
    try:
        result = analyze_image_groq(image_path, max_retries=1, retry_delay_seconds=0.6)
        if result is not None:
            return result
    except GroqAnalysisUnavailable as exc:
        print("Provider fallback: Groq failed, trying Gemini next:", exc)
        errors.append(f"Groq: {exc}")

    # 2) Gemini fallback.
    try:
        result = analyze_image_gemini(image_path, max_retries=1, retry_delay_seconds=0.6)
        if result is not None:
            return result
    except GeminiAnalysisUnavailable as exc:
        print("Provider fallback: Gemini also failed, retrying Groq once more:", exc)
        errors.append(f"Gemini: {exc}")

    # 3) Back to Groq for one final attempt before giving up entirely.
    try:
        result = analyze_image_groq(image_path, max_retries=0, retry_delay_seconds=0)
        if result is not None:
            return result
    except GroqAnalysisUnavailable as exc:
        errors.append(f"Groq (final retry): {exc}")

    raise AllProvidersUnavailable(" | ".join(errors) if errors else "Unknown error")


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------
@app.route("/")
def home():
    if session.get("user_id"):
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("detect"))
    return render_template("home.html")


@app.route("/detect")
@login_required
def detect():
    return render_template("detect.html", model_error=model_load_error)


@app.route("/guide")
def guide():
    return render_template("guide.html", guidance=GUIDANCE)


@app.route("/about")
def about():
    return render_template("about.html")


# ---------------------------------------------------------------------------
# User & Admin Authentication Routes (Unified Portal)
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("detect"))

    if request.method == "POST":
        login_identifier = request.form.get("login_identifier", "").strip()
        password = request.form.get("password", "")

        # Rate-limit by client IP + attempted identifier to slow down
        # brute-force / credential-stuffing attempts against any account.
        rate_key = f"{request.remote_addr}:{login_identifier.lower()}"
        if _login_rate_limited(rate_key):
            flash("Too many failed sign-in attempts. Please wait a few minutes and try again.", "error")
            return render_template("auth/login.html"), 429

        user, err = authenticate_user(login_identifier, password, require_admin=False)
        if err:
            _record_login_attempt(rate_key)
            flash(err, "error")
            return render_template("auth/login.html")

        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        session["is_admin"] = (user["role"] == "admin")

        if user["role"] == "admin":
            return redirect(url_for("admin_dashboard"))

        flash(f"Welcome back, {user['username']}!", "success")
        return redirect(url_for("detect"))

    return render_template("auth/login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("detect"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if len(username) < 3:
            flash("Username must be at least 3 characters.", "error")
            return render_template("auth/register.html")

        if (
            len(password) < 8
            or not any(c.isalpha() for c in password)
            or not any(c.isdigit() for c in password)
        ):
            flash("Password must be at least 8 characters and include both letters and numbers.", "error")
            return render_template("auth/register.html")

        user_id, err = create_user(username, email, password, role="user")
        if err:
            flash(err, "error")
            return render_template("auth/register.html")

        session.clear()
        session["user_id"] = user_id
        session["username"] = username
        session["role"] = "user"
        session["is_admin"] = False

        flash("Account created successfully! Welcome to EcoCycle AI.", "success")
        return redirect(url_for("detect"))

    return render_template("auth/register.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out successfully.", "success")
    return redirect(url_for("home"))


@app.route("/admin/login")
def admin_login():
    """Redirects legacy /admin/login to unified /login page."""
    return redirect(url_for("login"))


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    flash("Administrator logged out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    admin_user = get_user_by_id(session.get("user_id"))
    stats = get_admin_dashboard_stats()
    disposal_stats = get_disposal_requests_stats()
    
    search_query = request.args.get("search", "").strip()
    category_filter = request.args.get("category", "all")
    waste_filter = request.args.get("waste_status", "all")

    classifications = get_classifications(
        search=search_query,
        category_filter=category_filter,
        waste_filter=waste_filter,
        limit=1000
    )
    users = get_all_users(limit=1000)
    recent_disposal_requests = get_all_disposal_requests(limit=10)
    requests_list = get_all_disposal_requests(limit=1000)
    locations_list = get_all_disposal_locations()

    collection_stats = get_collection_requests_stats()
    collection_requests_list = get_all_collection_requests(limit=1000)
    collection_schedules_list = get_all_collection_schedules()

    return render_template(
        "admin/dashboard.html",
        admin_user=admin_user,
        stats=stats,
        disposal_stats=disposal_stats,
        classifications=classifications,
        users=users,
        recent_disposal_requests=recent_disposal_requests,
        requests_list=requests_list,
        locations_list=locations_list,
        search_query=search_query,
        category_filter=category_filter,
        waste_filter=waste_filter,
        collection_stats=collection_stats,
        collection_requests_list=collection_requests_list,
        collection_schedules_list=collection_schedules_list,
        weekdays=WEEKDAYS,
    )


@app.route("/admin/classification/<int:record_id>/delete", methods=["POST"])
@admin_required
def admin_delete_classification(record_id: int):
    success = delete_classification_record(record_id)
    if success:
        flash(f"Classification record #{record_id} deleted successfully.", "success")
    else:
        flash(f"Classification record #{record_id} could not be found.", "error")
    return redirect(url_for("admin_dashboard") + "#records")


# ---------------------------------------------------------------------------
# Disposal Locations & Requests Portal (User & Admin Routes)
# ---------------------------------------------------------------------------

@app.route("/requests")
@login_required
def user_requests():
    """User-facing page to review their disposal requests history and track assigned locations."""
    user_id = session.get("user_id")
    user_name = session.get("username")

    # Ensure user's active requests are matched to their latest updated location
    saved_location = get_user_location(user_id)
    if saved_location and saved_location.get("lat") and saved_location.get("lng"):
        reassign_user_disposal_requests_to_location(
            user_id=user_id,
            lat=float(saved_location["lat"]),
            lng=float(saved_location["lng"]),
            location_text=f"{saved_location.get('area')}" + (f" ({saved_location.get('pincode')})" if saved_location.get('pincode') else "")
        )

    requests_list = get_user_disposal_requests(user_id=user_id, user_name=user_name, limit=50)

    # Match each scanned item back to its specific disposal request by classification_id.
    # Scanned items start completely clean with "Disposal Location" button active until
    # a request is filed specifically for that scan instance.
    request_state_by_scan_id = {}
    for item in requests_list:
        c_id = item.get("classification_id")
        if c_id and c_id not in request_state_by_scan_id:
            request_state_by_scan_id[c_id] = item

    # Waste collection (pickup) request history linked by classification_id
    collection_requests_list = get_user_collection_requests(user_id=user_id, user_name=user_name, limit=200)
    collection_state_by_scan_id = {}
    for c_item in collection_requests_list:
        c_id = c_item.get("classification_id")
        if c_id and c_id not in collection_state_by_scan_id:
            collection_state_by_scan_id[c_id] = c_item

    # The user's own scan history (with images)
    my_classifications = get_classifications(user_id_filter=user_id, limit=50)

    return render_template(
        "requests.html",
        requests_list=requests_list,
        my_classifications=my_classifications,
        request_state_by_scan_id=request_state_by_scan_id,
        collection_state_by_scan_id=collection_state_by_scan_id,
    )


@app.route("/requests/<int:request_id>")
@app.route("/request/<int:request_id>")
@login_required
def request_detail(request_id: int):
    """Dedicated single page view for a disposal request with map, facility details, and directions."""
    user_id = session.get("user_id")
    is_admin = session.get("is_admin", False)
    req = get_disposal_request_by_id(request_id)
    if not req:
        flash("Disposal request not found.", "error")
        return redirect(url_for("user_requests"))

    if not is_admin and req.get("user_id") != user_id:
        flash("You do not have permission to view this disposal request.", "error")
        return redirect(url_for("user_requests"))

    return render_template("request_detail.html", req=req)


@app.route("/api/disposal/request/<int:request_id>/delete", methods=["POST"])
@login_required
def user_delete_disposal_request(request_id: int):
    """Lets a user delete their own disposal request (e.g. after removing
    the scanned item it was for). Admins may delete any request; a regular
    user may only delete their own."""
    user_id = session.get("user_id")
    is_admin = session.get("is_admin", False)

    req = get_disposal_request_by_id(request_id)
    if not req:
        return jsonify({"error": "Disposal request not found."}), 404

    if not is_admin and req.get("user_id") != user_id:
        return jsonify({"error": "You do not have permission to delete this request."}), 403

    success = delete_disposal_request(request_id)
    if success:
        return jsonify({"status": "ok", "message": f"Disposal request #{request_id} deleted."})
    return jsonify({"error": "Could not delete this request."}), 500


@app.route("/collection-requests")
@login_required
def user_collection_requests():
    """User-facing "Collection Availability" page. Displays the collector
    availability configured by the admin for the user's saved Area and PIN Code."""
    user_id = session.get("user_id")
    location = get_user_location(user_id)

    schedule = None
    next_date = None
    next_date_display = None
    time_range_display = None

    if location and location.get("area"):
        schedule = find_matching_schedule_for_area(location["area"], location.get("pincode"))
        if schedule:
            next_date = next_occurrence_date(schedule["day_of_week"], schedule["time_start"])
            next_date_display = _format_date_display(next_date)
            time_range_display = f"{_format_time_12h(schedule['time_start'])} – {_format_time_12h(schedule['time_end'])}"

    return render_template(
        "collection_requests.html",
        location=location,
        schedule=schedule,
        next_date=next_date,
        next_date_display=next_date_display,
        time_range_display=time_range_display,
    )


# --- User Profile: Saved Location (Collection Availability & Geocoding) ---

@app.route("/api/user/location", methods=["GET"])
@login_required
def api_get_user_location():
    """Returns the logged-in user's saved pickup location, if any."""
    user_id = session.get("user_id")
    location = get_user_location(user_id)
    return jsonify({"status": "ok", "saved": bool(location), "location": location})


@app.route("/api/geocode", methods=["GET", "POST"])
@login_required
def api_geocode():
    """Geocodes an Area + PIN Code + Address combination without saving."""
    if request.is_json:
        payload = request.get_json() or {}
    else:
        payload = request.args.to_dict() if request.method == "GET" else request.form.to_dict()

    area = (payload.get("area") or "").strip()
    pincode = (payload.get("pincode") or "").strip()
    address = (payload.get("address") or "").strip()

    if not area and not pincode:
        return jsonify({"status": "error", "error": "Please provide an Area or PIN Code."}), 400

    geocoded = geocode_location(area, pincode, address)
    if not geocoded:
        return jsonify({
            "status": "error",
            "error": f"Could not identify location for '{area}, {pincode}'. Please verify your spelling."
        }), 404

    lat, lng, display_name = geocoded
    return jsonify({
        "status": "ok",
        "lat": lat,
        "lng": lng,
        "display_name": display_name,
    })


@app.route("/api/reverse-geocode", methods=["GET", "POST"])
@login_required
def api_reverse_geocode():
    """Reverse geocodes Latitude and Longitude into Area, PIN Code, and Address."""
    if request.is_json:
        payload = request.get_json() or {}
    else:
        payload = request.args.to_dict() if request.method == "GET" else request.form.to_dict()

    try:
        lat = float(payload.get("lat"))
        lng = float(payload.get("lng"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "error": "Invalid latitude or longitude coordinates."}), 400

    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return jsonify({"status": "error", "error": "Coordinates are out of bounds."}), 400

    result = reverse_geocode_location(lat, lng)
    if not result:
        return jsonify({
            "status": "error",
            "error": "Could not identify address for these coordinates. Please enter your location manually."
        }), 404

    return jsonify({"status": "ok", **result})


@app.route("/api/user/location", methods=["POST"])
@login_required
def api_save_user_location():
    """Saves the user's location (Area + PIN Code + Address + Lat + Lng) to
    their profile.
    - For mobile users (with GPS coordinates): validates lat/lng and saves area/pincode/address.
    - For desktop/laptop users (with manual area + pincode + address): forward-geocodes to lat/lng.
    Matches with collector schedule and returns availability details."""
    payload = request.get_json() if request.is_json else request.form.to_dict()
    payload = payload or {}

    area = (payload.get("area") or "").strip()
    pincode = (payload.get("pincode") or "").strip()
    address = (payload.get("address") or "").strip()

    lat = payload.get("lat")
    lng = payload.get("lng")
    lat_val = None
    lng_val = None

    if lat is not None and lng is not None and str(lat).strip() != "" and str(lng).strip() != "":
        try:
            lat_f = float(lat)
            lng_f = float(lng)
            if -90 <= lat_f <= 90 and -180 <= lng_f <= 180 and not (lat_f == 0.0 and lng_f == 0.0):
                lat_val = lat_f
                lng_val = lng_f
        except (ValueError, TypeError):
            pass

    # Perform geocoding to identify and convert location to lat/lng if not provided
    if lat_val is None or lng_val is None:
        if not area and not pincode:
            return jsonify({"error": "Please enter your Area / Locality and PIN Code."}), 400
        geocoded = geocode_location(area, pincode, address)
        if geocoded:
            lat_val, lng_val, _ = geocoded
        else:
            # Regional fallback coordinates if geocoding fails or network unreachable
            lat_val = 15.3647
            lng_val = 75.1240

    if not area:
        return jsonify({"error": "Please provide your Area / Locality name."}), 400

    user_id = session.get("user_id")
    save_user_location(user_id, area, pincode, address, lat_val, lng_val)
    reassign_user_disposal_requests_to_location(
        user_id=user_id,
        lat=lat_val,
        lng=lng_val,
        location_text=f"{area}" + (f" ({pincode})" if pincode else "")
    )

    # Immediately check collector availability for this user's location
    schedule = find_matching_schedule_for_area(area, pincode)
    schedule_data = None
    if schedule:
        next_date = next_occurrence_date(schedule["day_of_week"], schedule["time_start"])
        schedule_data = {
            "id": schedule["id"],
            "area": schedule["area"],
            "pincode": schedule.get("pincode") or "",
            "collector_name": schedule.get("collector_name") or "EcoCycle Municipal Collector",
            "day_of_week": schedule["day_of_week"],
            "time_start": schedule["time_start"],
            "time_end": schedule["time_end"],
            "time_range_display": f"{_format_time_12h(schedule['time_start'])} – {_format_time_12h(schedule['time_end'])}",
            "next_date": next_date,
            "next_date_display": _format_date_display(next_date),
            "available": True,
        }

    availability_msg = (
        f"Collection is available in {area} every {schedule['day_of_week']} ({schedule_data['time_range_display']})."
        if schedule_data
        else "Collection service is currently not available in your area."
    )

    return jsonify({
        "status": "ok",
        "message": "Your location has been saved successfully.",
        "location": {"area": area, "pincode": pincode, "address": address, "lat": lat_val, "lng": lng_val},
        "available": bool(schedule_data),
        "schedule": schedule_data,
        "availability_message": availability_msg,
    })


@app.route("/api/collection/request", methods=["POST"])
@login_required
def create_user_collection_request():
    """Creates a new waste collection (pickup) request using the user's saved location
    and auto-assigning the schedule derived from the admin's collection availability."""
    if request.is_json:
        payload = request.get_json() or {}
    else:
        payload = request.form.to_dict()

    user_id = session.get("user_id")
    user_name = session.get("username", "Eco Member")
    saved_location = get_user_location(user_id)

    waste_type = (payload.get("waste_type") or "").strip() or "General Waste"
    quantity = (payload.get("quantity") or "").strip() or "1 item"
    address = (payload.get("address") or "").strip() or (saved_location.get("address") if saved_location else "")
    note = (payload.get("note") or "").strip()
    area = (payload.get("area") or "").strip() or (saved_location.get("area") if saved_location else "")
    pincode = (payload.get("pincode") or "").strip() or (saved_location.get("pincode") if saved_location else "")

    pickup_lat = 0.0
    pickup_lng = 0.0

    try:
        pickup_lat = float(payload.get("pickup_lat", 0.0))
        pickup_lng = float(payload.get("pickup_lng", 0.0))
    except (ValueError, TypeError):
        pass

    if (pickup_lat == 0.0 and pickup_lng == 0.0) and saved_location:
        pickup_lat = float(saved_location.get("lat") or 0.0)
        pickup_lng = float(saved_location.get("lng") or 0.0)

    if not area:
        return jsonify({
            "error": "Please set your pickup location (Area & PIN Code) in your profile first.",
            "location_required": True
        }), 400

    schedule = find_matching_schedule_for_area(area, pincode)
    if not schedule:
        return jsonify({
            "error": "Collection service is currently not available in your area.",
            "area_unavailable": True,
            "area": area,
            "pincode": pincode,
        }), 400

    scheduled_day = schedule["day_of_week"]
    scheduled_time_start = schedule["time_start"]
    scheduled_time_end = schedule["time_end"]
    scheduled_date = next_occurrence_date(scheduled_day, scheduled_time_start)

    pickup_location_text = f"{area}" + (f" ({pincode})" if pincode else "") + (f", {address}" if address else "")

    classification_id = payload.get("classification_id")
    if classification_id is not None:
        try:
            classification_id = int(classification_id)
        except (ValueError, TypeError):
            classification_id = None

    try:
        request_id = create_collection_request(
            user_name=user_name,
            waste_type=waste_type,
            quantity=quantity,
            pickup_lat=pickup_lat,
            pickup_lng=pickup_lng,
            pickup_location_text=pickup_location_text,
            address=address,
            note=note,
            user_id=user_id,
            area=area,
            scheduled_day=scheduled_day,
            scheduled_date=scheduled_date,
            scheduled_time_start=scheduled_time_start,
            scheduled_time_end=scheduled_time_end,
            classification_id=classification_id,
        )
        saved_req = get_collection_request_by_id(request_id)
        return jsonify({
            "status": "ok",
            "message": "Collection request submitted successfully. Our team will review it shortly.",
            "request": saved_req
        }), 201
    except Exception as exc:  # noqa: BLE001
        print("Collection request creation error:", exc)
        return jsonify({"error": "Could not create collection request."}), 500


@app.route("/api/collection/my-requests", methods=["GET"])
@login_required
def api_my_collection_requests():
    """Returns the logged-in user's collection request history as JSON."""
    user_id = session.get("user_id")
    user_name = session.get("username")
    requests_list = get_user_collection_requests(user_id=user_id, user_name=user_name, limit=50)
    return jsonify({"status": "ok", "requests": requests_list})


# --- Admin Waste Collection Management Routes ---

@app.route("/api/admin/collection-requests/<int:request_id>/accept", methods=["POST"])
@admin_required
def admin_accept_collection_request(request_id: int):
    """Admin accepts a pending pickup request."""
    success = update_collection_request_status(request_id, "Accepted")
    if success:
        flash(f"Collection request #{request_id} accepted.", "success")
    else:
        flash(f"Collection request #{request_id} could not be found.", "error")
    return redirect(url_for("admin_dashboard") + "#collection")


@app.route("/api/admin/collection-requests/<int:request_id>/reject", methods=["POST"])
@admin_required
def admin_reject_collection_request(request_id: int):
    """Admin rejects a pending pickup request."""
    success = update_collection_request_status(request_id, "Rejected")
    if success:
        flash(f"Collection request #{request_id} rejected.", "success")
    else:
        flash(f"Collection request #{request_id} could not be found.", "error")
    return redirect(url_for("admin_dashboard") + "#collection")


@app.route("/api/admin/collection-requests/<int:request_id>/collected", methods=["POST"])
@admin_required
def admin_collected_collection_request(request_id: int):
    """Admin marks an accepted pickup request as collected once picked up."""
    success = update_collection_request_status(request_id, "Collected")
    if success:
        flash(f"Collection request #{request_id} marked as collected.", "success")
    else:
        flash(f"Collection request #{request_id} could not be found.", "error")
    return redirect(url_for("admin_dashboard") + "#collection")


@app.route("/api/admin/collection-requests/<int:request_id>/delete", methods=["POST"])
@admin_required
def admin_delete_collection_request(request_id: int):
    """Deletes a collection request."""
    success = delete_collection_request(request_id)
    if success:
        flash(f"Collection request #{request_id} deleted.", "success")
    else:
        flash(f"Collection request #{request_id} could not be found.", "error")
    return redirect(url_for("admin_dashboard") + "#collection")


# --- Admin: Area-Based Waste Collection Schedule Management ---

@app.route("/admin/collection-schedule/add", methods=["POST"])
@admin_required
def admin_add_collection_schedule():
    """Adds a new area -> pickup day/time schedule row with PIN Code and Collector Name."""
    area = (request.form.get("area") or "").strip()
    pincode = (request.form.get("pincode") or "").strip()
    collector_name = (request.form.get("collector_name") or "EcoCycle Municipal Collector").strip()
    day_of_week = (request.form.get("day_of_week") or "").strip().title()
    time_start = (request.form.get("time_start") or "").strip()
    time_end = (request.form.get("time_end") or "").strip()
    active = request.form.get("active") == "on"

    if not area or day_of_week not in WEEKDAYS or not time_start or not time_end:
        flash("Please provide an area, a valid day, and both start/end times.", "error")
        return redirect(url_for("admin_dashboard") + "#collection")

    create_collection_schedule(
        area=area,
        day_of_week=day_of_week,
        time_start=time_start,
        time_end=time_end,
        pincode=pincode,
        collector_name=collector_name,
        active=active,
    )
    flash(f"Collection schedule added for {area}" + (f" ({pincode})" if pincode else "") + ".", "success")
    return redirect(url_for("admin_dashboard") + "#collection")


@app.route("/api/admin/collection-schedule/<int:schedule_id>", methods=["GET"])
@admin_required
def api_get_collection_schedule(schedule_id: int):
    """Returns a single schedule row as JSON, used to pre-fill the Edit modal."""
    schedule = get_collection_schedule_by_id(schedule_id)
    if not schedule:
        return jsonify({"error": "Schedule not found."}), 404
    return jsonify({"status": "ok", "schedule": schedule})


@app.route("/admin/collection-schedule/<int:schedule_id>/update", methods=["POST"])
@admin_required
def admin_update_collection_schedule(schedule_id: int):
    """Edits an existing area schedule row with PIN Code and Collector Name."""
    area = (request.form.get("area") or "").strip()
    pincode = (request.form.get("pincode") or "").strip()
    collector_name = (request.form.get("collector_name") or "EcoCycle Municipal Collector").strip()
    day_of_week = (request.form.get("day_of_week") or "").strip().title()
    time_start = (request.form.get("time_start") or "").strip()
    time_end = (request.form.get("time_end") or "").strip()
    active = request.form.get("active") == "on"

    if not area or day_of_week not in WEEKDAYS or not time_start or not time_end:
        flash("Please provide an area, a valid day, and both start/end times.", "error")
        return redirect(url_for("admin_dashboard") + "#collection")

    success = update_collection_schedule(
        schedule_id=schedule_id,
        area=area,
        day_of_week=day_of_week,
        time_start=time_start,
        time_end=time_end,
        pincode=pincode,
        collector_name=collector_name,
        active=active,
    )
    if success:
        flash(f"Collection schedule for {area} updated.", "success")
    else:
        flash("Schedule not found.", "error")
    return redirect(url_for("admin_dashboard") + "#collection")


@app.route("/admin/collection-schedule/<int:schedule_id>/toggle", methods=["POST"])
@admin_required
def admin_toggle_collection_schedule(schedule_id: int):
    """Enables/disables a schedule row without deleting it."""
    success = toggle_collection_schedule(schedule_id)
    if success:
        flash("Schedule status updated.", "success")
    else:
        flash("Schedule not found.", "error")
    return redirect(url_for("admin_dashboard") + "#collection")


@app.route("/admin/collection-schedule/<int:schedule_id>/delete", methods=["POST"])
@admin_required
def admin_delete_collection_schedule(schedule_id: int):
    """Deletes a collection schedule row."""
    success = delete_collection_schedule(schedule_id)
    if success:
        flash("Collection schedule deleted.", "success")
    else:
        flash("Schedule not found.", "error")
    return redirect(url_for("admin_dashboard") + "#collection")


# --- User-facing: Area / PIN code -> Collection Schedule lookup ---

@app.route("/api/collection/schedule-lookup", methods=["GET"])
@login_required
def api_collection_schedule_lookup():
    """Given an area and/or PIN code, checks whether the admin has an
    active pickup schedule / collector available for that location."""
    area = (request.args.get("area") or "").strip()
    pincode = (request.args.get("pincode") or "").strip()

    if not area and not pincode:
        user_id = session.get("user_id")
        saved = get_user_location(user_id)
        if saved:
            area = saved.get("area", "")
            pincode = saved.get("pincode", "")

    if not area and not pincode:
        return jsonify({"status": "error", "error": "Missing area or pincode."}), 400

    schedule = find_matching_schedule_for_area(area, pincode)
    if not schedule:
        return jsonify({
            "status": "ok",
            "area": area,
            "pincode": pincode,
            "available": False,
            "message": "Collection service is currently not available in your area."
        })

    next_date = next_occurrence_date(schedule["day_of_week"], schedule["time_start"])
    return jsonify({
        "status": "ok",
        "area": schedule["area"],
        "pincode": schedule.get("pincode") or "",
        "collector_name": schedule.get("collector_name") or "EcoCycle Municipal Collector",
        "available": True,
        "schedule": {
            "id": schedule["id"],
            "area": schedule["area"],
            "pincode": schedule.get("pincode") or "",
            "collector_name": schedule.get("collector_name") or "EcoCycle Municipal Collector",
            "day_of_week": schedule["day_of_week"],
            "time_start": schedule["time_start"],
            "time_end": schedule["time_end"],
            "time_range_display": f"{_format_time_12h(schedule['time_start'])} – {_format_time_12h(schedule['time_end'])}",
            "next_date": next_date,
            "next_date_display": _format_date_display(next_date),
        },
        "next_date": next_date,
    })


@app.route("/api/classification/<int:record_id>/delete", methods=["POST"])
@login_required
def delete_user_classification(record_id: int):
    """Deletes one scan only when it belongs to the logged-in user."""
    if delete_classification_for_user(record_id, session.get("user_id")):
        return jsonify({"status": "ok", "message": "Scanned item deleted."})
    return jsonify({"error": "Scanned item not found."}), 404


@app.route("/api/notifications", methods=["GET"])
@login_required
def api_user_notifications():
    """Returns recent notifications and the unread count for the user bell."""
    notifications = get_user_notifications(session.get("user_id"), limit=20)
    return jsonify({
        "status": "ok",
        "notifications": notifications,
        "unread_count": sum(1 for item in notifications if not item["is_read"]),
    })


@app.route("/api/notifications/mark-read", methods=["POST"])
@login_required
def api_mark_user_notifications_read():
    """Marks the user's notifications as read; IDs are optional."""
    payload = request.get_json(silent=True) or {}
    notification_ids = payload.get("notification_ids")
    if notification_ids is not None and not isinstance(notification_ids, list):
        return jsonify({"error": "notification_ids must be a list."}), 400
    mark_user_notifications_read(session.get("user_id"), notification_ids)
    return jsonify({"status": "ok"})


@app.route("/api/notifications/clear", methods=["POST"])
@login_required
def api_clear_user_notifications():
    """Hard-deletes all notifications for the current user."""
    delete_user_notifications(session.get("user_id"))
    return jsonify({"status": "ok"})


@app.route("/api/disposal/request", methods=["POST"])
@login_required
def create_user_disposal_request():
    """Creates a disposal request capturing the user's name, object, category,
    and using their saved location details without GPS geolocation."""
    if request.is_json:
        payload = request.get_json() or {}
    else:
        payload = request.form.to_dict()

    user_id = session.get("user_id")
    user_name = session.get("username", "Eco Member")
    saved_location = get_user_location(user_id)

    object_name = payload.get("object_name", "").strip() or "Waste Specimen"
    category = payload.get("category", "").strip() or "General Waste"
    user_location_text = payload.get("user_location_text", "").strip()
    image_url = (payload.get("image_url") or "").strip() or None
    classification_id = payload.get("classification_id")
    if classification_id is not None:
        try:
            classification_id = int(classification_id)
        except (ValueError, TypeError):
            classification_id = None

    user_lat = 0.0
    user_lng = 0.0

    # Prioritize user's saved profile location if set
    if saved_location and saved_location.get("lat") and saved_location.get("lng"):
        user_lat = float(saved_location.get("lat") or 0.0)
        user_lng = float(saved_location.get("lng") or 0.0)
        if not user_location_text:
            user_location_text = f"{saved_location.get('area')}" + (f" ({saved_location.get('pincode')})" if saved_location.get('pincode') else "")

    # Fallback to payload coordinates if profile location is missing
    if user_lat == 0.0 and user_lng == 0.0:
        try:
            user_lat = float(payload.get("user_lat", payload.get("latitude", 0.0)))
            user_lng = float(payload.get("user_lng", payload.get("longitude", 0.0)))
        except (ValueError, TypeError):
            pass

    if user_lat == 0.0 and user_lng == 0.0:
        return jsonify({
            "error": "Please set your location (Area & PIN Code) in your profile first to find the nearest disposal center.",
            "location_required": True
        }), 400

    try:
        nearby = get_nearby_disposal_locations(user_lat=user_lat, user_lng=user_lng, category=category)
        best = nearby[0] if nearby else None
        assigned_location_id = best["id"] if best else None
        admin_notes = (
            f"Auto-assigned to the nearest {'matching' if best.get('is_category_match') else 'available'} "
            f"center: {best['name']} (~{best['distance_km']} km away)."
        ) if best else "No disposal centers are on file yet."

        # If a disposal request already exists for this scan classification, update it with latest coordinates
        existing_req = None
        if classification_id and user_id:
            existing_req = get_disposal_request_by_classification_id(classification_id, user_id=user_id)

        if existing_req:
            request_id = existing_req["id"]
            update_disposal_request_location_and_center(
                request_id=request_id,
                user_lat=user_lat,
                user_lng=user_lng,
                user_location_text=user_location_text or f"Location: {user_lat:.4f}, {user_lng:.4f}",
                assigned_location_id=assigned_location_id,
                admin_notes=admin_notes
            )
        else:
            request_id = create_disposal_request(
                user_name=user_name,
                object_name=object_name,
                category=category,
                user_lat=user_lat,
                user_lng=user_lng,
                user_location_text=user_location_text or f"Location: {user_lat:.4f}, {user_lng:.4f}",
                user_id=user_id,
                image_url=image_url,
                classification_id=classification_id,
            )
            if best:
                update_disposal_request_status(
                    request_id=request_id,
                    status="Location Assigned",
                    assigned_location_id=assigned_location_id,
                    admin_notes=admin_notes
                )

        if best:
            response_message = f"Nearest disposal center found automatically: {best['name']} (~{best['distance_km']} km away)."
        else:
            response_message = (
                "Disposal request saved, but no disposal centers are on file yet, "
                "so a location couldn't be auto-assigned. Please contact support "
                "or check back soon — an admin needs to add at least one disposal "
                "center before auto-assignment can work."
            )
            print(f"WARNING: disposal_locations table is empty — request #{request_id} could not be auto-assigned.")

        saved_req = get_disposal_request_by_id(request_id)

        if best and saved_req and saved_req.get("user_id"):
            create_user_notification(
                saved_req["user_id"],
                request_id,
                f"Disposal location auto-assigned for {saved_req['object_name']}: {saved_req.get('location_name', '')}",
            )

        return jsonify({
            "status": "ok",
            "message": response_message,
            "request": saved_req,
            "nearby_locations": nearby[:4]
        }), 201
    except Exception as exc:  # noqa: BLE001
        print("Disposal request creation error:", exc)
        return jsonify({"error": "Could not create disposal request."}), 500


@app.route("/api/disposal/request/<int:request_id>/nearby", methods=["GET"])
@login_required
def api_disposal_request_nearby(request_id: int):
    """Returns up to 4 nearest disposal facilities for a request's GPS location.

    Available to the request's owner (or an admin) so the user-facing pages
    can show a few alternative nearby options in addition to the one the
    system auto-selected.
    """
    req = get_disposal_request_by_id(request_id)
    if not req:
        return jsonify({"error": "Request not found."}), 404

    user_id = session.get("user_id")
    is_admin = session.get("is_admin", False)
    if not is_admin and req.get("user_id") != user_id:
        return jsonify({"error": "You do not have permission to view this request."}), 403

    nearby = get_nearby_disposal_locations(
        user_lat=req["user_lat"],
        user_lng=req["user_lng"],
        category=req["category"]
    )
    return jsonify({
        "status": "ok",
        "nearby_locations": nearby[:4]
    })


@app.route("/api/disposal/my-requests", methods=["GET"])
@login_required
def api_my_disposal_requests():
    """Returns the logged-in user's request history as JSON."""
    user_id = session.get("user_id")
    user_name = session.get("username")
    requests_list = get_user_disposal_requests(user_id=user_id, user_name=user_name, limit=50)
    return jsonify({"status": "ok", "requests": requests_list})


@app.route("/api/disposal/request/<int:request_id>/complete", methods=["POST"])
@login_required
def complete_disposal_request(request_id: int):
    """Allows user or admin to mark a request as completed."""
    req = get_disposal_request_by_id(request_id)
    if not req:
        return jsonify({"error": "Request not found."}), 404

    user_id = session.get("user_id")
    is_admin = session.get("is_admin", False)
    if not is_admin and req.get("user_id") != user_id:
        return jsonify({"error": "Unauthorized."}), 403

    success = update_disposal_request_status(request_id, "Completed")
    if success:
        return jsonify({"status": "ok", "message": "Disposal request marked as completed."})
    return jsonify({"error": "Failed to update status."}), 400


# --- Admin Disposal Management Routes ---

@app.route("/admin/locations")
@admin_required
def admin_locations():
    """Redirects to unified admin console with disposal view active."""
    return redirect(url_for("admin_dashboard") + "#disposal")


@app.route("/api/admin/notifications/pending-count", methods=["GET"])
@admin_required
def api_admin_pending_notifications():
    """
    Lightweight, frequently-polled endpoint for the admin topbar bell and
    sidebar 'Requests' badge. Returns only a count (not full request
    payloads) so polling every ~25s stays cheap.
    """
    stats = get_disposal_requests_stats()
    return jsonify({"pending_count": stats.get("pending", 0)})


@app.route("/api/admin/disposal-requests/<int:request_id>", methods=["GET"])
@admin_required
def api_admin_get_disposal_request(request_id: int):
    """Fetches details of a request and returns matching disposal centers ranked by proximity."""
    req = get_disposal_request_by_id(request_id)
    if not req:
        return jsonify({"error": "Request not found."}), 404

    nearby_locations = get_nearby_disposal_locations(
        user_lat=req["user_lat"],
        user_lng=req["user_lng"],
        category=req["category"]
    )
    return jsonify({
        "status": "ok",
        "request": req,
        "nearby_locations": nearby_locations
    })


@app.route("/api/admin/disposal-requests/<int:request_id>/assign", methods=["POST"])
@admin_required
def api_admin_assign_location(request_id: int):
    """Admin assigns a selected disposal facility to the user's request and sets status to 'Location Assigned'."""
    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form.to_dict()

    location_id = data.get("location_id")
    admin_notes = data.get("admin_notes", "").strip()
    new_status = data.get("status", "Location Assigned")

    if not location_id:
        return jsonify({"error": "Please select a disposal center to assign."}), 400

    try:
        location_id = int(location_id)
    except ValueError:
        return jsonify({"error": "Invalid location ID."}), 400

    loc = get_disposal_location_by_id(location_id)
    if not loc:
        return jsonify({"error": "Selected disposal center does not exist."}), 404

    success = update_disposal_request_status(
        request_id=request_id,
        status=new_status,
        assigned_location_id=location_id,
        admin_notes=admin_notes or f"Assigned to {loc['name']}. Recommended drop-off during operating hours."
    )

    if success:
        updated_req = get_disposal_request_by_id(request_id)
        if updated_req and updated_req.get("user_id"):
            create_user_notification(
                updated_req["user_id"],
                request_id,
                f"Disposal location sent for {updated_req['object_name']}: {loc['name']}",
            )
        return jsonify({
            "status": "ok",
            "message": f"Successfully assigned '{loc['name']}' to request #{request_id}.",
            "request": updated_req
        })
    return jsonify({"error": "Failed to update disposal request."}), 500


@app.route("/api/admin/disposal-requests/<int:request_id>/verify", methods=["POST"])
@admin_required
def api_admin_verify_request(request_id: int):
    """Admin confirms/verifies a request after inspecting the image, GPS
    location, and the system's auto-selected disposal facility. This does
    not change the assignment — the system already picked the nearest
    matching facility when the request was created."""
    req = get_disposal_request_by_id(request_id)
    if not req:
        return jsonify({"error": "Request not found."}), 404

    success = verify_disposal_request(request_id)
    if success:
        updated_req = get_disposal_request_by_id(request_id)
        return jsonify({
            "status": "ok",
            "message": f"Request #{request_id} verified.",
            "request": updated_req
        })
    return jsonify({"error": "Failed to verify request."}), 500


@app.route("/api/admin/disposal-requests/<int:request_id>/status", methods=["POST"])
@admin_required
def api_admin_update_status(request_id: int):
    """Admin updates request status directly (e.g. Reviewed, Completed)."""
    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form.to_dict()

    new_status = data.get("status")
    admin_notes = data.get("admin_notes")

    if new_status not in {"Pending", "Reviewed", "Location Assigned", "Completed"}:
        return jsonify({"error": "Invalid status."}), 400

    success = update_disposal_request_status(
        request_id=request_id,
        status=new_status,
        admin_notes=admin_notes
    )

    if success:
        return jsonify({"status": "ok", "message": f"Status updated to '{new_status}'."})
    return jsonify({"error": "Failed to update status."}), 500


@app.route("/api/admin/disposal-requests/<int:request_id>/delete", methods=["POST"])
@admin_required
def admin_delete_request(request_id: int):
    """Deletes a disposal request."""
    success = delete_disposal_request(request_id)
    if request.is_json:
        if success:
            return jsonify({"status": "ok", "message": "Request deleted."})
        return jsonify({"error": "Request not found."}), 404
    
    if success:
        flash(f"Disposal request #{request_id} deleted successfully.", "success")
    else:
        flash(f"Disposal request #{request_id} could not be found.", "error")
    return redirect(url_for("admin_dashboard") + "#requests")


@app.route("/api/admin/disposal-locations/add", methods=["POST"])
@admin_required
def admin_add_location():
    """Adds a new verified disposal center."""
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "Universal").strip()
    address = request.form.get("address", "").strip()
    city = request.form.get("city", "Metro Area").strip()
    phone = request.form.get("phone", "").strip()
    operating_hours = request.form.get("operating_hours", "").strip()
    
    try:
        lat = float(request.form.get("latitude", 0.0))
        lng = float(request.form.get("longitude", 0.0))
    except ValueError:
        flash("Invalid latitude or longitude format.", "error")
        return redirect(url_for("admin_locations"))

    if not name or not address:
        flash("Facility name and address are required.", "error")
        return redirect(url_for("admin_locations"))

    loc_id = add_disposal_location(
        name=name,
        category=category,
        address=address,
        latitude=lat,
        longitude=lng,
        phone=phone,
        operating_hours=operating_hours,
        city=city
    )

    if loc_id:
        flash(f"Disposal center '{name}' added successfully.", "success")
    else:
        flash("Failed to add disposal center.", "error")
    return redirect(url_for("admin_locations"))


@app.route("/admin/disposal-locations/<int:loc_id>/edit", methods=["POST"])
@admin_required
def admin_edit_location(loc_id: int):
    """Updates an existing disposal center facility."""
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "Universal").strip()
    address = request.form.get("address", "").strip()
    city = request.form.get("city", "Metro Area").strip()
    phone = request.form.get("phone", "").strip()
    operating_hours = request.form.get("operating_hours", "").strip()
    
    try:
        lat = float(request.form.get("latitude", 0.0))
        lng = float(request.form.get("longitude", 0.0))
    except ValueError:
        flash("Invalid latitude or longitude format.", "error")
        return redirect(url_for("admin_dashboard") + "#disposal")

    if not name or not address:
        flash("Facility name and address are required.", "error")
        return redirect(url_for("admin_dashboard") + "#disposal")

    success = update_disposal_location(
        loc_id=loc_id,
        name=name,
        category=category,
        address=address,
        latitude=lat,
        longitude=lng,
        phone=phone,
        operating_hours=operating_hours,
        city=city
    )

    if success:
        flash(f"Disposal facility '{name}' updated successfully.", "success")
    else:
        flash("Failed to update disposal facility.", "error")
    return redirect(url_for("admin_dashboard") + "#disposal")


@app.route("/admin/disposal-locations/<int:loc_id>/delete", methods=["POST"])
@admin_required
def admin_delete_location(loc_id: int):
    """Deletes a disposal center facility."""
    success = delete_disposal_location(loc_id)
    if success:
        flash(f"Disposal facility #{loc_id} deleted successfully.", "success")
    else:
        flash("Disposal facility could not be found.", "error")
    return redirect(url_for("admin_locations"))


# ---------------------------------------------------------------------------
# Prediction API (With Database Telemetry Logging)
# ---------------------------------------------------------------------------
@app.route("/predict", methods=["POST"])
@login_required
def predict():
    # 1. Make sure the model actually loaded at startup
    if model is None:
        return jsonify({"error": model_load_error or "Model is not available."}), 500

    # 2. Make sure a file was actually sent
    if "image" not in request.files:
        return jsonify({"error": "No image file was uploaded."}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    if not allowed_file(file.filename):
        return jsonify({
            "error": "Unsupported file type. Please upload a .png, .jpg, or .jpeg image."
        }), 400

    # 3. Save the upload, then preprocess.
    # Prefix with a random token so concurrent uploads (from the same or
    # different users) never collide or silently overwrite each other.
    original_name = secure_filename(file.filename)
    filename = f"{uuid.uuid4().hex}_{original_name}"
    save_path = UPLOAD_DIR / filename
    file.save(save_path)

    try:
        input_array = preprocess_image(save_path)
    except UnidentifiedImageError:
        return jsonify({
            "error": "The uploaded file could not be read as a valid image. "
                     "It may be corrupted or in an unsupported format."
        }), 400
    except Exception as exc:  # noqa: BLE001
        # Don't leak internal exception details/paths to the client.
        print("Image preprocessing error:", exc)
        return jsonify({"error": "Could not process the uploaded image."}), 400

    # 4. Multi-provider vision evaluation: Groq -> Gemini -> Groq (last resort)
    analysis = None
    try:
        analysis = analyze_image_multi_provider(save_path)
    except AllProvidersUnavailable as exc:
        # Every vision provider we have (Groq, then Gemini, then Groq again)
        # failed. Do NOT silently fall back to the CNN-only path here —
        # that CNN has no "not waste" category, so a photo of a
        # person/animal or any non-waste object would otherwise get
        # force-classified as waste just because every provider call failed.
        print("All vision providers unavailable after retries:", exc)
        # Clean up the saved upload since we're not going to classify it.
        try:
            save_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        return jsonify({
            "error": "The AI vision service is temporarily unreachable (connection error). "
                     "Please check your internet connection and try again in a moment."
        }), 503
    except Exception as exc:  # noqa: BLE001
        print("Vision analysis call failed:", exc)
        analysis = None

    current_user_id = session.get("user_id")

    # Handle NON-WASTE scenario (Human, Animal, Fresh food, New products, etc.)
    if analysis is not None and analysis.get("is_waste") is False:
        obj = analysis.get("object", "Non-Waste Specimen")
        cond = analysis.get("condition", "Intact / Living")
        cat = analysis.get("category", "Material / Living")
        reason = analysis.get("reason", "The specimen is not classified as waste based on visual condition and context.")
        guidance = get_guidance_for_item(
            cat,
            is_waste=False,
            item_name=obj,
            condition=cond,
            custom_warning=analysis.get("warning", "") if analysis else "",
            custom_instructions=analysis.get("instructions", []) if analysis else None,
        )

        # Log into SQLite database
        saved_classification_id = None
        try:
            saved_classification_id = save_classification(
                image_filename=filename,
                object_name=obj,
                condition=cond,
                category=cat,
                is_waste=False,
                confidence=99.0,
                probabilities={},
                reason=reason,
                user_id=current_user_id
            )
        except Exception as db_err:  # noqa: BLE001
            print("DB classification log error:", db_err)

        return jsonify({
            "status": "ok",
            "is_waste": False,
            "object": obj,
            "item": obj,
            "condition": cond,
            "category": cat,
            "reason": reason,
            "guidance": guidance,
            "protocol": {
                "warning": guidance.get("summary", ""),
                "instructions": guidance.get("tips", []),
            },
            "image_url": f"/static/uploads/{filename}",
            "classification_id": saved_classification_id,
        })

    # 5. Run the waste classifier (CNN)
    try:
        predictions = model.predict(input_array, verbose=0)[0]
    except Exception as exc:  # noqa: BLE001
        print("Model prediction error:", exc)
        return jsonify({"error": "Prediction failed. Please try again."}), 500

    predicted_index = int(np.argmax(predictions))
    predicted_class = CLASS_NAMES[predicted_index]
    confidence = float(predictions[predicted_index]) * 100

    probabilities = {
        CLASS_NAMES[i]: round(float(predictions[i]) * 100, 2)
        for i in range(len(CLASS_NAMES))
    }

    # Extract or infer 5-field values
    if analysis is not None:
        obj = analysis.get("object", "Waste Specimen")
        cond = analysis.get("condition", "Used/Discarded")
        cat = analysis.get("category", f"{predicted_class} Waste")
        reason = analysis.get("reason", f"Identified as {cat.lower()} based on specimen condition.")

        # Harmonize top class with Groq category if valid waste category
        if "Hazardous" in cat:
            predicted_class = "Hazardous"
        elif "Organic" in cat:
            predicted_class = "Organic"
        elif "Recyclable" in cat:
            predicted_class = "Recyclable"
    else:
        obj = "Waste Specimen"
        cond = "Used/Discarded"
        cat = f"{predicted_class} Waste"
        reason = f"Optical features match {predicted_class.lower()} waste pattern with {round(confidence, 1)}% confidence."

    guidance = get_guidance_for_item(
        cat,
        is_waste=True,
        item_name=obj,
        condition=cond,
        custom_warning=analysis.get("warning", "") if analysis else "",
        custom_instructions=analysis.get("instructions", []) if analysis else None,
    )

    # Log into SQLite database
    saved_classification_id = None
    try:
        saved_classification_id = save_classification(
            image_filename=filename,
            object_name=obj,
            condition=cond,
            category=cat,
            is_waste=True,
            confidence=round(confidence, 2),
            probabilities=probabilities,
            reason=reason,
            user_id=current_user_id
        )
    except Exception as db_err:  # noqa: BLE001
        print("DB classification log error:", db_err)

    return jsonify({
        "status": "ok",
        "is_waste": True,
        "class": predicted_class,
        "confidence": round(confidence, 2),
        "probabilities": probabilities,
        "guidance": guidance,
        "protocol": {
            "warning": guidance.get("summary", ""),
            "instructions": guidance.get("tips", []),
        },
        "image_url": f"/static/uploads/{filename}",
        "object": obj,
        "item": obj,
        "condition": cond,
        "category": cat,
        "reason": reason,
        "classification_id": saved_classification_id,
    })


if __name__ == "__main__":
    import webbrowser
    from threading import Timer

    if model_load_error:
        print("WARNING:", model_load_error)

    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"

    # Automatically open the app in the browser
    def open_browser():
        webbrowser.open_new("http://127.0.0.1:5000")

    Timer(1, open_browser).start()

    app.run(debug=debug_mode)
