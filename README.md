# 🚀 Proyecto POSTAS
---

## ⚙️ Configuración del entorno

### 1. Clonar el repositorio

```bash
git clone https://github.com/tu-usuario/nombre-del-proyecto.git
cd nombre-del-proyecto
```

### 2. Crear y activar el entorno virtual

```bash
# Crear el entorno virtual
python -m venv venv

# Activar en Linux/macOS
source venv/bin/activate

# Activar en Windows
venv\Scripts\activate
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

---

## 🔐 Variables de entorno

Copiá el archivo de ejemplo y completá los valores:

```bash
cp .env-example .env
```

Editá el archivo `.env` con tus configuraciones locales:

```env
SECRET_KEY=tu_clave_secreta_aqui
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,api,tu-dominio-o-ip
CSRF_TRUSTED_ORIGINS=http://tu-dominio-o-ip:3000
FRONTEND_URL=http://tu-dominio-o-ip:3000
PORT=8000
WEB_CONCURRENCY=2
GUNICORN_TIMEOUT=60

# Base de datos (solo si no usás SQLite)
DATABASE_URL=postgres://usuario:contraseña@localhost:5432/nombre_db

# Email
EMAIL_PROVIDER=resend
EMAIL_FALLBACK_PROVIDER=django
EMAIL_PROVIDER_FALLBACK_ENABLED=True
DEFAULT_FROM_EMAIL=POSTAS <notificaciones@tu-dominio-verificado.com>
EMAIL_TIMEOUT=20

# Resend principal
RESEND_API_KEY=
RESEND_API_URL=https://api.resend.com
RESEND_COST_PER_1000_EMAILS=0.90

# Django fallback actual
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
DJANGO_EMAIL_COST_PER_1000_EMAILS=0
```

> ⚠️ **Nunca subas el archivo `.env` al repositorio.** Asegurate de que esté en `.gitignore`.

`EMAIL_PROVIDER=resend` usa la libreria oficial de Resend como proveedor principal.
`EMAIL_PROVIDER=django` usa el backend actual de Django (`EMAIL_BACKEND`) y permite seguir usando SMTP o `console.EmailBackend`.
Con `EMAIL_PROVIDER=resend`, si falla Resend y `EMAIL_PROVIDER_FALLBACK_ENABLED=True`, el sistema intenta enviar con `EMAIL_FALLBACK_PROVIDER=django`.

En Railway Free/Trial/Hobby, SMTP no esta disponible. Por eso el proveedor recomendado ahi es Resend por API HTTPS.
`RESEND_COST_PER_1000_EMAILS` y `DJANGO_EMAIL_COST_PER_1000_EMAILS` se usan para estimar costo por email en la tabla `notifications_email_deliveries`.

Para verificar la configuracion dentro del contenedor:

```bash
python manage.py debug_email --skip-db
python manage.py debug_email --tenant-id <tenant_uuid> --send
```

En un servidor de desarrollo con Docker, el `Dockerfile` ejecuta Gunicorn y lee `PORT`, `WEB_CONCURRENCY` y `GUNICORN_TIMEOUT` desde el entorno. El healthcheck del contenedor consulta `GET /healthz/`.

```bash
docker build -t postas-api:dev .
docker run --env-file .env -p 8000:8000 postas-api:dev
```

---

## 🗄️ Base de datos

### Aplicar migraciones

```bash
python manage.py migrate
```

---

## 👤 Crear superusuario

```bash
python manage.py createsuperuser
```

---

## ▶️ Ejecutar el servidor de desarrollo

```bash
python manage.py runserver
```

---

## 🧪 Ejecutar tests

```bash
python manage.py test
```
---

## 📁 Estructura del proyecto

```
/config
/apps
   /tenants
   /users
   /products
   /sales
   /cashbox
   /reports
   /audit
   /suppliers
   /notifications
/core
   /middleware
   /permissions
   /models
   /utils
   /cloud
