# Monitoreo de calidad de agua

Servicio en vivo para una red con **tres puntos de medición** (la salida de la fuente J280, con
el caudalímetro, y los puntos J224 y J237 de la red): recibe las lecturas cada 15 minutos,
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
    motor.py           recibe lecturas, procesa cada hora cerrada, maneja las alarmas
    cliente_datos.py   consulta la API de datos
    alertas.py         avisos por Telegram (alarmas, avisos anticipados, riesgo en 24 h, resumen diario)
    servicio.py        API del servicio (FastAPI, puerto 8001) que además sirve el dashboard
    ejecutar.py        motor en vivo conectado a la API de datos, solo en consola
    verificar.py       comprueba que el motor en vivo da lo mismo que los notebooks
    prediccion.py      POST /predict/contaminacion y /predict/fugas: predicción con lecturas que manda el cliente
    seguridad.py       clave de API, registro de accesos rechazados y HTTPS (TLS 1.2 o más)
    usuarios.py        inicio de sesión, roles, usuarios y bitácora del dashboard (CU-00, CU-07)
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
    App.jsx            páginas: #/general, #/sensor/J224, #/usuarios (administrador) y #/cuenta
    estado.js          semáforo y alertas activas ordenadas por severidad y antelación
    componentes/       Encabezado, Tarjetas, AlertasActivas, VistaGeneral, Anticipacion, Fugas,
                       GraficoRed, MapaCalor, DetalleSensor, Graficos, Alarmas, InicioSesion,
                       Cuenta, Usuarios
    api.js             consultas periódicas al backend y aviso cuando vence la sesión
    formato.js         etiquetas, norma, tolerancias, formato de números y fechas
    estilos.css        colores (modo claro y oscuro), tipografía y diseño
registros/             CSV de cada sesión del motor y accesos rechazados (no se versiona)
.env.ejemplo          variables de configuración y secretos; se copia como .env (no se versiona)
secretos/             certificado de HTTPS (no se versiona)
Dockerfile, docker/, docker-compose.yml   el sistema completo en Docker con un solo comando
```

## Con Docker (un solo comando)

Con Docker Desktop instalado y los tres proyectos en la misma carpeta (`Simulador_sensor`,
`Modelo_calidad_agua` y `Monitoreo_calidad_agua`, como en `D:\Practica_Profesional`), y con los
modelos ya entrenados (notebooks 06 a 10) y el dataset exportado, desde esta carpeta:

```
docker compose up --build
```

La primera vez tarda unos minutos (instala TensorFlow y compila el dashboard); las siguientes,
segundos. Levanta cinco servicios:

| Servicio | Qué hace | Dirección |
|---|---|---|
| `datos` | API de datos de los sensores (`Simulador_sensor/tiempo_real`) | http://127.0.0.1:8000 |
| `emisor` | manda las lecturas de la prueba como si fueran los sensores (31 días de precarga y después 1 h simulada por segundo; `VELOCIDAD=4 docker compose up` lo acelera) | — |
| `monitoreo` | servicio con el dashboard, que guarda los resultados de cada hora también en la base de datos | http://127.0.0.1:8001 |
| `db` | PostgreSQL 16 con TimescaleDB: tablas `pronosticos`, `deteccion`, `alarmas`, `anticipacion` y `fugas` (las que tienen fecha, como hipertablas), y `usuarios`, `sesiones` y `bitacora` del dashboard | puerto 5432 dentro de Docker |
| `mlflow` | los experimentos de los notebooks (lee `Modelo_calidad_agua/mlflow.db`) | http://127.0.0.1:5000 |

La primera vez hay que crear el administrador del dashboard (pide la contraseña dos veces):

```
docker compose exec monitoreo python -m monitoreo.usuarios --crear-admin correo@asada.cr "Nombre Apellido"
```

Los secretos van en el `.env` de esta carpeta, igual que sin Docker. Si el `.env` tiene
`CERTIFICADO_TLS` y `CLAVE_TLS`, el contenedor usa los archivos de `secretos/` y el dashboard queda
en **https**://127.0.0.1:8001. `docker compose down` lo
apaga; `docker compose down -v` borra también la base de datos.

## Instalación

Desde `backend/`:

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install -e "..\..\Modelo_calidad_agua[red]"
```

Los modelos se leen de `Modelo_calidad_agua/modelos/`, que se genera corriendo los
notebooks 06 a 10 de ese proyecto. Para usar otra carpeta: variable de entorno
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

### Alertas por Telegram

