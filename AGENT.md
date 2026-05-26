# AGENT.md

Guia operativa para agentes que trabajen en este proyecto.

## Proyecto

`postas_api` es un backend Django REST Framework para un sistema POS multi-tenant.

Ruta local principal:

```txt
D:\benja\proyectos\postas_api
```

Usar rutas absolutas en comandos. En este entorno el `cwd` puede caer en `C:\`, y algunos comandos con rutas relativas pueden leer o escribir fuera del repo.

## Stack

- Python 3.14
- Django 6.0
- Django REST Framework
- Simple JWT
- drf-spectacular para OpenAPI
- SQLite local por defecto, configurable por `DATABASE_URL`
- Cloudflare R2/S3 compatible para imagenes

## Comandos seguros

Preferir el Python del virtualenv del repo:

```powershell
& D:\benja\proyectos\postas_api\env\Scripts\python.exe D:\benja\proyectos\postas_api\manage.py check
```

Cuando el comando toque la base local y se ejecute fuera del repo, fijar `DATABASE_URL` absoluto:

```powershell
$env:DATABASE_URL='sqlite:///D:/benja/proyectos/postas_api/db.sqlite3'
& D:\benja\proyectos\postas_api\env\Scripts\python.exe D:\benja\proyectos\postas_api\manage.py migrate
```

Validaciones habituales:

```powershell
& D:\benja\proyectos\postas_api\env\Scripts\python.exe D:\benja\proyectos\postas_api\manage.py check
& D:\benja\proyectos\postas_api\env\Scripts\python.exe D:\benja\proyectos\postas_api\manage.py test apps.cashbox.tests apps.tenants.tests apps.reports.tests
$env:DATABASE_URL='sqlite:///D:/benja/proyectos/postas_api/db.sqlite3'; & D:\benja\proyectos\postas_api\env\Scripts\python.exe D:\benja\proyectos\postas_api\manage.py makemigrations --check --dry-run
```

Regenerar schema OpenAPI:

```powershell
$env:DATABASE_URL='sqlite:///D:/benja/proyectos/postas_api/db.sqlite3'
& D:\benja\proyectos\postas_api\env\Scripts\python.exe D:\benja\proyectos\postas_api\manage.py spectacular --file D:\benja\proyectos\postas_api\schema.yml
```

`drf-spectacular` puede emitir warnings por `APIView` sin serializer explicito. Si el comando termina con exit code 0, el schema se genero.

## Estructura

```txt
config/
  settings.py        Configuracion Django, DRF, JWT, email, R2
  urls.py            Rutas raiz bajo /api/v1/
  asgi.py
  wsgi.py

core/
  middleware/
    tenant.py        Extrae tenant_id desde el JWT antes de DRF auth
  permissions/
    roles.py         IsOwner, IsAdminOrOwner, IsEmployee
  models/
    tenant_model.py  Abstract model con tenant_id y active
  utils/
    audit.py         Helper para crear AuditLog
    dev_email_backend.py
  cloud/
    config.py
    service.py
    urls.py
    views.py         Endpoints de imagenes/R2

apps/
  tenants/           Tenant y TenantConfig
  users/             Usuario custom, auth JWT, reset password
  products/          Categorias y productos
  suppliers/         Proveedores y relacion producto-proveedor
  sales/             Ventas y detalle
  cashbox/           Apertura/cierre de caja
  notifications/     Providers, armado de emails y tracking de costos
  reports/           Reportes de ventas, productos y caja
  audit/             Logs de auditoria