/manage.py
```

---

## 🛠️ Comandos útiles

| Comando | Descripción |
|---|---|
| `python manage.py makemigrations` | Crear nuevas migraciones |
| `python manage.py migrate` | Aplicar migraciones |
| `python manage.py shell` | Abrir shell interactivo de Django |
| `python manage.py collectstatic` | Recolectar archivos estáticos |
| `python manage.py createsuperuser` | Crear usuario administrador |
| `python manage.py test` | Ejecutar tests |
| `python manage.py create_test_users` | Crear usuarios de prueba (ver abajo) |
| `python manage.py seed_data` | Poblar la DB con datos ficticios |
| `python manage.py reset_db` | Resetear la base de datos |

---

## 🧪 Scripts de prueba

### Crear usuarios de prueba

Crea un tenant de prueba con 4 usuarios (Owner, Admin, 2 Empleados):

```bash
python manage.py create_test_users
```

| Rol | Usuario | Contraseña |
|-----|---------|------------|
| OWNER | `owner` | `owner1234` |
| ADMIN | `admin` | `admin1234` |
| EMPLOYEE | `empleado1` | `empleado1234` |
| EMPLOYEE | `empleado2` | `empleado1234` |

**Tenant ID:** `00000000-0000-0000-0000-000000000001`

Para usar un tenant distinto:

```bash
python manage.py create_test_users --tenant-id <uuid>
```

### Poblar la base de datos

Genera datos realistas desde `openfoodfacts_products_clean.csv`: categorias del dataset, 100 productos de OpenFoodFacts, cajas diarias, ventas con detalle y audit logs:

```bash
python manage.py seed_data
```

Opciones:

```bash
python manage.py seed_data --sales 200       # Cantidad de ventas (default: 150)
python manage.py seed_data --days 60          # Distribuir en N días (default: 30)
python manage.py seed_data --tenant-id <uuid> # Tenant específico
python manage.py seed_data --products-csv openfoodfacts_products_clean.csv
```

> ⚠️ Requiere que los usuarios de prueba existan. Ejecutar `create_test_users` primero.
> El comando reemplaza los productos activos del tenant por los del CSV. Si `price`, `cost`, `stock` o `min_stock` vienen en cero, usa valores de prueba deterministicos para que las ventas y validaciones sigan funcionando.

### Resetear la base de datos

Borra todos los datos, re-aplica migraciones y opcionalmente re-pobla:

```bash
# Solo resetear
python manage.py reset_db

# Resetear + re-poblar con datos de prueba
python manage.py reset_db --seed

