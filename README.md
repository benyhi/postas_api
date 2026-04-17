# 🚀 Proyecto POSTAS

---

## 📋 Requisitos previos

Antes de comenzar, asegurate de tener instalado:

- Python 3.14.2
- pip
- git
- (Opcional) PostgreSQL u otro motor de base de datos si el proyecto no usa SQLite

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
cp .env.example .env
```

Editá el archivo `.env` con tus configuraciones locales:

```env
SECRET_KEY=tu_clave_secreta_aqui
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Base de datos (solo si no usás SQLite)
DATABASE_URL=postgres://usuario:contraseña@localhost:5432/nombre_db
```

> ⚠️ **Nunca subas el archivo `.env` al repositorio.** Asegurate de que esté en `.gitignore`.

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
   /users
   /products
   /sales
   /cashbox
   /reports
   /audit
   /suppliers
/core
   /middleware
   /permissions
   /models
   /utils
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

Genera datos realistas: 12 categorías, 98 productos (kiosko/almacén), cajas diarias, ventas con detalle y audit logs:

```bash
python manage.py seed_data
```

Opciones:

```bash
python manage.py seed_data --sales 200       # Cantidad de ventas (default: 150)
python manage.py seed_data --days 60          # Distribuir en N días (default: 30)
python manage.py seed_data --tenant-id <uuid> # Tenant específico
```

> ⚠️ Requiere que los usuarios de prueba existan. Ejecutar `create_test_users` primero.

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
| **Categories** | `GET/POST /api/v1/categories/`, `GET/PATCH/DELETE /api/v1/categories/{uuid}/` | CRUD de categorías (ADMIN/OWNER) |
| **Products** | `GET/POST /api/v1/products/`, `GET/PATCH/DELETE /api/v1/products/{uuid}/`, `GET /api/v1/products/search/` | CRUD + búsqueda. Filtros: `category_id`, `low_stock` |
| **Cashbox** | `POST /open/`, `POST /close/`, `GET /current/`, `GET /`, `GET /{uuid}/` | Apertura, cierre y consulta de cajas |
| **Sales** | `GET/POST /api/v1/sales/`, `GET /{uuid}/`, `POST /{uuid}/cancel/` | Ventas con detalle. Filtros: `user_id`, `payment_method`, `from`, `to` |
| **Reports** | `GET daily/`, `GET by-payment/`, `GET top-products/`, `GET cashbox-summary/` | Reportes con filtros de fechas y paginación |
| **Audit** | `GET /api/v1/audit/` | Logs de auditoría. Filtros: `action`, `entity`, `user`, `timestamp` |
| **Suppliers** | `GET/POST /api/v1/suppliers/`, `GET/PATCH/DELETE /api/v1/suppliers/{uuid}/` | CRUD de proveedores (ADMIN/OWNER). DELETE es soft delete |
| **Suppliers** | `GET/POST /api/v1/product-suppliers/`, `GET/PATCH/DELETE /api/v1/product-suppliers/{uuid}/` | Historial de relaciones producto-proveedor. Filtros: `product`, `is_current` |
| **Suppliers** | `POST /api/v1/product-suppliers/switch/` | Cambia el proveedor activo de un producto (desactiva los anteriores) |

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
