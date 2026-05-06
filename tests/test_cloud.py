"""
Cloud / R2 endpoint tests.
No deps externas — solo stdlib.
Requiere que el servidor esté corriendo en localhost:8000
y que existan los usuarios de prueba (create_test_users).
"""
import base64
import io
import json
import sys
import urllib.error
import urllib.request
import uuid

BASE   = "http://localhost:8000/api/v1"
TENANT = "00000000-0000-0000-0000-000000000001"

# PNG 1x1 px valido (blanco)
PNG_1x1 = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    b"AAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

passed = 0
failed = 0
errors = []


# ── helpers ──────────────────────────────────────────────────────────────────

def _json_req(method, path, data=None, token=None):
    url     = f"{BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    r    = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:300]}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def _multipart_req(method, path, fields, file_field, file_bytes, file_name, token=None):
    boundary = uuid.uuid4().hex
    body     = io.BytesIO()

    for name, value in fields.items():
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.write(f"{value}\r\n".encode())

    body.write(f"--{boundary}\r\n".encode())
    body.write(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'.encode()
    )
    body.write(b"Content-Type: image/png\r\n\r\n")
    body.write(file_bytes)
    body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())

    url     = f"{BASE}{path}"
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=body.getvalue(), headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:300]}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def check(name, status, body, expected=(200, 201)):
    global passed, failed
    if isinstance(expected, int):
        expected = (expected,)
    ok   = status in expected
    icon = "PASS" if ok else "FAIL"
    print(f"  [{icon}] {name:55s} -> {status}")
    if ok:
        passed += 1
    else:
        failed += 1
        errors.append(f"{name}: esperado {expected}, recibido {status} — {json.dumps(body, ensure_ascii=False)[:200]}")
    return ok, body


# ── inicio ────────────────────────────────────────────────────────────────────

print("=" * 70)
print("  POSTAS - Cloud / R2 Endpoint Tests")
print("=" * 70)

# ── auth ──────────────────────────────────────────────────────────────────────
print("\n--- AUTH ---")
s, login = _json_req("POST", "/auth/login/",
                     {"tenant_id": TENANT, "username": "owner", "password": "owner1234"})
check("Login (owner)", s, login)
TOKEN = login.get("access", "")

s, login_emp = _json_req("POST", "/auth/login/",
                         {"tenant_id": TENANT, "username": "empleado1", "password": "empleado1234"})
check("Login (empleado)", s, login_emp)
EMP_TOKEN = login_emp.get("access", "")

if not TOKEN:
    print("\n[ERROR] No se pudo obtener token. Servidor corriendo? Usuarios creados?")
    sys.exit(1)

# ── health check ──────────────────────────────────────────────────────────────
print("\n--- HEALTH CHECK ---")
s, body = _json_req("GET", "/cloud/health/", token=TOKEN)
ok, body = check("Health check (owner)", s, body)
if ok:
    for step in body.get("steps", []):
        icon = "ok" if step["ok"] else "!!"
        print(f"         [{icon}] {step['step']:10s}  {step.get('ms', '?')}ms"
              + (f"  bucket={step['bucket']}" if "bucket" in step else "")
              + (f"  ERR: {step['error']}" if "error" in step else ""))

s, body = _json_req("GET", "/cloud/health/", token=EMP_TOKEN)
check("Health check (empleado -> 403)", s, body, expected=403)

# ── upload ────────────────────────────────────────────────────────────────────
print("\n--- UPLOAD ---")
s, body = _multipart_req(
    "POST", "/cloud/images/",
    fields={"folder": "test"},
    file_field="image", file_bytes=PNG_1x1, file_name="test_probe.png",
    token=TOKEN,
)
ok, body = check("Subir imagen (owner)", s, body, expected=201)
IMAGE_KEY = body.get("key", "") if ok else ""
IMAGE_URL = body.get("url", "") if ok else ""
if IMAGE_KEY:
    # La key debe arrancar con el tenant_id
    assert IMAGE_KEY.startswith(TENANT), f"Key no tiene prefijo de tenant: {IMAGE_KEY}"
    print(f"         key: {IMAGE_KEY}")
    print(f"         url: {IMAGE_URL}")

# El empleado sube al mismo tenant (su token tiene el mismo tenant_id)
s, body = _multipart_req(
    "POST", "/cloud/images/",
    fields={"folder": "test"},
    file_field="image", file_bytes=PNG_1x1, file_name="test_probe_emp.png",
    token=EMP_TOKEN,
)
ok, body = check("Subir imagen (empleado)", s, body, expected=201)
EMP_IMAGE_KEY = body.get("key", "") if ok else ""
if EMP_IMAGE_KEY:
    assert EMP_IMAGE_KEY.startswith(TENANT), f"Key del empleado sin prefijo de tenant: {EMP_IMAGE_KEY}"

s, body = _multipart_req(
    "POST", "/cloud/images/",
    fields={},
    file_field="image", file_bytes=PNG_1x1, file_name="test_probe.txt",
    token=TOKEN,
)
check("Extension invalida (.txt -> 400)", s, body, expected=400)

s, body = _multipart_req(
    "POST", "/cloud/images/",
    fields={},
    file_field="other_field", file_bytes=PNG_1x1, file_name="test_probe.png",
    token=TOKEN,
)
check("Sin campo 'image' -> 400", s, body, expected=400)

# ── list & get (autenticado) ──────────────────────────────────────────────────
print("\n--- LIST & GET (autenticado) ---")