# Sin confirmación + custom sales
python manage.py reset_db --seed --sales 200 --yes
```

### Ejemplo de login

```bash
curl -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "00000000-0000-0000-0000-000000000001", "username": "owner", "password": "owner1234"}'
```

---

## 📖 Documentación de la API

La API cuenta con documentación interactiva generada automáticamente con **drf-spectacular** (OpenAPI 3.0).

| URL | Descripción |
|-----|-------------|
| `/api/docs/` | **Swagger UI** — Interfaz interactiva para probar endpoints |
| `/api/redoc/` | **Redoc** — Documentación en formato legible |
| `/api/schema/` | **Schema OpenAPI** — Especificación YAML descargable |

### Endpoints documentados

La documentación incluye **ejemplos de request/response**, **filtros** y **paginación** para todos los módulos:

| Tag | Endpoints | Descripción |
|-----|-----------|-------------|
| **Auth** | `POST /api/v1/auth/login/`, `POST /api/v1/auth/token/refresh/` | Login con JWT (tenant_id + username + password) y refresh de token |
| **Users** | `GET/POST /api/v1/users/`, `GET/PATCH/DELETE /api/v1/users/{uuid}/` | CRUD de usuarios (solo OWNER). DELETE es soft delete |
| **Categories** | `GET/POST /api/v1/categories/`, `GET/PATCH/DELETE /api/v1/categories/{uuid}/` | Lectura para usuarios autenticados; escritura ADMIN/OWNER |
| **Products** | `GET/POST /api/v1/products/`, `GET/PATCH/DELETE /api/v1/products/{uuid}/`, `GET /api/v1/products/search/` | Lectura para usuarios autenticados; escritura ADMIN/OWNER. Filtros: `category_id`, `low_stock` |
| **TenantConfig** | `GET/PATCH /api/v1/tenant/config/` | Configuración del tenant actual. Incluye email para notificaciones de caja |
| **Cashbox** | `POST /open/`, `POST /close/`, `GET /current/`, `GET /`, `GET /{uuid}/`, `POST /{uuid}/notify-email/` | EMPLOYEE puede abrir y ver solo caja actual; ADMIN/OWNER pueden listar/ver cajas |
| **Sales** | `GET/POST /api/v1/sales/`, `GET /{uuid}/`, `POST /{uuid}/cancel/` | EMPLOYEE puede vender y ver ventas de la caja actual; ADMIN/OWNER ven todo. Filtros: `user_id`, `payment_method`, `from`, `to` |
| **Reports** | `GET daily/`, `GET by-payment/`, `GET top-products/`, `GET cashbox-summary/` | Reportes con filtros de fechas y paginación |
| **Audit** | `GET /api/v1/audit/` | Logs de auditoría. Filtros: `action`, `entity`, `user`, `timestamp` |
| **Suppliers** | `GET/POST /api/v1/suppliers/`, `GET/PATCH/DELETE /api/v1/suppliers/{uuid}/` | CRUD de proveedores (ADMIN/OWNER). DELETE es soft delete |
| **Suppliers** | `GET/POST /api/v1/product-suppliers/`, `GET/PATCH/DELETE /api/v1/product-suppliers/{uuid}/` | Historial de relaciones producto-proveedor. Filtros: `product`, `is_current` |
| **Suppliers** | `POST /api/v1/product-suppliers/switch/` | Cambia el proveedor activo de un producto (desactiva los anteriores) |
| **Cloud** | `GET/POST/DELETE /api/v1/cloud/images/`, `GET/PUT /api/v1/cloud/images/{key}/` | CRUD de imágenes (autenticado, cualquier rol) |
| **Cloud** | `GET /api/v1/cloud/public/images/`, `GET /api/v1/cloud/public/images/{key}/` | Lectura pública de imágenes (sin autenticación) |
| **Cloud** | `GET /api/v1/cloud/health/` | Health check del bucket R2 (ADMIN/OWNER) |

### Paginación

Todos los endpoints de listado usan **PageNumberPagination** con `PAGE_SIZE=20`:

```
GET /api/v1/products/?page=2
```

Respuesta:
```json
{
  "count": 98,
  "next": "http://localhost:8000/api/v1/products/?page=3",
  "previous": "http://localhost:8000/api/v1/products/?page=1",
  "results": [...]
}
```

### Autenticación en Swagger UI

1. Hacé login en `POST /api/v1/auth/login/` para obtener el token
2. Clickeá el botón **Authorize** 🔒 en Swagger UI
3. Ingresá: `Bearer <tu_access_token>`
4. Todos los endpoints autenticados funcionarán

---

## ⚙️ Configuración del tenant

El módulo `apps.tenants` centraliza la configuración propia de cada tenant.

### Modelos

**`Tenant`** — Entidad base del tenant.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `uuid` | UUID (PK) | Identificador del tenant |
| `name` | CharField | Nombre interno/opcional |
| `active` | BooleanField | Estado del tenant |

**`TenantConfig`** — Configuración operativa del tenant.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `tenant` | OneToOne FK → Tenant | Configuración asociada al tenant |
| `notification_email` | EmailField | Email del dueño/empresa que recibe notificaciones |
| `cashbox_email_notifications_enabled` | BooleanField | Habilita/deshabilita emails automáticos de caja |

### Endpoints

Requieren JWT y rol `OWNER`.

```http
GET /api/v1/tenant/config/
Authorization: Bearer <access_token>
```

Devuelve la configuración del tenant actual. Si no existe, crea una configuración vacía.

```http
PATCH /api/v1/tenant/config/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "notification_email": "empresa@cliente.com",
  "cashbox_email_notifications_enabled": true
}
```

---

## 📧 Notificaciones por email

El módulo `apps.notifications` centraliza el armado, envío y registro de emails. Los flujos actuales son:

- Apertura/cierre de caja a `TenantConfig.notification_email`.
- Restablecimiento de contraseña.
- Emails de prueba con `python manage.py debug_email`.

Providers:

- `resend`: proveedor principal con la librería oficial `resend`.
- `django`: fallback actual basado en `EMAIL_BACKEND` (`smtp`, `console`, `locmem`, etc.).

Cada intento de envío se registra en la tabla `notifications_email_deliveries`, con provider, estado, destinatarios, external id, error y costo estimado en USD. Si Resend falla y el fallback está habilitado, quedan dos filas: una `FAILED` de Resend y una `SENT` de Django si el fallback envió correctamente.

Al abrir o cerrar una caja, la API intenta enviar automáticamente un email al valor de `TenantConfig.notification_email`.

Flujo:

1. `POST /api/v1/cashboxes/open/` crea la caja y dispara email de apertura.
2. `POST /api/v1/cashboxes/close/` cierra la caja y dispara email de cierre.
3. Si falta `TenantConfig`, falta `notification_email` o las notificaciones están desactivadas, la caja igualmente se abre/cierra.
4. El resultado queda registrado en `notifications_email_deliveries` y también en auditoría:
   - `CASHBOX_EMAIL`: email enviado.
   - `CASHBOX_EMAIL_SKIP`: envío omitido por configuración.
   - `CASHBOX_EMAIL_FAILED`: fallo técnico al enviar.

El cuerpo del email se arma desde `apps.cashbox.models.Cashbox` e incluye:

| Evento | Datos incluidos |
|--------|-----------------|
| Apertura | UUID de caja, tenant, estado, usuario que abrió, fecha de apertura, monto inicial |
| Cierre | Datos de apertura + usuario que cerró, fecha de cierre, monto final, monto esperado y diferencia |

También existe un endpoint manual para reenviar/notificar el estado actual de una caja:

```http
POST /api/v1/cashboxes/<cashbox_uuid>/notify-email/
Authorization: Bearer <access_token>
```

Permisos: `ADMIN`, `OWNER`, el usuario que abrió la caja o el usuario que la cerró.

Ejemplo de preparación local con el tenant de prueba:

```bash
curl -X PATCH http://localhost:8000/api/v1/tenant/config/ \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"notification_email": "owner@postas.test", "cashbox_email_notifications_enabled": true}'
```

Con `EMAIL_PROVIDER=django` y `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`, al abrir/cerrar caja el email se imprime en la consola donde corre `runserver`.

---

## 🏪 Módulo de Proveedores

Permite gestionar proveedores y asociarlos a productos con historial de precios.

### Modelos

**`Supplier`** — Proveedor del tenant.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `uuid` | UUID (PK) | Identificador único |
| `tenant_id` | UUID | Tenant al que pertenece |
| `name` | CharField | Nombre del proveedor |
| `phone` | CharField | Teléfono (opcional) |
| `email` | EmailField | Email (opcional) |
| `address` | CharField | Dirección (opcional) |
| `notes` | TextField | Notas internas (opcional) |
| `active` | BooleanField | Soft delete |

**`ProductSupplier`** — Relación histórica entre producto y proveedor.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `uuid` | UUID (PK) | Identificador único |
| `product` | FK → Product | Producto relacionado |
| `supplier` | FK → Supplier | Proveedor relacionado |
| `price` | Decimal | Precio de compra al proveedor (opcional) |
| `is_current` | BooleanField | Si es la relación activa actualmente |
| `since` | DateField | Fecha de inicio (auto) |
| `until` | DateField | Fecha de fin (se llena al desactivar) |

> No se elimina el historial: al cambiar de proveedor se setea `is_current=False` y `until=hoy`, y se crea un nuevo registro.

### Relación con Product

Cada `Product` expone una property `current_suppliers` y el serializer incluye el campo `current_suppliers` con la lista de proveedores activos:

```json
{
  "uuid": "...",
  "name": "Coca Cola 500ml",
  "current_suppliers": [
    { "uuid": "...", "name": "Distribuidora Norte" }
  ]
}
```

### Cambiar proveedor activo

```bash
POST /api/v1/product-suppliers/switch/
Authorization: Bearer <token>

