# Monitoreo de calidad de agua

Servicio en vivo para una red con **10 puntos de medición** (la salida de la fuente J280, con
el caudalímetro, y 9 puntos de la red; la ubicación es provisional mientras la ASADA define dónde
van, ver `Modelo_calidad_agua`): recibe las lecturas cada 15 minutos,
pronostica cloro, turbidez y pH a 24 h, **avisa antes** de que empiece un evento (próximas 24 h),
detecta eventos de calidad y **fugas** (con el tramo entre sensores donde está la fuga) y abre
alarmas. Los sensores del sistema son los del detector entrenado; si la API de datos manda más
(el simulador manda 21), los demás se ignoran.

```
API de datos de los sensores  ──►  backend (motor + modelos)  ──►  frontend (dashboard en React)
(lecturas cada 15 min)             pronóstico, anticipación,       red de sensores, gráficos,
                                   detector, alarmas, API :8001    avisos, alarmas
```

Los modelos y el código de las variables vienen del proyecto **Modelo_calidad_agua**,
instalado como el paquete `calidad_agua`: el servicio usa exactamente el mismo código
con el que se entrenaron.

## Estructura

```
backend/
  monitoreo/
    config.py          configuración (URL de la API de datos, modelos, modo de pronóstico)
    modelos.py         carga los modelos entrenados y los aplica
    pronostico_lluvia.py  pronóstico de lluvia que necesitan los modelos (archivo u Open-Meteo)
    fuentes_lluvia.py  de dónde sale la lluvia observada: adaptadores (lecturas u Open-Meteo, RNF-009)
    motor.py           recibe lecturas, procesa cada hora cerrada, maneja las alarmas
    cliente_datos.py   consulta la API de datos
    reintentos.py      reintentos con espera creciente para la API de datos y Open-Meteo (RNF-002)
    cursor.py          última hora procesada, en la base de datos: al reiniciar se sigue desde ahí
    alertas.py         avisos por correo y Telegram (alarmas, avisos anticipados, riesgo en 24 h, resumen diario)
    correo.py          envío de los avisos por correo (SMTP) a los destinatarios de cada nivel
    servicio.py        API del servicio (FastAPI, puerto 8001) que además sirve el dashboard
    ejecutar.py        motor en vivo conectado a la API de datos, solo en consola
    verificar.py       comprueba que el motor en vivo da lo mismo que los notebooks
    prediccion.py      POST /predict/contaminacion y /predict/fugas: predicción con lecturas que manda el cliente
    seguridad.py       clave de API, registro de accesos rechazados y HTTPS (TLS 1.2 o más)
    usuarios.py        inicio de sesión, roles, usuarios y bitácora del dashboard (CU-00, CU-07)
    gestion.py         gestión de las alertas: reconocer, atender y cerrar con su resultado (CU-06)
    rendimiento.py     F1 de las alarmas en producción, cada día en MLflow, y eventos no detectados (RNF-003)
    trabajadores.py    /predict en procesos aparte, para atender a varios usuarios a la vez
    base_datos.py      resultados de cada hora también en una base de datos (PostgreSQL/TimescaleDB)
    probar_prediccion.py  prueba de ese endpoint: latencia p95, errores 422 y mismos números
  pruebas/             pruebas unitarias del servicio (pytest)
  carga/locustfile.py  prueba de carga de la API de predicción (Locust, RNF-001)
  requirements.txt
  requirements-dev.txt  lo que hace falta para las pruebas y el estilo
.github/              integración continua en GitHub
frontend/              dashboard en React (Vite + Recharts)
  src/
    Sesion.jsx         inicio de sesión, contraseña temporal y después el dashboard
    App.jsx            páginas: #/general, #/sensor/J224, #/alertas/12, #/usuarios (administrador) y #/cuenta
    estado.js          semáforo y alertas activas ordenadas por severidad y antelación
    componentes/       Encabezado, Tarjetas, Curva, AlertasActivas, VistaGeneral, Anticipacion, Fugas,
                       GraficoRed (y serieRed.js), MapaCalor, DetalleSensor, Graficos, Alarmas,
                       InicioSesion, Cuenta, Usuarios, CorreoAlertas, GestionAlertas
    api.js             consultas periódicas al backend y aviso cuando vence la sesión
    formato.js         etiquetas, norma, tolerancias, formato de números y fechas
    estilos.css        colores (modo claro y oscuro), tipografía y diseño
  index.html           pide la sesión y los primeros datos mientras baja el JavaScript (RNF-001)
  medir-lcp.mjs        LCP del dashboard con red Fast 3G (RNF-001)
registros/             CSV de cada sesión del motor y accesos rechazados (no se versiona)
.env.ejemplo          variables de configuración y secretos; se copia como .env (no se versiona)
secretos/             certificado de HTTPS (no se versiona)
Dockerfile, docker/, docker-compose.yml   el sistema completo en Docker con un solo comando
```

## Con Docker (un solo comando)

