"""
POSTAS API - Comprehensive Endpoint Test
Tests all CRUD operations for every model.
Uses only stdlib (urllib) - no external deps needed.
"""
import json
import urllib.request
import urllib.error
import sys
import os

# Write output only to file to avoid terminal issues
_log_file = open("test_results.txt", "w", encoding="utf-8")
_orig_print = print
def print(*args, **kwargs):
    _orig_print(*args, **kwargs, file=_log_file, flush=True)

BASE = "http://localhost:8000/api/v1"
TENANT = "00000000-0000-0000-0000-000000000001"

passed = 0
failed = 0
errors = []


def req(method, path, data=None, token=None, expected=(200, 201)):
    """Make an HTTP request and return (status, body_dict)."""
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            raw = resp.read().decode()
            status = resp.status
            result = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        status = e.code
        try:
            result = json.loads(raw)
        except Exception:
            result = {"raw": raw[:300]}
    except Exception as e:
        status = 0
        result = {"error": f"{type(e).__name__}: {e}"}

    return status, result


def test(name, method, path, data=None, token=None, expected=(200, 201)):
    global passed, failed
    status, body = req(method, path, data, token, expected)
    if isinstance(expected, int):
        expected = (expected,)
    ok = status in expected
    icon = "PASS" if ok else "FAIL"
    print(f"  [{icon}] {name:45s} -> {status}")
    if ok:
        passed += 1
    else:
        failed += 1
        errors.append(f"{name}: expected {expected}, got {status} - {json.dumps(body, ensure_ascii=False)[:200]}")
    return status, body


# ──────────────────────────────────────────────
print("=" * 60)
print("  POSTAS API - Full Endpoint Test")
print("=" * 60)

# ── AUTH ──────────────────────────────────────
print("\n--- AUTH ---")
_, login = test("Login (owner)", "POST", "/auth/login/",
                {"tenant_id": TENANT, "username": "owner", "password": "owner1234"})
TOKEN = login.get("access", "")

_, login_emp = test("Login (empleado1)", "POST", "/auth/login/",
                    {"tenant_id": TENANT, "username": "empleado1", "password": "empleado1234"})
EMP_TOKEN = login_emp.get("access", "")

test("Login bad password", "POST", "/auth/login/",
     {"tenant_id": TENANT, "username": "owner", "password": "wrong"}, expected=(400,))

test("Token refresh", "POST", "/auth/token/refresh/",
     {"refresh": login.get("refresh", "")})

if not TOKEN:
    print("\n[ERROR] Cannot continue without token. Aborting.")
    sys.exit(1)

# ── USERS (owner only) ───────────────────────
print("\n--- USERS ---")
test("List users", "GET", "/users/", token=TOKEN)

_, new_user = test("Create user", "POST", "/users/",
                   {"username": "test_tmp", "email": "tmp@test.com",
                    "password": "tmp12345", "role": "EMPLOYEE"}, token=TOKEN)
user_uuid = new_user.get("uuid", "")

if user_uuid:
    test("Get user detail", "GET", f"/users/{user_uuid}/", token=TOKEN)
    test("Update user (PATCH)", "PATCH", f"/users/{user_uuid}/",
         {"email": "updated@test.com"}, token=TOKEN)
    test("Delete user (soft)", "DELETE", f"/users/{user_uuid}/", token=TOKEN, expected=(204,))

test("Create user (employee -> 403)", "POST", "/users/",
     {"username": "nope", "email": "no@no.com", "password": "x1234567", "role": "EMPLOYEE"},
     token=EMP_TOKEN, expected=(403,))

# ── CATEGORIES ────────────────────────────────
print("\n--- CATEGORIES ---")
test("List categories", "GET", "/categories/", token=TOKEN)

_, new_cat = test("Create category", "POST", "/categories/",
                  {"name": "Test Category TMP"}, token=TOKEN)
cat_uuid = new_cat.get("uuid", "")

if cat_uuid:
    test("Get category detail", "GET", f"/categories/{cat_uuid}/", token=TOKEN)
    test("Update category", "PATCH", f"/categories/{cat_uuid}/",
         {"name": "Updated Category"}, token=TOKEN)

# ── PRODUCTS ──────────────────────────────────
print("\n--- PRODUCTS ---")
test("List products", "GET", "/products/", token=TOKEN)

_, new_prod = test("Create product", "POST", "/products/",
                   {"name": "Test Product TMP", "price": "999.99", "cost": "500.00",
                    "unit": "U", "stock": 100, "min_stock": 5,
                    "category_id": cat_uuid if cat_uuid else None}, token=TOKEN)
prod_uuid = new_prod.get("uuid", "")

if prod_uuid:
    test("Get product detail", "GET", f"/products/{prod_uuid}/", token=TOKEN)
    test("Update product", "PATCH", f"/products/{prod_uuid}/",
         {"price": "1099.99", "stock": 200}, token=TOKEN)
    test("Search product (by name)", "GET", "/products/search/?q=Test+Product", token=TOKEN)

test("List products low_stock", "GET", "/products/?low_stock=true", token=TOKEN)