{
  "product_uuid": "<uuid-del-producto>",
  "supplier_uuid": "<uuid-del-nuevo-proveedor>",
  "price": "850.00"
}
```

Desactiva todos los proveedores activos del producto y asigna el nuevo. La lógica vive en `apps/suppliers/services.py`.

---

## ☁️ Módulo de Imágenes (Cloudflare R2)

Permite subir, actualizar, obtener y eliminar imágenes desde un bucket de Cloudflare R2 (compatible con S3).

### Configuración del backend

Agregá las siguientes variables al `.env`:

```env
R2_BUCKET_NAME=nombre-de-tu-bucket
R2_ACCESS_KEY_ID=tu-access-key-id
R2_SECRET_ACCESS_KEY=tu-secret-access-key
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
R2_PUBLIC_URL=https://pub-<hash>.r2.dev
R2_REGION=auto
```

> `R2_PUBLIC_URL` es la URL pública del bucket (dominio personalizado o la URL `pub-*.r2.dev` que provee Cloudflare). Es el prefijo que se antepone a cada `key` para armar la URL final de la imagen.

Instalá la dependencia si no la tenés:

```bash
pip install -r requirements.txt
```

---

### Endpoints — Frontend

#### Organización por tenant

Todas las imágenes se almacenan bajo el prefijo `<tenant_id>/` dentro del bucket, de modo que cada tenant tiene su propio espacio aislado:

```
bucket/
  00000000-0000-0000-0000-000000000001/
    images/
      20250506_130000_foto.jpg
    banners/
      20250506_140000_banner.png
  otro-tenant-uuid/
    images/
      ...
