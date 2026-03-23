import json, urllib.request, urllib.error, re

BASE = "http://localhost:8000/api/v1"
TENANT = "00000000-0000-0000-0000-000000000001"

def post(path, data, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(f"{BASE}{path}", json.dumps(data).encode(), headers, method="POST")
    try:
        resp = urllib.request.urlopen(r)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        title = re.search(r"<title>(.*?)</title>", body)
        exc = re.search(r'exception_value">(.*?)</pre>', body, re.DOTALL)
        return e.code, {
            "title": title.group(1) if title else "?",
            "exception": (exc.group(1)[:300] if exc else body[:300]),
        }

# Login
status, data = post("/auth/login/", {"tenant_id": TENANT, "username": "owner", "password": "owner1234"})
print(f"Login: {status}")
TOKEN = data.get("access", "")

# User create
print("\n--- USER CREATE ---")
s, d = post("/users/", {"username": "debugtest", "email": "debug@test.com", "password": "debug12345", "role": "EMPLOYEE"}, TOKEN)
print(f"Status: {s}")
print(f"Body: {json.dumps(d, indent=2, ensure_ascii=False)[:500]}")

# Product create
print("\n--- PRODUCT CREATE ---")
s, d = post("/products/", {"name": "Debug Product", "price": "100.00", "cost": "50.00", "unit": "U", "stock": 10, "min_stock": 2}, TOKEN)
print(f"Status: {s}")
print(f"Body: {json.dumps(d, indent=2, ensure_ascii=False)[:500]}")

# Sale create
print("\n--- SALE CREATE ---")
# Get a product
r = urllib.request.Request(f"{BASE}/products/", headers={"Authorization": f"Bearer {TOKEN}"})
resp = urllib.request.urlopen(r)
prods = json.loads(resp.read()).get("results", [])
if prods:
    pid = prods[0]["uuid"]
    s, d = post("/sales/", {"payment_method": "CASH", "items": [{"product_id": pid, "quantity": 1}]}, TOKEN)
    print(f"Status: {s}")
    print(f"Body: {json.dumps(d, indent=2, ensure_ascii=False)[:500]}")
