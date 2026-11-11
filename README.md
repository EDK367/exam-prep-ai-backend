# Exam Prep AI - Backend & Documentacion del Sistema

Plataforma integral de preparacion de examenes impulsada por Inteligencia Artificial con arquitectura RAG (Retrieval-Augmented Generation), procesamiento asincrono de documentos PDF y evaluacion interactiva.

---

## Tabla de Contenidos

- [Descripcion General](#descripcion-general)
- [Arquitectura y Tecnologias](#arquitectura-y-tecnologias)
- [Estructura del Proyecto](#estructura-del-proyecto)
- [Requisitos Previos](#requisitos-previos)
- [Puesta en Marcha del Backend](#puesta-en-marcha-del-backend)
  - [Metodo 1: Docker Compose (Recomendado)](#metodo-1-docker-compose-recomendado)
  - [Metodo 2: Entorno Local (Manual)](#metodo-2-entorno-local-manual)
- [Puesta en Marcha del Frontend](#puesta-en-marcha-del-frontend)
- [Ejecucion de Pruebas Unitarias](#ejecucion-de-pruebas-unitarias)
- [Verificacion y Preparacion para Despliegue](#verificacion-y-preparacion-para-despliegue)
- [Guia de Despliegue en Servicios Gratuitos (Free Tier)](#guia-de-despliegue-en-servicios-gratuitos-free-tier)
  - [Arquitectura Recomendada Gratuita](#arquitectura-recomendada-gratuita)
  - [Paso a Paso de Despliegue Gratuito](#paso-a-paso-de-despliegue-gratuito)

---

## Descripcion General

Exam Prep AI permite a los estudiantes cargar material de estudio (archivos PDF), procesar y vectorizar automaticamente el contenido mediante modelos de embedding, y generar cuestionarios y simulaciones de examen personalizadas con retroalimentacion inmediata.

El sistema esta dividido en dos componentes dentro del repositorio principal (`exam-prep-ai`):
1. **exam-prep-ai-backend**: API REST asincrona con FastAPI, pipeline de ingestion de documentos, motor de busqueda vectorial y tareas en segundo plano con Celery.
2. **exam-prep-ai-fronted**: Aplicacion web interactiva basada en Vue 3, Vite, Vuetify y Pinia.

---

## Arquitectura y Tecnologias

### Backend
- **Lenguaje:** Python 3.12+
- **Framework API:** FastAPI con validacion mediante Pydantic v2
- **Capa de Persistencia:** PostgreSQL 16 con extension `pgvector` y SQLAlchemy 2.0 (motor asincrono con `asyncpg`)
- **Migraciones:** Alembic
- **Procesamiento Asincrono:** Celery 5.x respaldado por Redis 7
- **Monitorizacion de Tareas:** Flower
- **Autenticacion y Archivos:** Supabase Auth (JWT) y Supabase Storage
- **Inteligencia Artificial:** OpenAI API / OpenRouter, embeddings vectoriales y division semantica de texto (LangChain Splitters)
- **Extraccion de Documentos:** `pdfplumber`, `pypdf`, `pytesseract` y `pdf2image`

### Frontend
- **Framework:** Vue 3 (Composition API)
- **Herramienta de Compilacion:** Vite
- **Tipado:** TypeScript
- **Libreria de Componentes:** Vuetify 3
- **Gestion de Estado:** Pinia
- **Enrutamiento:** Vue Router
- **Cliente HTTP y SDKs:** Axios, Supabase JS Client

---

## Estructura del Proyecto

```text
exam-prep-ai/
├── exam-prep-ai-backend/           # Servicio Backend (FastAPI + Celery)
│   ├── app/
│   │   ├── api/                    # Endpoints HTTP y dependencias de autenticacion
│   │   ├── core/                   # Configuracion, seguridad y middleware
│   │   ├── db/                     # Sesiones asincronas y modelos base SQLAlchemy
│   │   ├── modules/                # Modulos de negocio: ai, billing, documents, users, tests
│   │   └── workers/                # Definicion de tareas en segundo plano (Celery)
│   ├── infra/
│   │   └── docker/                 # Dockerfiles para API y Workers
│   ├── migrations/                 # Migraciones de base de datos con Alembic
│   ├── tests/                      # Suite de pruebas unitarias y de integracion
│   ├── docker-compose.yml          # Orquestacion para entorno de desarrollo
│   ├── docker-compose.prod.yaml    # Orquestacion para entorno de produccion
│   ├── Dockerfile                  # Dockerfile principal para despliegue en la nube
│   └── pyproject.toml              # Definicion de dependencias y empaquetado Python
│
└── exam-prep-ai-fronted/           # Aplicacion Frontend (Vue 3 + Vite)
    ├── src/
    │   ├── components/             # Componentes reutilizables
    │   ├── layouts/                # Plantillas de diseño (Auth, Default)
    │   ├── pages/                  # Vistas principales (Exams, Dashboard, Files)
    │   ├── stores/                 # Stores de Pinia (auth, documents, exams)
    │   └── services/               # Clientes API y comunicacion HTTP
    ├── package.json                # Dependencias de Node.js
    └── vite.config.mts             # Configuracion de Vite y plugins
```

---

## Requisitos Previos

Dependiendo del metodo de ejecucion elegido:

### Opcion Contenedores (Recomendada):
- Docker Engine 24.0 o superior
- Docker Compose v2.20 o superior

### Opcion Ejecucion Local Nativa:
- Python 3.12+ (y gestor de paquetes `uv` o `pip`)
- Node.js 20+ y gestor de paquetes `pnpm`
- Servidor PostgreSQL 16 con extension `pgvector` habilitada
- Servidor Redis 7+
- Dependencias del sistema operativo para procesamiento de PDFs e imagenes:
  - Debian/Ubuntu: `sudo apt-get install libpq-dev poppler-utils tesseract-ocr libmagic1 build-essential`

---

## Puesta en Marcha del Backend

### Paso Previo: Configuracion de Variables de Entorno

Copie la plantilla de variables de entorno y configure los valores correspondientes:

```bash
cd exam-prep-ai-backend
cp .env.example .env
```

Variables clave requeridas:
- `SECRET_KEY`: Cadena aleatoria de minimo 32 caracteres para seguridad de sesiones.
- `DATABASE_URL`: Cadena de conexion asincrona a PostgreSQL (`postgresql+asyncpg://user:pass@host:5432/dbname`).
- `CELERY_BROKER_URL` y `CELERY_RESULT_BACKEND`: URL de conexion a Redis.
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `SUPABASE_JWT_SECRET`: Credenciales del proyecto Supabase.
- `OPENROUTER_API_KEY`: Clave de API para generacion de texto y embeddings.
- `ALLOWED_ORIGINS`: Lista de origenes autorizados en formato JSON (por ejemplo: `["http://localhost:3000","http://localhost:5173"]`).

---

### Metodo 1: Docker Compose (Recomendado)

Levanta de manera automatica el API, el Worker de Celery, PostgreSQL con pgvector, Redis y la interfaz de Flower.

1. Construir las imagenes e iniciar todos los servicios:
```bash
docker compose up --build -d
```

2. Aplicar las migraciones de base de datos dentro del contenedor de API:
```bash
docker compose exec api alembic upgrade head
```

3. Verificar el estado de los contenedores:
```bash
docker compose ps
```

4. Consultar los registros en tiempo real:
```bash
docker compose logs -f api
docker compose logs -f worker
```

Servicios expuestos:
- **API FastAPI y Swagger UI:** `http://localhost:8000/docs`
- **Panel de Monitorizacion Flower:** `http://localhost:5555`
- **Base de Datos PostgreSQL:** Puerto `5432`
- **Servidor Redis:** Puerto `6379`

Para detener los servicios:
```bash
docker compose down
```

---

### Metodo 2: Entorno Local (Manual)

Si cuenta con instancias locales de PostgreSQL (con pgvector) y Redis activas:

1. Crear y activar un entorno virtual de Python 3.12:
```bash
cd exam-prep-ai-backend

# Utilizando uv (recomendado por velocidad)
uv venv --python 3.12 .venv
source .venv/bin/activate

# O utilizando venv tradicional de Python
python3.12 -m venv .venv
source .venv/bin/activate
```

2. Instalar dependencias del proyecto:
```bash
# Con uv
uv pip install -e ".[dev]"

# O con pip
pip install -e ".[dev]"
```

3. Ejecutar las migraciones de base de datos:
```bash
alembic upgrade head
```

4. Iniciar el servidor API de FastAPI:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

5. En una terminal separada (con el mismo entorno virtual activado), iniciar el Worker de Celery:
```bash
celery -A app.workers.celery_app worker -Q documents,ai,notifications -c 4 -l INFO
```

---

## Puesta en Marcha del Frontend

El frontend se encuentra en la carpeta `exam-prep-ai-fronted`, paralela al backend.

1. Navegar a la carpeta del frontend:
```bash
cd ../exam-prep-ai-fronted
```

2. Configurar las variables de entorno:
```bash
cp .env.example .env
```

Asegurese de que `.env` contenga:
```env
VITE_API_URL=http://localhost:8000/api/v1
BASE_URL=http://localhost:5173
VITE_APP_NAME=Exam Prep AI
VITE_SUPABASE_URL=https://<tu-proyecto>.supabase.co
VITE_SUPABASE_ANON_KEY=<tu-supabase-anon-key>
```

3. Instalar las dependencias de Node.js con `pnpm`:
```bash
pnpm install
```

4. Iniciar el servidor de desarrollo:
```bash
pnpm dev
```

El servidor web estara disponible en `http://localhost:5173` (o el puerto indicado en la consola).

5. Comandos adicionales del Frontend:
```bash
# Verificacion estatica de tipos con TypeScript
pnpm run type-check

# Compilar para produccion
pnpm run build

# Previsualizar la compilacion de produccion localmente
pnpm run preview

# Ejecutar el linter
pnpm run lint
```

---

## Ejecucion de Pruebas Unitarias

El backend incluye una suite de pruebas automatizadas con `pytest` y base de datos asincrona en memoria SQLite (`aiosqlite`).

Para ejecutar todas las pruebas:
```bash
cd exam-prep-ai-backend
source .venv/bin/activate
pytest tests/ -v
```

---

## Verificacion y Preparacion para Despliegue

Se ha auditado el codigo y la infraestructura con las siguientes validaciones y correcciones efectuadas:

1. **Dockerfiles de API y Workers validados:**
   - Se optimizaron las capas de compilacion en `infra/docker/Dockerfile.api` y `infra/docker/Dockerfile.worker`, eliminando redundancias en las instrucciones `COPY` y asegurando la instalacion adecuada de dependencias de sistema (`libmagic1`, `poppler-utils`, `tesseract-ocr`).
   - Se añadio el punto de entrada predeterminado `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]` y `EXPOSE 8000` para garantizar compatibilidad con plataformas PaaS en la nube.
   - Se creo un `Dockerfile` en la raiz del backend para plataformas que exigen el manifiesto en el directorio raiz.

2. **Orquestacion de Produccion Lista:**
   - Se creo `docker-compose.prod.yaml` con politicas de reinicio automatico (`restart: unless-stopped`), volumenes de datos persistentes, comprobaciones de salud (`healthchecks`) y ejecucion de Uvicorn con multiples procesos trabajadores (4 workers).

3. **Frontend Verificado:**
   - Se integro la dependencia de orquestacion de scripts `npm-run-all2` en `exam-prep-ai-fronted`.
   - Se comprobo que la compilacion de TypeScript (`vue-tsc`) y el empaquetado de produccion con Vite (`pnpm build`) se ejecutan sin errores y generan la carpeta `dist/` lista para ser servida.

4. **Variables de Produccion:**
   - En produccion debe actualizar `ALLOWED_ORIGINS` en el backend para incluir el dominio real donde este desplegado el frontend (ejemplo: `["https://mi-frontend.vercel.app"]`).

---

## Guia de Despliegue en Servicios Gratuitos (Free Tier)

Este proyecto requiere tres capas funcionales:
1. Frontend estatico (SPA).
2. Base de datos PostgreSQL con extension `pgvector` y almacenamiento/autenticacion Supabase.
3. API FastAPI y Worker de tareas en segundo plano con Redis.

A continuacion se presentan las opciones recomendadas para desplegar la aplicacion sin costo alguno.

---

### Arquitectura Recomendada Gratuita

| Componente | Servicio Gratuito Recomendado | Alternativas Gratuitas | Caracteristicas del Plan Free |
| :--- | :--- | :--- | :--- |
| **Frontend** | **Vercel** | Netlify, Cloudflare Pages | Despliegue continuo desde GitHub, HTTPS automatico, CDN global sin limite de tiempo. |
| **Base de Datos** | **Supabase** | Neon DB | PostgreSQL 16 con `pgvector` nativo preinstalado, 500 MB de almacenamiento, Auth y Storage incluidos. |
| **Redis / Broker** | **Upstash Redis** | Redis Cloud | Redis Serverless gratuito (hasta 10,000 comandos diarios), ideal para Celery en bajo y mediano volumen. |
| **API Backend** | **Render (Web Service)** | Koyeb (Eco Tier), Hugging Face Spaces | Despliegue directo de contenedor Docker o repositorio Python. Entra en reposo tras inactividad. |
| **Worker Celery** | **Koyeb / VPS Always Free** | Railway (credito mensual) | Ejecucion continua del contenedor Celery. |

---

### Opcion A: Despliegue por Servicios Gestionados (Recomendada)

#### 1. Base de Datos, Autenticacion y Almacenamiento (Supabase - 100% Free)
1. Cree una cuenta en [Supabase](https://supabase.com).
2. Cree un nuevo proyecto. Anote la URL del proyecto, la Anon Key, la Service Role Key y el JWT Secret (disponibles en Project Settings > API).
3. En la seccion **Database > Extensions**, verifique que este habilitada la extension `vector`.
4. En la seccion **Storage**, cree un bucket publico o privado llamado `documents`.
5. Obtenga la URL de conexion a la base de datos (con driver asincrono: `postgresql+asyncpg://postgres:[PASSWORD]@[HOST]:5432/postgres`).

#### 2. Redis Cloud o Upstash (Free Tier - 30 MB)
El sistema ha sido especialmente optimizado para bases de datos Redis gratuitas con limite estricto de memoria (30 MB):
- **Compresion automatica Gzip:** Tareas y resultados se comprimen reduciendo el consumo de memoria en un 70%.
- **Expiracion agresiva de resultados:** Las tareas se eliminan del backend de resultados en 15 minutos (900s) evitando acumulacion.
- **Prefijos en Base de Datos 0:** Permite que Broker, Resultados y Cache compartan la base de datos 0 (los planes gratuitos no admiten multiples DBs) sin colision de llaves (`exam_prep_broker:`, `exam_prep_result:`, `exam_prep_cache:`).
- **TTL de Cache a 15 minutos:** Impide el desbordamiento de memoria por consultas repetidas.

Si utiliza Redis Cloud:
1. Cree su base de datos gratuita de 30 MB en [Redis Cloud](https://redis.io/cloud/).
2. Copie el endpoint de conexion proporcionado (ejemplo: `redis://default:<password>@<host>:<port>`). Nota: no incluya el prefijo `redis-cli -u`.
3. Configure en `.env`:
   - `REDIS_URL=redis://default:<password>@<host>:<port>/0`
   - `CELERY_BROKER_URL=redis://default:<password>@<host>:<port>/0`
   - `CELERY_RESULT_BACKEND=redis://default:<password>@<host>:<port>/0`

#### 3. Frontend (Vercel o Cloudflare Pages - 100% Free)
1. Conecte su cuenta de GitHub en [Vercel](https://vercel.com).
2. Importe el repositorio `exam-prep-ai-fronted`.
3. Configure los parametros del proyecto:
   - **Framework Preset:** Vite
   - **Root Directory:** `./` (o la carpeta del frontend)
   - **Build Command:** `pnpm build`
   - **Output Directory:** `dist`
4. Agregue las variables de entorno en el panel de Vercel:
   - `VITE_API_URL`: URL publica que tendra su backend (ejemplo: `https://exam-prep-api.onrender.com/api/v1`).
   - `VITE_SUPABASE_URL`: URL de su proyecto Supabase.
   - `VITE_SUPABASE_ANON_KEY`: Anon Key publica de Supabase.
5. Presione **Deploy**. La aplicacion quedara activa con certificado SSL gratuito.

#### 4. Backend API (Render - 100% Free Web Service)
1. Cree una cuenta en [Render](https://render.com).
2. Cree un nuevo **Web Service** conectado a su repositorio `exam-prep-ai-backend`.
3. Seleccione el entorno **Docker** (detectara automaticamente el `Dockerfile`).
4. Configure las variables de entorno en el panel de Render:
   - `APP_ENV`: `production`
   - `DEBUG`: `false`
   - `SECRET_KEY`: Una clave aleatoria segura.
   - `DATABASE_URL`: Cadena de conexion asincrona a Supabase.
   - `CELERY_BROKER_URL`: URL de Upstash Redis.
   - `CELERY_RESULT_BACKEND`: URL de Upstash Redis.
   - `SUPABASE_URL`: URL de su proyecto Supabase.
   - `SUPABASE_ANON_KEY`: Anon Key de Supabase.
   - `SUPABASE_SERVICE_KEY`: Service Role Key de Supabase.
   - `SUPABASE_JWT_SECRET`: JWT Secret de Supabase.
   - `SUPABASE_STORAGE_BUCKET`: `documents`
   - `OPENROUTER_API_KEY`: Clave de OpenRouter / OpenAI.
   - `ALLOWED_ORIGINS`: `["https://<su-proyecto-en-vercel>.vercel.app"]`
5. Ejecute las migraciones: En Render, puede abrir una consola de Shell en la instancia y ejecutar `alembic upgrade head`.

---

### Opcion B: Servidor VPS Gratuito Completo (Oracle Cloud Always Free)

Si desea ejecutar el stack completo (FastAPI + Celery Worker + Redis + PostgreSQL + Flower) sin limites de suspension ni division en multiples proveedores:

- **Proveedor:** Oracle Cloud Infrastructure (OCI).
- **Plan:** Always Free Compute (instancia ARM Ampere).
- **Recursos gratuitos de por vida:** Hasta 4 OCPU, 24 GB de memoria RAM y 200 GB de disco NVMe.

**Procedimiento:**
1. Cree una maquina virtual Ubuntu 24.04 ARM Always Free en Oracle Cloud.
2. Instale Docker y Docker Compose en la instancia:
```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2
```
3. Clone su repositorio en el servidor:
```bash
git clone <URL_REPOSITORIO_BACKEND>
cd exam-prep-ai-backend
```
4. Cree y complete el archivo `.env` de produccion.
5. Inicie el stack completo con el compose de produccion:
```bash
docker compose -f docker-compose.prod.yaml up -d --build
```
6. Ejecute las migraciones:
```bash
docker compose -f docker-compose.prod.yaml exec api alembic upgrade head
```
7. Configure el firewall de Oracle Cloud (Security Lists) para permitir el trafico en los puertos 80 y 443, y coloque un certificado SSL con Certbot/Nginx.

---

## Licencia

Este proyecto esta protegido bajo la licencia MIT.