```

Archivos raiz importantes:

```txt
README.md            Documentacion humana
schema.yml           OpenAPI generado
requirements.txt
Dockerfile
docker-compose.yml
.env-example
```

## Multi-tenant

El sistema usa `tenant_id` en el JWT. `core.middleware.tenant.TenantMiddleware` lo extrae del header:

```txt
Authorization: Bearer <access_token>
```

La mayoria de queries deben filtrar por `request.tenant_id`.

`apps.tenants.models.Tenant` existe como entidad base nueva. `TenantConfig` usa `OneToOneField` contra `Tenant` con columna `tenant_id`.

Cuando se agreguen modelos tenant-scoped, revisar si conviene heredar de `TenantModel` o usar FK real a `Tenant`. No mezclar acceso cross-tenant.

## Autenticacion y roles

`apps.users.models.User` es el usuario custom. Roles:

```txt
OWNER
ADMIN
EMPLOYEE
```

Permisos existentes:

```txt
IsOwner
IsAdminOrOwner
IsEmployee
```

Los endpoints de reportes generales son Admin/Owner. El resumen de caja tiene permiso por objeto:

- Admin/Owner ven cualquier caja del tenant.
- Employee puede ver caja abierta del tenant.
- Employee puede ver caja cerrada solo si la abrio o la cerro.

## TenantConfig y notificaciones

`apps.tenants` centraliza la configuracion del tenant.

Endpoint:

```http
GET/PATCH /api/v1/tenant/config/
```

Campos actuales:

```txt
notification_email
cashbox_email_notifications_enabled
```

Al abrir o cerrar caja, `apps.cashbox.views` llama a `send_cashbox_notification_email_safely`. El armado/envio vive en `apps.notifications.cashbox` y el email se envia a `TenantConfig.notification_email`.

Si falta config/email o las notificaciones estan desactivadas, la caja igual se abre/cierra y se audita `CASHBOX_EMAIL_SKIP`.

Si fallan todos los providers, se audita `CASHBOX_EMAIL_FAILED`.

Si envia correctamente, se audita `CASHBOX_EMAIL`.

`apps.notifications.models.EmailDelivery` registra cada intento en `notifications_email_deliveries`, incluyendo provider, estado, destinatarios, external id, error y `estimated_cost_usd`.

Providers:

```txt
resend  -> principal con la libreria oficial resend
django  -> fallback actual via EMAIL_BACKEND
```

Para pruebas locales con el fallback actual:

```env
EMAIL_PROVIDER=django
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

Eso imprime el email en la consola donde corre `runserver`.

Para produccion:

```env
EMAIL_PROVIDER=resend
EMAIL_FALLBACK_PROVIDER=django
EMAIL_PROVIDER_FALLBACK_ENABLED=True
RESEND_API_KEY=<api-key>
RESEND_COST_PER_1000_EMAILS=0.90
DEFAULT_FROM_EMAIL=POSTAS <notificaciones@dominio-verificado.com>
```

Si se usa `django` como provider/fallback SMTP, `EMAIL_USE_TLS` acepta `true`, `True`, `1`, `yes`, `on`.

## Cashbox

Modelo: `apps.cashbox.models.Cashbox`.

Campos clave:

```txt
opened_by
closed_by
opened_at
closed_at
initial_amount
final_amount
expected_amount
difference
status: OPEN/CLOSED
```

Endpoints:

```http
POST /api/v1/cashboxes/open/
POST /api/v1/cashboxes/close/
GET  /api/v1/cashboxes/current/
GET  /api/v1/cashboxes/
GET  /api/v1/cashboxes/<uuid>/
POST /api/v1/cashboxes/<uuid>/notify-email/
```

`close/` calcula:

```txt
expected_amount = initial_amount + total ventas CASH completadas de esa caja
difference = final_amount - expected_amount
```

## Reports

`apps.reports.views` contiene:

```txt
DailySalesReportView
SalesByPaymentReportView
TopProductsReportView
CashboxSummaryReportView
```

`CashboxSummaryReportView` es usado por el dashboard de caja del frontend:

```http
GET /api/v1/reports/cashbox/summary/?cashbox_id=<uuid>
```

No volver a restringir este endpoint globalmente a Admin/Owner sin revisar el dashboard cajero.

## Audit

`core.utils.audit.log_action` crea `AuditLog`.

`AuditLog.action` tiene `max_length=20`. Si se agregan actions nuevas, mantener nombres de 20 caracteres o menos y crear migracion si cambian choices.

Actions relevantes:

```txt
CASHBOX
CASHBOX_EMAIL
CASHBOX_EMAIL_SKIP
CASHBOX_EMAIL_FAILED
```

## Documentacion

Si se agregan o cambian endpoints:

1. Actualizar `README.md`.
2. Regenerar `schema.yml`.
3. Ejecutar `manage.py check`.
4. Correr pruebas enfocadas.

## Git y cambios locales

Puede haber cambios no relacionados en el working tree. No revertirlos sin pedido explicito.

Antes de commitear:

```powershell
git -C D:\benja\proyectos\postas_api status --short
git -C D:\benja\proyectos\postas_api diff --stat
git -C D:\benja\proyectos\postas_api diff --cached --stat
```

Solo commitear cuando el usuario lo pida.
