import json, urllib.request, urllib.error, re

BASE = "http://localhost:8000/api/v1"
TENANT = "00000000-0000-0000-0000-000000000001"

# Login
data = json.dumps({"tenant_id": TENANT, "username": "owner", "password": "owner1234"}).encode()
r = urllib.request.Request(BASE + "/auth/login/", data, {"Content-Type": "application/json"}, method="POST")
token = json.loads(urllib.request.urlopen(r, timeout=10).read())["access"]
print("Logged in OK")

# Get product
r2 = urllib.request.Request(BASE + "/products/", headers={"Authorization": "Bearer " + token})
prods = json.loads(urllib.request.urlopen(r2, timeout=10).read()).get("results", [])
pid = prods[0]["uuid"] if prods else None
print(f"Product: {pid}")

# Create sale
data2 = json.dumps({"payment_method": "CASH", "items": [{"product_id": pid, "quantity": 1}]}).encode()
r3 = urllib.request.Request(BASE + "/sales/", data2, {"Content-Type": "application/json", "Authorization": "Bearer " + token}, method="POST")
try:
    resp = urllib.request.urlopen(r3, timeout=15)
    print(f"OK {resp.status}: {resp.read().decode()[:300]}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    # Extract exception value and traceback
    exc_val = re.search(r'exception_value">(.*?)</pre>', body, re.DOTALL)
    # Find the last traceback entry
    tb_entries = re.findall(r'<td class="source"><pre>(.*?)</pre>', body)
    print(f"ERROR {e.code}")
    try:
        print(f"Detail: {json.loads(body)}")
    except Exception:
        if exc_val:
            print(f"Exception: {exc_val.group(1)[:300]}")
    if tb_entries:
        print(f"Last source lines:")
        for t in tb_entries[-5:]:
            print(f"  {t}")
except Exception as e:
    print(f"Other error: {type(e).__name__}: {e}")
