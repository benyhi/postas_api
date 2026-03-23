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

---
