# Datos de demostración de Postas y Platform

El lanzador `scripts/seed_demo.py` carga ocho comercios con identidades estables, un año de ventas y suscripciones. Usa un comando Django y un proceso SQLAlchemy independientes; no requiere levantar las APIs. Ejecutar sobre bases de desarrollo/preproducción con las migraciones ya aplicadas.

## Ejecución en PowerShell

```powershell
# Usar los virtualenv de ambos repos y configurar sus respectivos .env.
# DATABASE_URL se toma del .env de cada repo; una DATABASE_URL global no se comparte.
# Overrides opcionales, siempre distintos y con rutas absolutas para SQLite:
$env:POSTAS_DEMO_DATABASE_URL='sqlite:///D:/datos/postas_demo.sqlite3'
$env:PLATFORM_DEMO_DATABASE_URL='sqlite:///D:/datos/platform_demo.db'
# Aplicar las migraciones Django/Alembic a esas bases antes del seed.

& D:\benja\proyectos\postas_api\env\Scripts\python.exe D:\benja\proyectos\postas_api\scripts\seed_demo.py --dry-run

# Definir DEMO_SEED_PASSWORD (mínimo 12 caracteres) mediante la configuración local.
# No guardar contraseñas en manifiestos ni argumentos de línea de comandos.
& D:\benja\proyectos\postas_api\env\Scripts\python.exe D:\benja\proyectos\postas_api\scripts\seed_demo.py
```

El modo normal escribe en ambas bases y sube imágenes a R2. `--dry-run` consulta ambas bases, descarga/verifica imágenes y consulta R2, pero no escribe en bases ni R2 y no persiste el manifiesto. Necesita conexión a internet y configuración R2 incluso en dry-run. Las pruebas automatizadas reemplazan R2 y la red por mocks.

Opciones: `--platform-dir`, `--postas-python`, `--platform-python`, `--products-csv`, `--manifest`, `--seed`, `--as-of` (ISO con zona horaria), `--tenants 1,3`. Los defaults usan el repo hermano `postas_platform_api`, 8 tenants, semilla 20261002 e instante actual en la primera ejecución. El período retrocede un año calendario; 29 de febrero se ajusta a 28.

El archivo `.demo-seed/manifest.json` está ignorado por Git. Conserva fecha, catálogo, identificadores, fingerprint y eventos de consumo; nunca contraseñas. Preservarlo para reanudar. No cambiar parámetros al reintentar: el seed detecta discrepancias y se detiene. No ejecutar dos lanzadores simultáneamente contra el mismo dataset.

## Carga Railway de Benjamin Sosa (development)

Las bases privadas de Railway no se alcanzan desde la máquina local. `scripts/build_railway_seed_bundle.py` prepara bajo `.demo-seed/` un contexto Docker sin `.env`, bases locales, tests ni credenciales para un servicio runner temporal. El runner debe recibir referencias de variables a `DB Tenant Dev.DATABASE_URL` y `DB Platform.DATABASE_URL`, `SECRET_KEY`, las variables R2 y `DEMO_SEED_PASSWORD` (contraseña aleatoria de al menos 12 caracteres). No pasar secretos por argumentos ni escribirlos en el manifiesto.

Para esta carga se vaciaron una sola vez 22 tablas operativas Postas y 13 Platform, sin backup según lo autorizado, preservando migraciones y metadatos de permisos. La limpieza se hizo después de verificar el bucket y las 100 imágenes públicamente. La herramienta temporal de borrado no forma parte del código entregable para evitar su reutilización accidental. El seed normal, por sí mismo, nunca borra datos previos.

La carga de 2026-10-03 usó `--as-of 2026-10-03T14:39:19+00:00`. El servicio `postas-demo-seed-runner` queda sin deployment al finalizar; su variable privada `DEMO_SEED_PASSWORD` permanece allí para consultar la contraseña de los 24 usuarios demo desde Railway. Para reintentar con el mismo dataset, recrear el manifiesto con ese mismo `--as-of`; no volver a limpiar una base ya poblada.

## Perfiles

| Sufijo UUID | Comercio | Plan | Productos | Ventas |
|---|---|---|---:|---|
| 01 | Kiko Store | Business + IA | 100 | 10.000 |
| 02 | Kiosco Pepito | Starter | 100 | 80 % del cupo mensual |
| 03 | FreeMarket | Free | 20 | 80 % del cupo mensual |
| 04 | Almacén Central | Business | 100 | 10.000 |
| 05 | Mercado Personalizado | Custom | 100 | 10.000, máximo 1.000/mes |
| 06 | Comercio Demo 1 | Demo 1 (`test`) | 10 | 80 % de 10/mes |
| 07 | Comercio Demo 2 | Demo 2 | 10 | 80 % de 10/mes |
| 08 | Comercio Demo 3 | Demo 3 | 10 | 80 % de 10/mes |