El servicio avisa por Telegram cuando se **abre** una alarma (tipo de evento sugerido, sensores con
su probabilidad de evento y sus valores de cloro, turbidez y pH, a qué sensores todavía no llega si
el evento empieza en la planta, y qué hacer), cuando se **cierra** (duración y sensores), cuando el
pronóstico de un sensor sale de la norma en las próximas 24 h (**riesgo**, una vez por episodio,
con qué hacer según el parámetro), cuando el modelo de anticipación espera que **empiece un evento en las próximas 24 h**
(**aviso anticipado**: tipo, probabilidad, la señal que lo explica y, si el evento empieza en la
planta, en cuántas horas llegaría a cada sensor, y qué revisar para evitarlo) y con un **resumen
diario**. Las acciones recomendadas están en `ACCION_ALARMA`, `ACCION_AVISO` y `ACCION_RIESGO` de
`backend/monitoreo/alertas.py`: son una guía general y la ASADA debe ajustarlas a sus
procedimientos. Sin Telegram configurado, las alertas solo se escriben en
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

Al arrancar, el servicio dice en la consola qué canal usa (`Alertas: telegram`) y `/api/estado`
informa cuántas alertas se enviaron y el último error, si hubo.

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
| Operador técnico | ver el tablero (y, más adelante, atender las alertas) |
| Administrador | lo anterior, y en **Usuarios**: crear, editar y desactivar usuarios, cambiarles el rol, restablecer su contraseña, elegir quién recibe por correo las alertas críticas y las predictivas, y ver la bitácora de accesos y cambios (CU-07) |

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

### API del servicio (puerto 8001)

| Ruta | Qué devuelve |
|---|---|
| `GET /health` | si el servicio está en pie (`ok` o `degradado` con el motivo), versión, y de cada modelo cargado su huella y la corrida de MLflow que lo generó (`run_id`, experimento y huella de los datos) |
| `POST /predict/contaminacion` | requiere `X-API-Key`. Con las lecturas de 15 min de toda la red de las últimas 98 h (mismo formato que `POST /lecturas` de la API de datos): probabilidad de evento, tipo sugerido, pronóstico a 24 h y nivel verde, amarillo o rojo por sensor y para la red. 422 con el detalle si faltan columnas, lecturas o datos. El nivel amarillo empieza en `UMBRAL_AMARILLO` (0,5 por defecto) |
| `POST /api/sesion` | inicia sesión con `{"correo", "contrasena"}`; deja la cookie. `GET` dice quién tiene la sesión (401 si nadie) y `DELETE` la cierra |
| `POST /api/sesion/contrasena` | cambia la contraseña propia: `{"actual", "nueva"}` |
| `GET, POST /api/usuarios`, `PATCH /api/usuarios/{id}` | solo administrador: lista, crea y modifica usuarios (nombre, rol, activo, notificaciones, contraseña temporal) |
| `GET /api/bitacora?limite=100` | solo administrador: accesos y cambios, el más reciente primero |
| `GET /api/estado` | hora de los datos, conexión, alarma activa, modo de pronóstico, estado de las alertas. Desde aquí, todo `/api/...` pide la sesión (401 sin ella) |
| `POST /predict/fugas` | requiere `X-API-Key`. Con las mismas lecturas, pero de los últimos 8 días: probabilidad de fuga, alarma confirmada, tramo más probable y caudal de más (nivel verde, amarillo o rojo). 422 si falta historia |
| `GET /api/sensores` | estado actual de los sensores: observado, pronóstico a 24 h, probabilidad de evento |
| `GET /api/sensores/{nodo}/serie?horas=72` | serie horaria para graficar (observado, pronóstico, probabilidad) |
| `GET /api/red/series?horas=72` | series de todos los sensores a la vez (vista general) |
| `GET /api/alarmas` | alarmas de red, la más reciente primero |
| `GET /api/anticipacion` | probabilidad de que empiece cada tipo de evento en las próximas 24 h, con su umbral, y los avisos anticipados (`disponible: false` si no hay modelo de anticipación) |
| `GET /api/fugas?horas=168` | probabilidad de fuga por hora, estado actual con el tramo y el caudal de más, y las alarmas de fuga (`disponible: false` si no hay modelo de fugas) |
| `GET /api/referencias` | norma, tolerancias de la meta y umbral del detector |

## Cómo funciona el motor

- Una hora se **cierra** cuando llega una lectura de la hora siguiente.
- En cada ciclo se procesan **juntas todas las horas cerradas pendientes**: armar las
  variables cuesta casi lo mismo para una hora que para muchas, así que el motor no se
  queda atrás aunque los datos lleguen acelerados (~70 ms por hora).
- Las variables se arman con las últimas **96 h** de lecturas, limpiadas solo con las
  reglas de operación (presión, rango físico, sensor pegado).
- **Calentamiento:** al arrancar, hasta tener 96 h de datos no se encienden alarmas y los
  pronósticos se marcan como `calentando`.
- **Alarmas** (igual que en el notebook 07): un sensor entra en alarma si su probabilidad
  de evento supera el umbral 3 horas seguidas; la alarma de red se cierra tras 2 horas
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
