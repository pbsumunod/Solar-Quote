"""Offline country -> latitude dataset (capital-city latitude, degrees; south is negative).

This is a country-level approximation, not a city-level lookup -- large countries
that span a wide latitude range (Russia, Brazil, Australia, the USA) will only get
their capital's latitude, not a client's exact city. That's a deliberate tradeoff:
the app is fully offline (no geocoding service), and country-level precision is
enough to distinguish "near-equator, lots of sun" from "high-latitude, less sun"
for a sales-sizing tool.
"""

COUNTRY_LATITUDES: dict[str, float] = {
    "Afghanistan": 34.5, "Albania": 41.3, "Algeria": 36.8, "Andorra": 42.5, "Angola": -8.8,
    "Argentina": -34.6, "Armenia": 40.2, "Australia": -35.3, "Austria": 48.2, "Azerbaijan": 40.4,
    "Bahamas": 25.0, "Bahrain": 26.2, "Bangladesh": 23.8, "Barbados": 13.1, "Belarus": 53.9,
    "Belgium": 50.8, "Belize": 17.5, "Benin": 6.5, "Bhutan": 27.5, "Bolivia": -16.5,
    "Bosnia and Herzegovina": 43.9, "Botswana": -24.6, "Brazil": -15.8, "Brunei": 4.9,
    "Bulgaria": 42.7, "Burkina Faso": 12.4, "Burundi": -3.4, "Cambodia": 11.6, "Cameroon": 3.9,
    "Canada": 45.4, "Cape Verde": 14.9, "Central African Republic": 4.4, "Chad": 12.1,
    "Chile": -33.4, "China": 39.9, "Colombia": 4.7, "Comoros": -11.7, "Costa Rica": 9.9,
    "Croatia": 45.8, "Cuba": 23.1, "Cyprus": 35.2, "Czech Republic": 50.1, "Denmark": 55.7,
    "Djibouti": 11.6, "Dominican Republic": 18.5, "Ecuador": -0.2, "Egypt": 30.0,
    "El Salvador": 13.7, "Equatorial Guinea": 3.8, "Eritrea": 15.3, "Estonia": 59.4,
    "Eswatini": -26.3, "Ethiopia": 9.0, "Fiji": -18.1, "Finland": 60.2, "France": 48.9,
    "Gabon": 0.4, "Gambia": 13.5, "Georgia": 41.7, "Germany": 52.5, "Ghana": 5.6,
    "Greece": 38.0, "Grenada": 12.1, "Guatemala": 14.6, "Guinea": 9.5, "Guinea-Bissau": 12.0,
    "Guyana": 6.8, "Haiti": 18.5, "Honduras": 14.1, "Hungary": 47.5, "Iceland": 64.1,
    "India": 28.6, "Indonesia": -6.2, "Iran": 35.7, "Iraq": 33.3, "Ireland": 53.3,
    "Israel": 31.8, "Italy": 41.9, "Ivory Coast": 6.8, "Jamaica": 18.0, "Japan": 35.7,
    "Jordan": 31.9, "Kazakhstan": 51.2, "Kenya": -1.3, "Kiribati": 1.5, "Kosovo": 42.7,
    "Kuwait": 29.4, "Kyrgyzstan": 42.9, "Laos": 17.97, "Latvia": 56.9, "Lebanon": 33.9,
    "Lesotho": -29.3, "Liberia": 6.3, "Libya": 32.9, "Liechtenstein": 47.1, "Lithuania": 54.7,
    "Luxembourg": 49.6, "Madagascar": -18.9, "Malawi": -13.9, "Malaysia": 3.1, "Maldives": 4.2,
    "Mali": 12.6, "Malta": 35.9, "Marshall Islands": 7.1, "Mauritania": 18.1, "Mauritius": -20.2,
    "Mexico": 19.4, "Micronesia": 6.9, "Moldova": 47.0, "Monaco": 43.7, "Mongolia": 47.9,
    "Montenegro": 42.4, "Morocco": 34.0, "Mozambique": -25.9, "Myanmar": 16.9, "Namibia": -22.6,
    "Nauru": -0.5, "Nepal": 27.7, "Netherlands": 52.4, "New Zealand": -41.3, "Nicaragua": 12.1,
    "Niger": 13.5, "Nigeria": 9.1, "North Korea": 39.0, "North Macedonia": 42.0, "Norway": 59.9,
    "Oman": 23.6, "Pakistan": 33.7, "Palau": 7.3, "Palestine": 31.9, "Panama": 9.0,
    "Papua New Guinea": -9.5, "Paraguay": -25.3, "Peru": -12.0, "Philippines": 14.6,
    "Poland": 52.2, "Portugal": 38.7, "Qatar": 25.3, "Romania": 44.4, "Russia": 55.75,
    "Rwanda": -1.9, "Saint Kitts and Nevis": 17.3, "Saint Lucia": 14.0, "Saint Vincent and the Grenadines": 13.2,
    "Samoa": -13.8, "San Marino": 43.9, "Sao Tome and Principe": 0.3, "Saudi Arabia": 24.7,
    "Senegal": 14.7, "Serbia": 44.8, "Seychelles": -4.6, "Sierra Leone": 8.5, "Singapore": 1.35,
    "Slovakia": 48.1, "Slovenia": 46.1, "Solomon Islands": -9.4, "Somalia": 2.0, "South Africa": -25.7,
    "South Korea": 37.6, "South Sudan": 4.9, "Spain": 40.4, "Sri Lanka": 6.9, "Sudan": 15.6,
    "Suriname": 5.9, "Sweden": 59.3, "Switzerland": 46.9, "Syria": 33.5, "Taiwan": 25.0,
    "Tajikistan": 38.6, "Tanzania": -6.2, "Thailand": 13.75, "Timor-Leste": -8.6, "Togo": 6.1,
    "Tonga": -21.1, "Trinidad and Tobago": 10.7, "Tunisia": 36.8, "Turkey": 39.9, "Turkmenistan": 37.9,
    "Tuvalu": -8.5, "Uganda": 0.3, "Ukraine": 50.5, "United Arab Emirates": 24.5,
    "United Kingdom": 51.5, "United States": 38.9, "Uruguay": -34.9, "Uzbekistan": 41.3,
    "Vanuatu": -17.7, "Vatican City": 41.9, "Venezuela": 10.5, "Vietnam": 21.0,
    "Yemen": 15.4, "Zambia": -15.4, "Zimbabwe": -17.8,
}


def latitude_for_country(country: str) -> float | None:
    return COUNTRY_LATITUDES.get(country)


def solar_latitude_factor(latitude_deg: float) -> float:
    """Approximate relative solar-harvest multiplier for a latitude, 1.0 at the equator.

    Uses cos(latitude) as a simple stand-in for how directly sunlight hits the ground
    on average -- a real irradiance model would also need season, altitude, and local
    climate, which this app has no data source for offline. The result is clamped to
    [0.35, 1.0] so even high-latitude locations (which still get usable sun, especially
    in summer) don't get scaled toward zero.
    """
    import math

    factor = math.cos(math.radians(min(75.0, abs(latitude_deg))))
    return max(0.35, min(1.0, factor))
