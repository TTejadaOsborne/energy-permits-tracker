"""
test_boe_api.py — Diagnosticar el problema de la API del BOE
python test_boe_api.py
"""
import requests

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
})

print("=== Test API BOE ===")

tests = [
    # Formato XML (original)
    ("XML Accept",  "https://boe.es/datosabiertos/api/boe/sumario/20260424",
     {"Accept": "application/xml"}),
    # Formato JSON
    ("JSON Accept", "https://boe.es/datosabiertos/api/boe/sumario/20260424",
     {"Accept": "application/json"}),
    # Sin Accept
    ("Sin Accept",  "https://boe.es/datosabiertos/api/boe/sumario/20260424",
     {}),
    # URL www
    ("www URL",     "https://www.boe.es/datosabiertos/api/boe/sumario/20260424",
     {"Accept": "application/json"}),
    # Fecha reciente
    ("Hoy",         "https://boe.es/datosabiertos/api/boe/sumario/20260507",
     {"Accept": "application/json"}),
]

for nombre, url, headers in tests:
    try:
        r = s.get(url, headers=headers, timeout=15)
        ct = r.headers.get("Content-Type","")[:50]
        print(f"\n[{nombre}]")
        print(f"  Status: {r.status_code} | {len(r.content)}B | {ct}")
        print(f"  Content: {r.text[:300]}")
    except Exception as e:
        print(f"\n[{nombre}] ERROR: {e}")

print("\n=== COMPLETADO ===")