# Sin prefix: lista todo el tenant
s, body = _json_req("GET", "/cloud/images/", token=TOKEN)
ok, body = check("Listar todo el tenant", s, body)
if ok:
    print(f"         count={body.get('count')}")
    # Verificar que todas las keys pertenecen al tenant
    for img in body.get("images", []):
        assert img["key"].startswith(TENANT), f"Key ajena en listado: {img['key']}"

# Con prefix relativo: lista solo la subcarpeta test/
s, body = _json_req("GET", "/cloud/images/?prefix=test/", token=TOKEN)
ok, body = check("Listar subcarpeta test/ del tenant", s, body)
if ok:
    print(f"         count={body.get('count')}")
    for img in body.get("images", []):
        assert img["key"].startswith(f"{TENANT}/test/"), f"Key fuera de subcarpeta: {img['key']}"

if IMAGE_KEY:
    s, body = _json_req("GET", f"/cloud/images/{IMAGE_KEY}/", token=TOKEN)
    check("Obtener imagen por key (autenticado)", s, body)

# ── aislamiento entre tenants ─────────────────────────────────────────────────
print("\n--- AISLAMIENTO DE TENANT ---")

FAKE_KEY = f"otro-tenant-uuid/images/foto_ajena.png"

# GET con key de otro tenant -> 403
s, body = _json_req("GET", f"/cloud/images/{FAKE_KEY}/", token=TOKEN)
check("GET key de otro tenant -> 403", s, body, expected=403)

# DELETE con key de otro tenant -> 403
s, body = _json_req("DELETE", "/cloud/images/", data={"key": FAKE_KEY}, token=TOKEN)
check("DELETE key de otro tenant -> 403", s, body, expected=403)

# PUT con key de otro tenant -> 403
s, body = _multipart_req(
    "PUT", f"/cloud/images/{FAKE_KEY}/",
    fields={},
    file_field="image", file_bytes=PNG_1x1, file_name="test.png",
    token=TOKEN,
)
check("PUT key de otro tenant -> 403", s, body, expected=403)

# ── endpoints publicos ────────────────────────────────────────────────────────
print("\n--- ENDPOINTS PUBLICOS (sin token) ---")

# Sin tenant_id -> 400
s, body = _json_req("GET", "/cloud/public/images/")
check("Listar sin tenant_id -> 400", s, body, expected=400)

# Con tenant_id correcto -> 200
s, body = _json_req("GET", f"/cloud/public/images/?tenant_id={TENANT}")
ok, body = check("Listar con tenant_id (publico)", s, body)
if ok:
    print(f"         count={body.get('count')}")
    for img in body.get("images", []):
        assert img["key"].startswith(TENANT), f"Key ajena en listado publico: {img['key']}"

# Con prefix relativo
s, body = _json_req("GET", f"/cloud/public/images/?tenant_id={TENANT}&prefix=test/")
ok, body = check("Listar subcarpeta test/ (publico)", s, body)
if ok:
    print(f"         count={body.get('count')}")

# Obtener imagen por key completa
if IMAGE_KEY:
    s, body = _json_req("GET", f"/cloud/public/images/{IMAGE_KEY}/")
    check("Obtener imagen por key (publico)", s, body)

# ── update ────────────────────────────────────────────────────────────────────
print("\n--- UPDATE ---")
if IMAGE_KEY:
    s, body = _multipart_req(
        "PUT", f"/cloud/images/{IMAGE_KEY}/",
        fields={},
        file_field="image", file_bytes=PNG_1x1, file_name="test_probe_updated.png",
        token=TOKEN,
    )
    ok, body = check("Reemplazar imagen (PUT)", s, body)
    if ok:
        IMAGE_KEY = body.get("key", IMAGE_KEY)
        assert IMAGE_KEY.startswith(TENANT), f"Key actualizada sin prefijo de tenant: {IMAGE_KEY}"
        print(f"         nueva key: {IMAGE_KEY}")
else:
    print("  [SKIP] No hay key para actualizar")

# ── delete ────────────────────────────────────────────────────────────────────
print("\n--- DELETE ---")
s, body = _json_req("DELETE", "/cloud/images/", token=TOKEN)
check("Eliminar sin 'key' -> 400", s, body, expected=400)

if IMAGE_KEY:
    s, body = _json_req("DELETE", "/cloud/images/", data={"key": IMAGE_KEY}, token=TOKEN)
    check("Eliminar imagen propia (owner)", s, body)

if EMP_IMAGE_KEY:
    s, body = _json_req("DELETE", "/cloud/images/", data={"key": EMP_IMAGE_KEY}, token=TOKEN)
    check("Eliminar imagen del empleado (owner, mismo tenant)", s, body)

# ── sin autenticacion -> 401 ───────────────────────────────────────────────────
print("\n--- SIN AUTENTICACION ---")
s, body = _json_req("GET", "/cloud/images/")
check("Listar sin token -> 401", s, body, expected=401)

s, body = _json_req("DELETE", "/cloud/images/", data={"key": f"{TENANT}/images/fake.png"})
check("Eliminar sin token -> 401", s, body, expected=401)

# ── resumen ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print(f"  RESULTADO: {passed} pasaron,  {failed} fallaron,  {passed + failed} total")
print("=" * 70)

if errors:
    print("\n  FALLOS:")
    for e in errors:
        print(f"    - {e}")

sys.exit(0 if failed == 0 else 1)