# ── CASHBOX ───────────────────────────────────
print("\n--- CASHBOX ---")
test("List cashboxes", "GET", "/cashboxes/", token=TOKEN)

# Close current open cashbox first (from seed) so we can test open/close cycle
_, current = req("GET", "/cashboxes/current/", token=TOKEN)
if current and current.get("uuid"):
    test("Close existing cashbox", "POST", "/cashboxes/close/",
         {"final_amount": "10000.00"}, token=TOKEN)

_, opened = test("Open cashbox", "POST", "/cashboxes/open/",
                 {"initial_amount": "5000.00"}, token=TOKEN)
cashbox_uuid = opened.get("uuid", "")

test("Get current cashbox", "GET", "/cashboxes/current/", token=TOKEN)

if cashbox_uuid:
    test("Get cashbox detail", "GET", f"/cashboxes/{cashbox_uuid}/", token=TOKEN)

# ── SALES (need open cashbox) ─────────────────
print("\n--- SALES ---")
test("List sales", "GET", "/sales/", token=TOKEN)

# Get a product UUID for the sale
_, prods = req("GET", "/products/", token=TOKEN)
product_list = prods.get("results", [])
sale_product_uuid = product_list[0]["uuid"] if product_list else prod_uuid

if sale_product_uuid:
    _, new_sale = test("Create sale (CASH)", "POST", "/sales/",
                       {"payment_method": "CASH",
                        "items": [{"product_id": sale_product_uuid, "quantity": 2}]},
                       token=TOKEN)
    sale_uuid = new_sale.get("uuid", "")

    _, new_sale2 = test("Create sale (CARD)", "POST", "/sales/",
                        {"payment_method": "CARD",
                         "items": [{"product_id": sale_product_uuid, "quantity": 1}]},
                        token=TOKEN)

    if sale_uuid:
        test("Get sale detail", "GET", f"/sales/{sale_uuid}/", token=TOKEN)
        test("Cancel sale", "POST", f"/sales/{sale_uuid}/cancel/", token=TOKEN)

    # Employee can create sales
    _, emp_sale = test("Create sale (employee)", "POST", "/sales/",
                       {"payment_method": "TRANSFER",
                        "items": [{"product_id": sale_product_uuid, "quantity": 1}]},
                       token=EMP_TOKEN)
    emp_sale_uuid = emp_sale.get("uuid", "")
    if emp_sale_uuid:
        test("Cancel sale (employee -> 403)", "POST", f"/sales/{emp_sale_uuid}/cancel/",
             token=EMP_TOKEN, expected=(403,))
else:
    print("  [SKIP] No products available for sale tests")

# Close cashbox to finalize
test("Close cashbox", "POST", "/cashboxes/close/",
     {"final_amount": "12000.00"}, token=TOKEN)

# ── REPORTS ───────────────────────────────────
print("\n--- REPORTS ---")
test("Daily sales report", "GET",
     "/reports/sales/daily/?from=2026-02-01&to=2026-03-23", token=TOKEN)
test("Sales by payment", "GET",
     "/reports/sales/by-payment/?from=2026-02-01&to=2026-03-23", token=TOKEN)
test("Top products", "GET",
     "/reports/products/top/?from=2026-02-01&to=2026-03-23", token=TOKEN)

# Get a cashbox_id for summary (use first from list)
_, cashbox_list = req("GET", "/cashboxes/", token=TOKEN)
cb_results = cashbox_list.get("results", [])
cb_id = cb_results[0]["uuid"] if cb_results else ""
if cb_id:
    test("Cashbox summary (by id)", "GET",
         f"/reports/cashbox/summary/?cashbox_id={cb_id}", token=TOKEN)
else:
    print("  [SKIP] No cashbox available for summary test")

test("Report (employee -> 403)", "GET",
     "/reports/sales/daily/?from=2026-03-01&to=2026-03-23", token=EMP_TOKEN, expected=(403,))

# ── AUDIT ─────────────────────────────────────
print("\n--- AUDIT ---")
test("List audit logs", "GET", "/audit/", token=TOKEN)
test("Audit filter by action", "GET", "/audit/?action=CREATE", token=TOKEN)
test("Audit filter by entity", "GET", "/audit/?entity=PRODUCT", token=TOKEN)
test("Audit (employee -> 403)", "GET", "/audit/", token=EMP_TOKEN, expected=(403,))

# ── CLEANUP: delete temp category & product ──
print("\n--- CLEANUP ---")
if prod_uuid:
    test("Delete test product", "DELETE", f"/products/{prod_uuid}/", token=TOKEN, expected=(204,))
if cat_uuid:
    test("Delete test category", "DELETE", f"/categories/{cat_uuid}/", token=TOKEN, expected=(204,))

# ── SUMMARY ───────────────────────────────────
print("\n" + "=" * 60)
print(f"  RESULTS: {passed} passed, {failed} failed, {passed + failed} total")
print("=" * 60)

if errors:
    print("\n  FAILURES:")
    for e in errors:
        print(f"    - {e}")

sys.exit(0 if failed == 0 else 1)

