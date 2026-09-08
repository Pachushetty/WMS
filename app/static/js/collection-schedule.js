/**
 * EcoCycle AI — Area & PIN-Based Waste Collection Schedule helpers.
 *
 * Flow: User enters Area / Locality + PIN Code -> Backend / Geocoding resolves
 * precise Latitude & Longitude -> Matches with Admin Collector Availability.
 */

/**
 * Geocodes an Area + PIN Code + Address into coordinates (lat, lng).
 * Calls the backend /api/geocode endpoint or Nominatim as fallback.
 */
async function geocodeAreaAndPincode(area, pincode, address) {
  try {
    const params = new URLSearchParams();
    if (area) params.append('area', area);
    if (pincode) params.append('pincode', pincode);
    if (address) params.append('address', address);

    const res = await fetch(`/api/geocode?${params.toString()}`);
    if (res.ok) {
      const data = await res.json();
      if (data.status === 'ok') {
        return { lat: data.lat, lng: data.lng, display_name: data.display_name };
      }
    }
  } catch (err) {
    console.warn('Backend geocode endpoint failed, attempting direct query:', err);
  }

  // Client-side fallback to Nominatim
  try {
    const qParts = [address, area, pincode].filter(Boolean).join(', ');
    const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${encodeURIComponent(qParts)}`;
    const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
    if (!res.ok) return null;
    const list = await res.json();
    if (list && list.length > 0) {
      return {
        lat: parseFloat(list[0].lat),
        lng: parseFloat(list[0].lon),
        display_name: list[0].display_name
      };
    }
  } catch (err) {
    console.error('Client geocoding fallback failed:', err);
  }

  return null;
}

/**
 * Asks the backend whether an active pickup schedule and collector exist
 * for the given Area and PIN Code.
 */
async function lookupCollectionSchedule(area, pincode) {
  try {
    const params = new URLSearchParams();
    if (area) params.append('area', area);
    if (pincode) params.append('pincode', pincode);

    const res = await fetch(`/api/collection/schedule-lookup?${params.toString()}`);
    const data = await res.json();
    if (!res.ok) {
      return { status: 'error', available: false, message: data.error || 'Could not check the collection schedule.' };
    }
    return data;
  } catch (err) {
    console.error('Schedule lookup failed:', err);
    return { status: 'error', available: false, message: 'Network error while checking the collection schedule.' };
  }
}

/** Formats "09:00" -> "9:00 AM" for display. */
function formatScheduleTime(hhmm) {
  if (!hhmm) return '';
  const [hStr, mStr] = hhmm.split(':');
  let h = parseInt(hStr, 10);
  if (isNaN(h)) return hhmm;
  const m = (mStr || '00').padStart(2, '0');
  const suffix = h >= 12 ? 'PM' : 'AM';
  h = h % 12;
  if (h === 0) h = 12;
  return `${h}:${m} ${suffix}`;
}

/** Formats an ISO date "2026-09-07" -> "Mon, Sep 7". */
function formatScheduleDate(isoDate) {
  if (!isoDate) return '';
  const d = new Date(isoDate + 'T00:00:00');
  if (isNaN(d.getTime())) return isoDate;
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}