```

Los endpoints autenticados aplican esto de forma automática. El `key` que devuelve la API ya incluye el `tenant_id` como prefijo, por ejemplo: `00000000-0000-0000-0000-000000000001/images/20250506_130000_foto.jpg`.

---

#### Endpoints públicos (sin autenticación)

> Usar estos para mostrar imágenes en el panel de administración sin necesidad de token.

**Listar imágenes**

```
GET /api/v1/cloud/public/images/?tenant_id=<uuid>
```

Query params:

| Param | Requerido | Default | Descripción |
|-------|-----------|---------|-------------|
| `tenant_id` | ✅ | — | UUID del tenant |
| `prefix` | ❌ | — | Subcarpeta dentro del tenant (ej: `images/`) |
| `search` | ❌ | — | Filtra por nombre de archivo |
| `max_keys` | ❌ | `200` | Máx. imágenes a devolver (tope: 1000) |
| `token` | ❌ | — | Token de paginación para la siguiente página |

Respuesta:

```json
{
  "images": [
    {
      "key": "00000000-0000-0000-0000-000000000001/images/20250506_123000_foto.jpg",
      "url": "https://pub-xxx.r2.dev/00000000-0000-0000-0000-000000000001/images/20250506_123000_foto.jpg",
      "size": 84320,
      "last_modified": "2025-05-06T12:30:00+00:00",
      "filename": "20250506_123000_foto.jpg"
    }
  ],
  "count": 1,
  "is_truncated": false,
  "next_token": null
}
```

**Obtener una imagen específica**

```
GET /api/v1/cloud/public/images/<key>/
```

Ejemplo:

```
GET /api/v1/cloud/public/images/00000000-0000-0000-0000-000000000001/images/20250506_123000_foto.jpg/
```

Respuesta:

```json
{
  "success": true,
  "key": "00000000-0000-0000-0000-000000000001/images/20250506_123000_foto.jpg",
  "url": "https://pub-xxx.r2.dev/00000000-0000-0000-0000-000000000001/images/20250506_123000_foto.jpg"
}
```

---

#### Endpoints autenticados (requieren JWT)

> Cualquier usuario logueado (EMPLOYEE, ADMIN u OWNER) puede operar.

Todos los requests autenticados requieren el header:

```
Authorization: Bearer <access_token>
```

**Listar imágenes**

```
GET /api/v1/cloud/images/
```

Mismos query params que el endpoint público, excepto que `tenant_id` no es necesario (se toma del token automáticamente). El parámetro `prefix` es relativo al tenant (ej: `prefix=images/` lista `<tenant_id>/images/`).

**Subir imagen**

```
POST /api/v1/cloud/images/
Content-Type: multipart/form-data
```

| Campo | Requerido | Descripción |
|-------|-----------|-------------|
| `image` | ✅ | Archivo de imagen (`.jpg`, `.jpeg`, `.png`, `.webp`) |
| `folder` | ❌ | Carpeta destino dentro del bucket (default: `images`) |

Respuesta `201`:

```json
{
  "success": true,
  "key": "00000000-0000-0000-0000-000000000001/images/20250506_130000_foto.jpg",
  "url": "https://pub-xxx.r2.dev/00000000-0000-0000-0000-000000000001/images/20250506_130000_foto.jpg"
}
```

**Obtener metadata de una imagen**

```
GET /api/v1/cloud/images/<key>/
```

**Reemplazar una imagen** (elimina la anterior y sube la nueva)

```
PUT /api/v1/cloud/images/<key>/
Content-Type: multipart/form-data
```

| Campo | Requerido | Descripción |
|-------|-----------|-------------|
| `image` | ✅ | Nuevo archivo |
| `folder` | ❌ | Carpeta destino (default: la misma carpeta del `key` original) |

Respuesta:

```json
{
  "success": true,
  "key": "00000000-0000-0000-0000-000000000001/images/20250506_140000_foto_nueva.jpg",
  "url": "https://pub-xxx.r2.dev/00000000-0000-0000-0000-000000000001/images/20250506_140000_foto_nueva.jpg"
}
```

**Eliminar imagen**

```
DELETE /api/v1/cloud/images/
```

Body JSON:

```json
{ "key": "00000000-0000-0000-0000-000000000001/images/20250506_123000_foto.jpg" }
```

O como query param:

```
DELETE /api/v1/cloud/images/?key=00000000-0000-0000-0000-000000000001/images/20250506_123000_foto.jpg
```

Respuesta:

```json
{ "deleted": "images/20250506_123000_foto.jpg" }
```

---

#### Health check (ADMIN / OWNER)

Prueba la conectividad con el bucket haciendo un ciclo upload → read → delete sobre un archivo de prueba.

```
GET /api/v1/cloud/health/
Authorization: Bearer <token>
```

Respuesta:

```json
{
  "ok": true,
  "steps": [
    { "step": "connect", "ok": true, "ms": 12, "bucket": "mi-bucket" },
    { "step": "upload",  "ok": true, "ms": 230 },
    { "step": "read",    "ok": true, "ms": 180 },
    { "step": "delete",  "ok": true, "ms": 150 }
  ]
}
```

---

### Notas para el frontend

- El campo `key` es el identificador interno del archivo en el bucket. Guardarlo si después se necesita actualizar o eliminar la imagen.
- Las extensiones permitidas son: `.jpg`, `.jpeg`, `.png`.
- Tamaño máximo por defecto: **5 MB**.

---