UUID completo: `00000000-0000-0000-0000-000000000001` a `...0008`. Platform guarda estos UUID en billing y no tiene tabla de comercios.

Tres usuarios por comercio: `owner`, `admin`, `employee`, correo `rol.<número>@example.invalid`; sin permisos de superusuario. Cada tenant tiene dos terminales, con una sesión abierta en Free/Demo y dos en los demás. Los proveedores son 3/5/10/2 según Free/Starter/Business-Custom/Demo. Ventas con CASH, CARD, TRANSFER, MIXED y cancelaciones; cuotas agrupadas por mes UTC y actividad por horario de Argentina.

Stock final positivo. La auditoría de creación registra inventario inicial calculado como unidades vendidas netas más stock final; no existe una tabla de reposiciones. Los precios son simulados en ARS, no cotizaciones comerciales.

El catálogo de Platform conserva Free, Starter, Business y Business + IA; configura Custom privado a ARS 49.999, 100 productos, 1.000 ventas/mes, 2 cajas, 10 proveedores, 3 usuarios, 30 emails/mes y todas las features salvo IA. Test conserva su código técnico, se llama Demo 1 y junto a Demo 2/3 es privado/gratuito: 10 productos, 10 ventas/mes, 1 caja, 2 proveedores, 3 usuarios, 2 emails/mes, todas las features salvo IA. El cambio de catálogo afecta también suscripciones existentes a Test/Custom al ejecutar el seed de catálogo.

Pagos manuales simulados por mes cubren el intervalo y el período vigente, solo para planes pagos. Una ventana anual puede intersectar 13 meses. Las suscripciones cubren `as_of`; un dataset histórico no extiende artificialmente la suscripción hasta hoy.

## Imágenes y efectos externos

Los 100 códigos del CSV tienen nombres/categorías curados en `scripts/demo_catalog.py`. Las descripciones son resúmenes comerciales, no declaraciones de ingredientes/alérgenos. Procedencia y atribución se conservan en el manifiesto: Open Food Facts y sus colaboradores (datos ODbL, imágenes CC BY-SA).

R2 requiere `R2_BUCKET_NAME`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`, `R2_PUBLIC_URL` HTTPS público. El prefijo exclusivo es `demo/production-demo-v1/products/`; las claves estables evitan duplicados. Se comprueba el contenido público contra su hash. Una imagen faltante detiene la carga; no se usan placeholders ni imágenes de otros productos.

Solo se realizan lecturas de Open Food Facts y lecturas/escrituras de imágenes R2. No hay correos reales, solicitudes de IA, cobros, facturación ARCA ni llamadas a Mercado Pago. Los emails y extracciones son historiales simulados con estados terminales; extracción solo en Business + IA. Configuración de notificaciones/facturación automáticas desactivada. OAuth, credenciales, webhooks, reservas activas y outboxes quedan fuera.

## Recuperación y validación

Cada fase usa transacciones locales, sin transacción distribuida. Si falla después de subir imágenes o completar una base, reejecutar el mismo comando y manifiesto: reutiliza imágenes, tenants y pagos propios sin reiniciar stock ni contraseñas. Los consumos solo se incrementan una vez. No borra datos ajenos ni adopta tenants preexistentes, incluso si coinciden sus UUID con los seeds viejos. Una colisión requiere elegir una base aislada.

Los marcadores de propiedad están en AuditLog (Postas) y en un UsageEvent de cantidad cero `__seed_manifest__` (Platform), sin consumo ni pago ficticio. La verificación final muestra conteos y valida referencias. Mantener el manifiesto local privado porque contiene datos del dataset.

```powershell
& D:\benja\proyectos\postas_api\env\Scripts\python.exe -m unittest discover -s D:\benja\proyectos\postas_api\scripts -p test_demo_tools.py
& D:\benja\proyectos\postas_api\env\Scripts\python.exe D:\benja\proyectos\postas_api\manage.py test apps.users.test_seed_demo
# En Platform, con PYTHONPATH apuntando a ese repo:
& D:\benja\proyectos\postas_platform_api\env\Scripts\python.exe -m pytest D:\benja\proyectos\postas_platform_api\tests\test_demo_seed.py D:\benja\proyectos\postas_platform_api\tests\test_billing.py -q

# Integración completa con migraciones, ocho tenants y bases temporales; sin red:
$env:RUN_DEMO_INTEGRATION='1'
& D:\benja\proyectos\postas_api\env\Scripts\python.exe D:\benja\proyectos\postas_api\scripts\test_demo_integration.py -v

# Comprobar únicamente las 100 imágenes de origen (lecturas, sin R2):
& D:\benja\proyectos\postas_api\env\Scripts\python.exe D:\benja\proyectos\postas_api\scripts\demo_images.py
```