En una máquina nueva, solo con [Docker Desktop](https://www.docker.com/products/docker-desktop/)
y [Git](https://git-scm.com/) instalados:

1. Crear una carpeta para el sistema y abrir una terminal en ella.
2. `git clone https://github.com/evproyectos/Modelo_calidad_agua.git`
3. `git clone https://github.com/evproyectos/Monitoreo_calidad_agua.git`
4. `cd Monitoreo_calidad_agua`
5. Si ya hay una API que mande las lecturas de los sensores, crear un archivo `.env` con la línea
   `URL_DATOS_DOCKER=https://...` (ver **De dónde salen las lecturas**, abajo).
6. `docker compose up --build`
7. En otra terminal, en la misma carpeta, crear el administrador del dashboard (pide la
   contraseña dos veces):
   `docker compose exec monitoreo python -m monitoreo.usuarios --crear-admin correo@asada.cr "Nombre Apellido"`
8. Abrir http://127.0.0.1:8001 y entrar con ese correo.

Los dos proyectos tienen que quedar uno al lado del otro, en la misma carpeta, porque la imagen
del servicio usa el paquete `calidad_agua` de `Modelo_calidad_agua`. La primera vez tarda unos
minutos: descarga los modelos (unos 155 MB), instala TensorFlow y compila el dashboard. Las
siguientes, segundos. Lo mismo vale en la PC de desarrollo (`D:\Practica_Profesional`), desde
esta carpeta.

**Los modelos.** `modelos/`, `mlflow.db` y `mlartifacts/` de `Modelo_calidad_agua` no se versionan:
están en un release de GitHub de ese proyecto, el que nombra `Modelo_calidad_agua/artefactos.json`
junto con la huella SHA-256 de cada archivo. El servicio `preparar` descarga lo que falte, comprueba
la huella y termina; lo que ya está en la carpeta (por ejemplo, modelos recién reentrenados en esta
máquina) no lo toca. Si el release no se puede descargar, el servicio no arranca y `preparar` dice
por qué (sin la historia de MLflow sí arranca). Cómo publicar un release nuevo después de reentrenar:
`Modelo_calidad_agua/README.md`, **Publicar los modelos**.

| Servicio | Qué hace | Dirección |
|---|---|---|
| `preparar` | descarga los modelos y la historia de MLflow si faltan, y termina | — |
| `monitoreo` | servicio con el dashboard, que guarda los resultados de cada hora también en la base de datos | http://127.0.0.1:8001 |
| `db` | PostgreSQL 16 con TimescaleDB: tablas `pronosticos`, `deteccion`, `alarmas`, `anticipacion` y `fugas` (las que tienen fecha, como hipertablas), y `usuarios`, `sesiones`, `bitacora`, `notificaciones`, `alertas` y `alertas_historial` del dashboard | puerto 5432 dentro de Docker |
| `mlflow` | los experimentos de los notebooks (`Modelo_calidad_agua/mlflow.db`) | http://127.0.0.1:5000 |
| `datos` | solo con el perfil `simulador`: API de datos con el dataset del simulador (`Simulador_sensor/tiempo_real`) | http://127.0.0.1:8000 |
| `emisor` | solo con el perfil `simulador`: manda las lecturas de la prueba como si fueran los sensores (31 días de precarga y después 1 h simulada por segundo; `VELOCIDAD=4` en el `.env` lo acelera) | — |
| `mailpit` | solo con el perfil `correo`: servidor de correo de prueba que recibe los correos de las alertas sin mandarlos a nadie y los muestra en una página (ver **Alertas por correo**) | http://127.0.0.1:8025 |

**De dónde salen las lecturas.** En Docker, el servicio las pide a la API que diga
`URL_DATOS_DOCKER` en el `.env` (`URL_DATOS` es la del servicio sin Docker, que suele ser
`127.0.0.1` y dentro de un contenedor no sirve). Sin `URL_DATOS_DOCKER`, usa la API del simulador
(servicio `datos`), que necesita el proyecto `Simulador_sensor` en la misma carpeta, con su
dataset en `datos/dtown/final`, y el perfil `simulador`: la línea `COMPOSE_PROFILES=simulador` en
el `.env` (los perfiles se suman con comas: `COMPOSE_PROFILES=simulador,correo`). Sin ninguna de
las dos, el dashboard abre igual y avisa que no hay conexión con la API de datos.

Los secretos van en el `.env` de esta carpeta, igual que sin Docker. Si el `.env` tiene
`CERTIFICADO_TLS` y `CLAVE_TLS`, el contenedor usa los archivos de `secretos/` y el dashboard queda
en **https**://127.0.0.1:8001. `docker compose down` lo apaga; `docker compose down -v` borra
también la base de datos (con los usuarios del dashboard).

## Instalación

Desde `backend/`:

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install -e "..\..\Modelo_calidad_agua[red]"
```

Los modelos se leen de `Modelo_calidad_agua/modelos/`, que se genera corriendo los
notebooks 06 a 10 de ese proyecto o se descarga del release de GitHub con
`set MODELO_DIR=..\..\Modelo_calidad_agua` y `python ..\docker\preparar.py` (lo mismo que hace
Docker). Para usar otra carpeta: variable de entorno
`CARPETA_MODELOS`. Si los modelos son de una versión anterior (sin pronóstico de lluvia), el
servicio no arranca y pide volver a correr esos notebooks.

**Pronóstico de lluvia.** Los modelos de pronóstico usan la lluvia pronosticada para las
próximas 24 h (promedio de los modelos meteorológicos ECMWF, GFS, ICON y GEM). La fuente se elige
con la variable de entorno `FUENTE_PRONOSTICO`:

- `archivo` (por defecto): los pronósticos pasados guardados en
  `Modelo_calidad_agua/clima/pronostico_lluvia_modelos.csv`. Es lo que corresponde con los datos
  del emisor, que son de fechas pasadas: el servicio ve el pronóstico que existía en ese momento.
- `open-meteo`: el pronóstico vigente de la API de Open-Meteo, para datos en tiempo real. Se
  consulta cada hora; si no hay conexión, se sigue con el último que se obtuvo.

**Lluvia observada (RNF-009).** Los tres modelos usan también la lluvia que ya cayó
(`lluvia_mm_h`: el detector la de las últimas horas, las fugas la de 24 h y la anticipación la de
30 días). Los sensores de la red no la miden; en el dataset viene de la estación 69-701 del IMN, que
el simulador mete en las lecturas. Cada fuente es un adaptador de la capa de ingesta
(`backend/monitoreo/fuentes_lluvia.py`) que completa la lluvia de cada lectura antes de que llegue
al motor:

- `lecturas`: la lluvia viene en las lecturas, como la manda el simulador o la mandaría un
  pluviómetro de la ASADA.
- `open-meteo`: se consulta Open-Meteo para la hora de cada lectura, con el modelo meteorológico de
  `LLUVIA_MODELOS` (por defecto `ecmwf_ifs025`, el que mejor coincide con la estación). Usa la
  Forecast API para los últimos 90 días y la Historical Forecast API para fechas más viejas (las
  del simulador), con los reintentos de RNF-002; si Open-Meteo no responde, esas horas quedan sin
  lluvia y `/health` da `degradado`.

Los modelos tienen que operar con la misma lluvia con que se entrenaron, así que **por defecto el
servicio usa la de los modelos**: el reentrenamiento deja `fuente_lluvia.json` en la carpeta de
modelos (hoy: `open-meteo`, ECMWF). `FUENTE_LLUVIA` y `LLUVIA_MODELOS` la cambian; si no coinciden
con las de los modelos, `/health` da `degradado` y dice qué hacer. La comparación con el IMN y lo
que pasa con cada modelo están en `Modelo_calidad_agua/docs/modelos/fuente-lluvia.md`. Otra fuente
(otra API, una estación propia) se agrega con una clase nueva en ese archivo, sin tocar el
servicio, el motor ni los modelos.

**Open-Meteo: límites y licencia.** La API gratuita es para uso no comercial (incluye proyectos sin
fines de lucro, sin suscripciones ni publicidad) y permite 10 000 consultas al día por IP; el
servicio hace menos de 100 (la lluvia de cada hora nueva y el pronóstico cada hora). Los datos son
CC BY 4.0: el dashboard muestra el crédito a Open-Meteo al pie. Con un plan pagado, la clave va en
`OPEN_METEO_API_KEY` y las consultas (lluvia y pronóstico) pasan a los dominios
`customer-…open-meteo.com`.

## Pruebas

Las pruebas del servicio no necesitan los modelos entrenados ni los datos: usan lecturas
sintéticas de una red pequeña y unos modelos de prueba que dan pronósticos y probabilidades
fijados por cada prueba. Con eso corren de verdad el motor, las alarmas, las alertas, la API
(incluidos `/health` y los errores 422 de `/predict/contaminacion`) y la carga de modelos de
árboles entrenados en la misma prueba. Desde `backend/`:

```
pip install -r requirements-dev.txt
pytest --cov                 # pruebas y cobertura (mínimo 70 %)
flake8                       # estilo PEP 8 (líneas de hasta 120 caracteres)
```

`verificar`, `ejecutar` y `probar_prediccion` no entran en la medición: necesitan los datos
reales o el servicio corriendo y se usan a mano (ver abajo).

**Prueba de carga (RNF-001).** Con el servicio y la API de datos corriendo, 10 usuarios a la vez
durante 5 minutos sobre `/predict/contaminacion`, `/predict/fugas` y `/api/estado`; el reporte
queda en `docs/rendimiento/` (la columna 95 % es el percentil 95 de la latencia, meta ≤ 500 ms):

```
cd backend
pip install locust
$env:CLAVE_API="<una de las claves de CLAVES_API>"
$env:CORREO_CARGA="<correo de un usuario del dashboard>"     # /api/estado pide sesión
$env:CONTRASENA_CARGA="<su contraseña>"
locust -f carga/locustfile.py --host https://127.0.0.1:8001 --headless -u 10 -r 2 -t 5m --csv ../docs/rendimiento/carga
```

Con el servicio en HTTP (sin certificado) el `--host` es `http://127.0.0.1:8001`.

**Carga del dashboard en Fast 3G (RNF-001, LCP ≤ 2,5 s).** `frontend/medir-lcp.mjs` abre con el
caché vacío la pantalla de inicio de sesión y, con sesión, la vista general y el detalle de un
sensor, con la red Fast 3G de Chrome DevTools (562,5 ms de latencia, 1,44 Mbit/s de bajada) y el
procesador 4 veces más lento, y lee el Largest Contentful Paint que da el navegador (5 veces cada
una). El resultado queda en `docs/rendimiento/lcp.json` (y `lcp-movil.json` con `MOVIL=1`):

```
cd frontend
npm install
npx playwright install chromium
$env:CORREO_LCP="<correo de un usuario del dashboard>"; $env:CONTRASENA_LCP="<su contraseña>"
npm run lcp
```

| Página | Antes | Ahora (mediana · máximo) | Transferido antes → ahora |
|---|---|---|---|
| Inicio de sesión | 5,9 s | 1,9 s · 1,9 s | 784 KB → 145 KB |
| Vista general | 6,7 s | 2,0 s · 2,1 s | 1036 KB → 327 KB |
| Detalle de un sensor | 6,6 s | 2,0 s · 2,0 s | 1132 KB → 342 KB |

(13/11/2026, servicio local con 10 días del periodo de prueba, pantalla de 1366 × 768; en teléfono,
1,9 s en las tres.) Lo que cambió:

- **Compresión**: el servicio manda el dashboard y las respuestas JSON con gzip (`GZipMiddleware`);
  el JavaScript inicial pasó de 678 KB a 81 KB transferidos. Los archivos de `assets/` llevan un hash
  en el nombre y se guardan en el navegador por un año; `index.html`, nunca.
- **Lo primero, primero**: la pantalla de inicio de sesión y la vista general vienen en el archivo
  inicial; los gráficos (Recharts, unos 115 KB), el detalle de un sensor, Usuarios, Alertas y Mi
  cuenta se cargan cuando hacen falta, y mientras tanto queda su espacio para que la página no salte.
- **Los datos no esperan al JavaScript**: `index.html` pide la sesión y los datos de la primera
  pantalla mientras baja el JavaScript (`api.js` usa esas respuestas una sola vez y en los primeros
  15 s; sin sesión las descarta).
- **Letra**: solo el alfabeto latino de Manrope (con tildes y ñ); el CSS pasó de 66 KB a 32 KB.

Las predicciones a pedido se atienden en procesos aparte (`monitoreo/trabajadores.py`), cada uno
con su copia de los modelos: en un solo proceso las solicitudes hacen fila (Python ejecuta de a un
hilo a la vez) y con 10 usuarios el percentil 95 pasaba de 5 s. `TRABAJADORES_PREDICCION` fija
cuántos (por defecto, los núcleos menos uno, hasta 3; unos 800 MB cada uno). La prueba se corre con
el emisor ya terminado (`docker compose ps` ya no lo muestra): con `VELOCIDAD=1` manda una hora
simulada por segundo y el motor pasa ocupado procesándolas, cosa que en operación ocurre una vez
por hora (`VELOCIDAD=0.000278` es el ritmo real).

En GitHub, el CI (`.github/workflows/ci.yml`) corre en cada push y en cada pull request:
estilo, pruebas con cobertura mínima de 70 % (instala `calidad_agua` desde el repositorio
de modelos), compilación del dashboard y búsqueda de secretos en el historial (gitleaks).

## Uso

**Verificación (sin API).** Reproduce el periodo de prueba a través del motor y
compara con el cálculo de los notebooks: mismos pronósticos, mismas alarmas, mismos avisos
anticipados y mismas métricas (acierto del notebook 08, eventos detectados y falsas alarmas del
notebook 07, eventos anticipados del notebook 09, probabilidad y alarmas de fuga del notebook 10).
Antes de la prueba manda 31 días de lecturas, porque la anticipación usa la lluvia de los
últimos 30 días.

```
python -m monitoreo.verificar              # periodo de prueba completo (~3 min)
python -m monitoreo.verificar --dias 10    # más rápido
```

**Prueba de `POST /predict/contaminacion`** (con el servicio corriendo). Manda lecturas reales del
periodo de prueba y mide la latencia (criterio: p95 ≤ 500 ms), revisa que las solicitudes
incompletas respondan 422 con el detalle y, con `--comparar`, que los números sean los de los
notebooks.

```
python -m monitoreo.probar_prediccion              # 100 solicitudes
python -m monitoreo.probar_prediccion -n 300 --comparar
```

**Dashboard.** Compilar el frontend una vez (y cada vez que se cambie), desde `frontend/`:

```
npm install
npm run build
```

Luego, en tres terminales:

```
# 1 · Simulador_sensor:            python -m tiempo_real.servicio
# 2 · este proyecto, en backend/:  python -m monitoreo.servicio
# 3 · Simulador_sensor:            python -m tiempo_real.emisor --velocidad 1
```

y abrir **http://127.0.0.1:8001**. Con `--modo arboles` el servicio corre sin TensorFlow.

El dashboard cumple el RF-003.2 y se actualiza solo cada pocos segundos:

- **Arriba, en las dos vistas:** el estado de toda la red en una línea con su semáforo (verde =
  normal, amarillo = alerta predictiva, rojo = alerta crítica) y una tarjeta por punto de medición,
  de la fuente al extremo, con su semáforo, el cloro actual y su curva de 7 días, la turbidez, el pH
  y el cloro pronosticado. La última tarjeta es la de fugas. Cada tarjeta abre su sensor.
- **A la derecha:** las **alertas activas** ordenadas por severidad y antelación (lo que ya pasa,
  después lo anticipado a 24 h y a 48 h) y el **historial de alarmas** del detector.
- **Vista general** (`#/general`):
  - Gráfico de la red para cloro, turbidez o pH: mediana de los sensores, la banda donde está la
    mayoría (del 10 % al 90 %) y el sensor más extremo, en los últimos 7 días y el pronóstico de
    las próximas 24 h. Una falla general mueve toda la banda; un problema local separa al sensor
    extremo.
  - **Probabilidad de eventos** a 24 h y a 48 h por tipo, cada una con su umbral. La de 48 h
    sale del modelo de árboles del notebook 09 y solo se muestra (los avisos y alertas son los de
    24 h).
  - **Riesgo de fuga por tramo**: mapa de calor tramo × hora de los últimos 7 días, donde el
    riesgo es la probabilidad de fuga por la probabilidad de que esté en ese tramo. Las alertas de
    fuga enlazan aquí (`#/fugas`).
  - Mapa de calor sensor × hora, de la fuente al extremo: muestra cómo un evento se propaga por la
    red. Los valores fuera de norma van en rojo; al tocar un sensor se abre su detalle.
- **Por sensor** (`#/sensor/J224`): los gráficos del sensor en detalle (7 días observados,
  pronóstico con margen de acierto, límites de la norma y probabilidad de evento).

Para trabajar en el frontend con recarga automática: `npm run dev` en `frontend/` y abrir
http://localhost:5173 (las llamadas a `/api` se redirigen al backend en el puerto 8001).

**Solo consola**, sin dashboard: `python -m monitoreo.ejecutar` en lugar del servicio.

### Alertas por correo

Cada aviso (los mismos que se describen en **Alertas por Telegram**) se manda por correo
(RF-003.3, CU-04) a los usuarios que el administrador marcó en **Usuarios**:

| Nivel | Qué avisos | Quién lo recibe |
|---|---|---|
| Rojo (críticas) | alarma o posible fuga, al abrirse y al cerrarse | quien tiene marcadas las **Críticas** (por defecto, operadores y administradores) |
| Amarillo (predictivas) | aviso anticipado, riesgo en 24 h, datos que se apartan de lo habitual | quien tiene marcadas las **Predictivas** (por defecto, operadores) |
| Resumen diario | el resumen de la hora `ALERTAS_RESUMEN_HORA` | quien tiene marcada cualquiera de las dos |

El asunto dice el nivel, qué pasa y dónde (por ejemplo `Alerta roja · Alarma #3: falla de
cloración en J439 y 2 sensores más`), y el correo trae la probabilidad, la antelación, los sensores
con sus valores, qué hacer y un botón al tablero. Cada persona recibe su propio correo. El correo
sale apenas el motor procesa la hora, en un hilo aparte. Si falla, se reintenta 3 veces (a los 5,
10 y 20 s), solo con los destinatarios que faltan. Cada envío queda registrado en la tabla
`notificaciones` con su estado (enviada, fallida o sin destinatarios), y el administrador lo ve en
**Usuarios › Alertas por correo**. Desde ahí puede mandarse un correo de prueba.

**Con Gmail** (una cuenta exclusiva para las alertas, p. ej. `alertas.asadalalucha@gmail.com`):

1. En la cuenta de Google, activar la **verificación en 2 pasos** (Seguridad).
2. En https://myaccount.google.com/apppasswords crear una **contraseña de aplicación** (nombre:
   "Monitoreo ASADA"). Google muestra 16 letras una sola vez.
3. En el `.env` (no va en el código ni en git):

   ```
   SMTP_SERVIDOR=smtp.gmail.com
   SMTP_PUERTO=587
   SMTP_USUARIO=alertas.asadalalucha@gmail.com
   SMTP_CONTRASENA=<las 16 letras, sin espacios>
   URL_DASHBOARD=https://<dirección del tablero que abren los destinatarios>
   ```

4. Probar desde `backend/` (o con `docker compose exec monitoreo python -m monitoreo.correo ...`):

   ```
   python -m monitoreo.correo --prueba tu-correo@ejemplo.com
   ```

5. Reiniciar el servicio: en la consola dice `Alertas: correo` (o `correo + telegram`).

Una cuenta gratuita de Gmail admite unos 500 destinatarios por día, de sobra para la ASADA. Con
otro proveedor (Outlook, el hosting de la ASADA, Brevo...) se usan los datos SMTP que dé ese
proveedor. `SMTP_SEGURIDAD` es `starttls` por defecto o `ssl` con el puerto 465, y
`SMTP_REMITENTE` sirve si el remitente no es el mismo usuario.

**Sin cuenta de correo, para probar o demostrar:** `docker compose --profile correo up --build`
levanta también **Mailpit**, que recibe todos los correos y los muestra en http://127.0.0.1:8025
sin mandarlos a nadie. En el `.env`: `SMTP_SERVIDOR=mailpit`, `SMTP_PUERTO=1025`,
`SMTP_SEGURIDAD=ninguna` y `SMTP_REMITENTE=alertas@asada.local`.

### Alertas por Telegram

Además del correo, el servicio puede avisar por Telegram (el segundo canal que CU-04 deja para
después del MVP). Avisa cuando se **abre** una alarma (tipo de evento sugerido, sensores con
su probabilidad de evento y sus valores de cloro, turbidez y pH, a qué sensores todavía no llega si
el evento empieza en la planta, y qué hacer), cuando se **cierra** (duración y sensores), cuando el
pronóstico de un sensor sale de la norma en las próximas 24 h (**riesgo**, una vez por episodio,
con qué hacer según el parámetro), cuando el modelo de anticipación espera que **empiece un evento en las próximas 24 h**
(**aviso anticipado**: tipo, probabilidad, la señal que lo explica y, si el evento empieza en la
planta, en cuántas horas llegaría a cada sensor, y qué revisar para evitarlo) y con un **resumen
diario**. Las acciones recomendadas están en `ACCION_ALARMA`, `ACCION_AVISO` y `ACCION_RIESGO` de
`backend/monitoreo/alertas.py`: son una guía general y la ASADA debe ajustarlas a sus
procedimientos. Sin correo ni Telegram configurados, las alertas solo se escriben en
la consola del servicio.

Configuración, una sola vez:

1. En Telegram, escribirle a **@BotFather** `/newbot` y seguir los pasos: da el *token* del bot.
2. Abrir el chat con el bot nuevo y mandarle cualquier mensaje.
3. Poner el token en `TELEGRAM_TOKEN` del archivo `.env` (ver **Seguridad**; no va en el código
   ni en git) y sacar el *chat id*. Desde `backend/`, con el venv activado:

   ```
   python -m monitoreo.alertas --chat-id
   # poner el número en TELEGRAM_CHAT_ID del .env y probar:
   python -m monitoreo.alertas --prueba
   ```

Al arrancar, el servicio dice en la consola qué canales usa (`Alertas: telegram` o
`correo + telegram`) y `/api/estado` informa cuántas alertas se enviaron por cada canal y el último
error, si hubo.

Opciones (en el `.env`): `ALERTAS_RIESGO=0` para no avisar del riesgo en 24 h,
`ALERTAS_ANTICIPACION=0` para no mandar los avisos anticipados,
`ALERTAS_RESUMEN_HORA` para la hora del resumen diario (7 por defecto; `-1` para no mandarlo),
`URL_DASHBOARD` para el enlace de los mensajes y `TELEGRAM_CHAT_ID` con varios chats separados
por coma para avisar a más de una persona. Las horas son las de los datos: con el emisor en
tiempo real coinciden con el reloj; con el emisor acelerado llegan muchos mensajes seguidos.

### Seguridad

Los secretos y la configuración local van en un archivo **`.env`** en la raíz del proyecto, que
no se versiona. Para crearlo, copiar `.env.ejemplo` como `.env` y completar los valores. Las
variables definidas en el sistema (por ejemplo con `setx`) tienen prioridad sobre las del `.env`.

- **Clave de API.** `POST /predict/contaminacion` pide una de las claves de `CLAVES_API` en el
  encabezado `X-API-Key`. Sin clave o con una equivocada responde 401 y anota el intento (fecha,
  origen, ruta y motivo, nunca la clave) en `registros/accesos_rechazados.log`. Sin ninguna clave
  configurada responde 503, para que no quede abierto por olvido. En `/docs`, el botón
  **Authorize** permite probarlo con la clave. El dashboard (`/api/...`) no usa la clave sino el
  inicio de sesión (abajo); `/health` queda abierto para Docker y el monitoreo externo.
- **HTTPS.** Con `CERTIFICADO_TLS` y `CLAVE_TLS` el servicio atiende solo por HTTPS, con TLS 1.2
  como versión mínima. Para usarlo en la propia máquina hay un certificado de prueba.
- **Secretos en el repositorio.** El CI busca secretos en todo el historial con gitleaks.

Desde `backend/`:

```
python -m monitoreo.seguridad --nueva-clave     # clave para CLAVES_API
python -m monitoreo.seguridad --certificado     # certificado para 127.0.0.1 en secretos/
```

El certificado de prueba es autofirmado: el navegador avisa que no lo reconoce hasta que se
marca como confiable (el comando dice cómo). Para un servidor real se usa un certificado de una
autoridad reconocida, que se configurará con Docker.

### Inicio de sesión y roles

El dashboard pide correo y contraseña (CU-00). Cada usuario tiene un rol:

| Rol | Qué puede hacer |
|---|---|
| Junta Directiva | ver el tablero |
| Operador técnico | ver el tablero y atender las alertas (CU-06) |
| Administrador | lo anterior (también atiende alertas), y en **Usuarios**: crear, editar y desactivar usuarios, cambiarles el rol, restablecer su contraseña, elegir quién recibe por correo las alertas críticas y las predictivas, y ver la bitácora de accesos y cambios (CU-07) |

- **El primer administrador** se crea desde la consola, en `backend/`:
  `python -m monitoreo.usuarios --crear-admin correo@asada.cr "Nombre Apellido"`. Los demás los
  crea él desde el dashboard, con una contraseña temporal que cada persona cambia al entrar.
- **Contraseñas:** al menos 10 caracteres; se guarda solo su hash (scrypt con sal). Con 5
  intentos fallidos seguidos, ese correo queda bloqueado 15 minutos. El mensaje de error es el
  mismo si falla el correo o la contraseña.
- **Sesión:** cookie HttpOnly y SameSite=Strict (Secure con HTTPS) que vence a las 12 h. Al
  desactivar a alguien o restablecer su contraseña se cierran sus sesiones abiertas. Nadie puede
  quitarse el rol de administrador a sí mismo, ni desactivar al último administrador activo.
- **Dónde se guardan:** en `BASE_DE_DATOS` (PostgreSQL en Docker) o, sin ella, en
  `registros/usuarios.db` (SQLite). `BASE_USUARIOS` permite usar otra base.
- **Bitácora:** inicios de sesión, intentos fallidos, cierres y cambios de usuarios, con fecha,
  correo y origen. Se ve en **Usuarios**.
- `INICIO_SESION=no` en el `.env` deja el dashboard abierto, solo para desarrollo.

### Gestión de alertas

Cada alarma, posible fuga, aviso anticipado o riesgo en 24 h queda como una **alerta** en la
página **Alertas** del tablero (CU-06), hasta que alguien la cierre. La pestaña muestra cuántas
faltan por atender, y el botón de cada correo lleva directo a su alerta.

1. **Nueva:** la crea el sistema con el tipo de evento, dónde, la probabilidad, la antelación, las
   lecturas y qué hacer.
2. **En atención:** un operador o el administrador la **reconoce** y queda como responsable. Si ya
   la atiende otra persona, el sistema dice quién y deja agregar observaciones.
3. Se van anotando **las acciones realizadas y lo que se encontró en campo**.
4. **Cerrada:** con su **resultado** (confirmada, falso positivo o inconclusa) y las observaciones,
   que son obligatorias. Las inconclusas no cuentan para evaluar el modelo.

- **Sin duplicados:** mientras una alerta del mismo tipo y lugar siga activa, no se crea otra ni
  se reenvía el correo: se actualiza su probabilidad. Al reiniciar el servicio tampoco se repiten.
- **Se resuelve sola** (RF-003.3): un aviso predictivo (amarillo) que nadie tomó se cierra solo
  cuando el riesgo baja del umbral. Una alerta roja que terminó sigue esperando a que alguien
  diga qué pasó.
- **Historial inmutable:** cada paso (creada, tomada, observación, terminó, cerrada) queda con
  fecha y persona; nunca se modifica ni se borra.
- **Filtros:** estado, tipo, nodo y fechas. Arriba se ve lo pendiente y qué porcentaje de las
  verificadas en campo resultó un evento real: es el insumo para validar el modelo (RF-004.1).
- La Junta Directiva las ve, pero solo el operador técnico y el administrador las atienden.

### F1 de las alarmas en producción (RF-004.2 y RNF-003)

La página **Alertas** muestra el **F1 de los últimos 7 días** de las alarmas de la red y las
posibles fugas (las alertas rojas de los modelos de detección), con lo que el personal verificó:

- **acierto:** alerta cerrada como confirmada; **falso positivo:** cerrada como falso positivo;
- **no detectado:** un evento que ocurrió sin alerta. Lo registra el operador o el administrador con
  el botón **Registrar un evento que no se detectó** (cuándo, tipo, dónde, si lo dijo el laboratorio,
  un registro de la ASADA o un abonado, y observaciones);
- las inconclusas, las que siguen abiertas y los avisos amarillos no cuentan.

F1 = 2·aciertos / (2·aciertos + falsos positivos + no detectados). Con menos de 3 casos verificados
en la ventana se muestra "faltan casos verificados" y no se avisa.

**Todos los días**, cuando el procesamiento pasa por la medianoche de los datos, el servicio
calcula el F1 de los 7 días anteriores, lo guarda en la base (tabla `rendimiento_diario`) y lo
registra en **MLflow**, en el experimento `monitoreo_produccion` (una corrida por día con el F1,
la precisión, la sensibilidad y los casos). Si el F1 baja de **75 %**, manda una **alerta
amarilla** por correo y Telegram con qué revisar. En Docker, MLflow ya está conectado
(`MLFLOW_URL=http://mlflow:5000`); sin Docker se configura con `MLFLOW_URL` en el `.env` (por
ejemplo `http://127.0.0.1:5000` con `mlflow ui` corriendo); sin MLflow el F1 se guarda igual en la
base. Se ajusta con `RENDIMIENTO_DIAS` (7), `RENDIMIENTO_F1_MINIMO` (0,75) y
`RENDIMIENTO_MIN_CASOS` (3).

### API del servicio (puerto 8001)

| Ruta | Qué devuelve |
|---|---|
| `GET /health` | si el servicio está en pie (`ok` o `degradado` con el motivo), versión, y de cada modelo cargado su huella y la corrida de MLflow que lo generó (`run_id`, experimento y huella de los datos) |
| `POST /predict/contaminacion` | requiere `X-API-Key`. Con las lecturas de 15 min de toda la red de las últimas 98 h (mismo formato que `POST /lecturas` de la API de datos): probabilidad de evento, tipo sugerido, pronóstico a 24 h y nivel verde, amarillo o rojo por sensor y para la red. 422 con el detalle si faltan columnas, lecturas o datos. El nivel amarillo empieza en `UMBRAL_AMARILLO` (0,5 por defecto) |
| `POST /api/sesion` | inicia sesión con `{"correo", "contrasena"}`; deja la cookie. `GET` dice quién tiene la sesión (401 si nadie) y `DELETE` la cierra |
| `POST /api/sesion/contrasena` | cambia la contraseña propia: `{"actual", "nueva"}` |
| `GET, POST /api/usuarios`, `PATCH /api/usuarios/{id}` | solo administrador: lista, crea y modifica usuarios (nombre, rol, activo, notificaciones, contraseña temporal) |
| `GET /api/bitacora?limite=100` | solo administrador: accesos y cambios, el más reciente primero |
| `GET /api/alertas?estado=pendientes&tipo=&nodo=&desde=&hasta=` | alertas para atender (estado `nueva`, `en_atencion`, `cerrada` o `pendientes`; tipo `alarma`, `fuga`, `aviso` o `riesgo`; fechas AAAA-MM-DD), lo pendiente primero. `GET /api/alertas/{id}` da el detalle con el historial y `GET /api/alertas/indicadores`, lo pendiente y los resultados de los últimos 30 días |
| `POST /api/alertas/{id}/reconocer`, `/notas` y `/cerrar` | operador o administrador: tomar la alerta, agregar `{"texto"}` y cerrarla con `{"resultado", "observaciones"}` (409 si ya está cerrada o la atiende otra persona) |
| `GET /api/rendimiento` | F1 de las alarmas en los últimos 7 días (hora de los datos), con los aciertos, falsos positivos, no detectados y sin verificar, y el historial diario |
| `GET, POST /api/rendimiento/no-detectados` | eventos que ocurrieron sin alerta; registrar uno (operador o administrador): `{"fecha", "tipo", "lugar", "fuente", "observaciones"}` |
| `GET /api/notificaciones?limite=30` | solo administrador: si el correo está configurado, cuántas personas reciben cada nivel y los últimos envíos por correo y Telegram |
| `POST /api/notificaciones/prueba` | solo administrador: manda un correo de prueba a quien lo pide (409 si no hay SMTP; 502 con el motivo si el servidor no lo acepta) |
| `GET /api/estado` | hora de los datos, conexión, alarma activa, modo de pronóstico, estado de las alertas; `retomado` (desde qué hora siguió después de un reinicio) y `sin_datos_desde` (desde cuándo no llegan lecturas). Desde aquí, todo `/api/...` pide la sesión (401 sin ella) |
| `POST /predict/fugas` | requiere `X-API-Key`. Con las mismas lecturas, pero de los últimos 8 días: probabilidad de fuga, alarma confirmada, tramo más probable y caudal de más (nivel verde, amarillo o rojo). 422 si falta historia |
| `GET /api/sensores` | estado actual de los sensores: observado, pronóstico a 24 h, probabilidad de evento |
| `GET /api/sensores/{nodo}/serie?horas=72` | serie horaria para graficar (observado, pronóstico, probabilidad) |
| `GET /api/red/series?horas=72` | series de todos los sensores a la vez (vista general) |
| `GET /api/alarmas` | alarmas de red, la más reciente primero |
| `GET /api/anticipacion` | probabilidad de que empiece cada tipo de evento en las próximas 24 h, con su umbral, y los avisos anticipados (`disponible: false` si no hay modelo de anticipación) |
| `GET /api/fugas?horas=168` | probabilidad de fuga por hora, estado actual con el tramo y el caudal de más, y las alarmas de fuga (`disponible: false` si no hay modelo de fugas) |
| `GET /api/referencias` | norma, tolerancias de la meta y umbral del detector |

### Resiliencia (RNF-002)

Ninguna falla externa detiene el monitoreo ni hace perder horas de datos. El detalle, con cada
modo de falla y sus pruebas, está en [docs/arquitectura-resiliencia.md](docs/arquitectura-resiliencia.md).

- **Reintentos con espera creciente:** la API de datos (0,5, 1 y 2 s), Open-Meteo (1, 2 y 4 s; si
  falla, sigue con el último pronóstico y vuelve a probar en 10 min) y el correo y Telegram (5, 10
  y 20 s, cada canal en su hilo).
- **Cola persistente:** la API de datos guarda las lecturas y el servicio guarda en la base de
  datos la última hora procesada (`cursor.py`). Si la API se cae, al volver se procesan en orden
  todas las horas pendientes; si el servicio se reinicia, sigue con la hora siguiente y rearma con
  los últimos 31 días la lluvia de 30 días, la semana de las fugas y la de la deriva.
- **Base de datos caída:** los resultados se escriben siempre en el CSV de `registros/` y las filas
  para la base esperan hasta que vuelva.
- **Datos que no llegan:** si pasan 60 min sin lecturas nuevas (`SIN_DATOS_MIN`), se avisa por correo
  (a todos los destinatarios) y por Telegram, y otra vez cuando vuelven. `/health` da `degradado`.
- **Docker** vuelve a levantar los servicios si se caen (`restart: unless-stopped`).

## Cómo funciona el motor

- Una hora se **cierra** cuando llega una lectura de la hora siguiente.
- En cada ciclo se procesan **juntas todas las horas cerradas pendientes**: armar las
  variables cuesta casi lo mismo para una hora que para muchas, así que el motor no se
  queda atrás aunque los datos lleguen acelerados (~70 ms por hora).
- Las variables se arman con las últimas **96 h** de lecturas (144 h si la anticipación es la LSTM,
  porque cada secuencia mira 48 h de variables hacia atrás), limpiadas con las reglas de
  operación (presión, rango físico, sensor pegado) y el **preprocesamiento** (RF-001.3): quita los
  picos de cloro, turbidez, pH y temperatura por IQR, interpola los huecos de hasta 30 min y marca
  los más largos (`flag_imputacion`). Es el mismo código del entrenamiento
  (`calidad.lecturas_operativas`). `/api/estado` dice en `imputacion_ultimo_ciclo` cuántas filas
  del último ciclo llegaron completas, con algo rellenado o con un hueco largo.
- **Calentamiento:** al arrancar, hasta tener 96 h de datos no se encienden alarmas y los
  pronósticos se marcan como `calentando`. Después de un reinicio no hay calentamiento: el
  servicio sigue desde la última hora procesada (ver Resiliencia).
- **Alarmas** (igual que en el notebook 07): un sensor entra en alarma si su probabilidad
  de evento supera el umbral las horas de confirmación seguidas (las del modelo guardado); la alarma de red se cierra tras 2 horas
  seguidas sin ningún sensor en alarma.
- **Avisos anticipados** (igual que en el notebook 09): cada tipo de evento tiene su umbral y sus
  horas de confirmación; un tipo entra en aviso cuando su probabilidad de empezar en las próximas
  24 h supera el umbral esas horas seguidas, y el aviso termina tras 6 horas sin aviso. La lluvia
  de 30 días (una de las variables) se guarda aparte, porque el búfer tiene solo 96 h. Si no está
  `anticipacion_24h.joblib` en la carpeta de modelos, el servicio funciona igual sin avisos.
- **Fugas** (igual que en el notebook 10): hay alarma de fuga cuando la probabilidad supera el
  umbral durante las horas de confirmación seguidas, y se cierra tras 2 horas sin alarma. El
  tramo de la alarma es el más votado en sus horas. La línea base compara con la misma hora de
  los 7 días anteriores, así que el caudal y la presión horarios de los últimos 9 días se guardan
  aparte. Si no está `fugas.joblib`, el servicio funciona igual sin fugas.
- **Modo de pronóstico:** `combinado` (árboles para cloro, LSTM para turbidez, promedio
  para pH, como se eligió en el notebook 08) o `arboles` (sin TensorFlow).
