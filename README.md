# Monitoreo de calidad de agua

Servicio en vivo para la red de 21 sensores: recibe las lecturas cada 15 minutos,
pronostica cloro, turbidez y pH a 24 h, detecta eventos y abre alarmas.

```
API de datos de los sensores  ──►  backend (motor + modelos)  ──►  frontend (dashboard en React)
(lecturas cada 15 min)             pronóstico, detector,           red de sensores, gráficos,
                                   alarmas, API en :8001           alarmas
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
    alertas.py         avisos por Telegram (alarmas, riesgo en 24 h, resumen diario)
    servicio.py        API del servicio (FastAPI, puerto 8001) que además sirve el dashboard
    ejecutar.py        motor en vivo conectado a la API de datos, solo en consola
    verificar.py       comprueba que el motor en vivo da lo mismo que los notebooks
    prediccion.py      POST /predict/contaminacion: predicción con lecturas que manda el cliente
    seguridad.py       clave de API, registro de accesos rechazados y HTTPS (TLS 1.2 o más)
    probar_prediccion.py  prueba de ese endpoint: latencia p95, errores 422 y mismos números
  pruebas/             pruebas unitarias del servicio (pytest)
  requirements.txt
  requirements-dev.txt  lo que hace falta para las pruebas y el estilo
.github/              integración continua en GitHub
frontend/              dashboard en React (Vite + Recharts)
  src/
    App.jsx            página y navegación entre las dos vistas (#/general y #/sensor/J224)
    componentes/       Encabezado, VistaGeneral, GraficoRed, MapaCalor, RedSensores,
                       DetalleSensor, Graficos, Alarmas
    api.js             consultas periódicas al backend
    formato.js         etiquetas, norma, tolerancias, formato de números y fechas
    estilos.css        colores (modo claro y oscuro), tipografía y diseño
registros/             CSV de cada sesión del motor y accesos rechazados (no se versiona)
.env.ejemplo          variables de configuración y secretos; se copia como .env (no se versiona)
secretos/             certificado de HTTPS (no se versiona)
```

## Instalación

Desde `backend/`:

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install -e "..\..\Modelo_calidad_agua[red]"
```

Los modelos se leen de `Modelo_calidad_agua/modelos/`, que se genera corriendo los
notebooks 07 y 08 de ese proyecto. Para usar otra carpeta: variable de entorno
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

En GitHub, el CI (`.github/workflows/ci.yml`) corre en cada push y en cada pull request:
estilo, pruebas con cobertura mínima de 70 % (instala `calidad_agua` desde el repositorio
de modelos), compilación del dashboard y búsqueda de secretos en el historial (gitleaks).

## Uso

**Verificación (sin API).** Reproduce el periodo de prueba a través del motor y
compara con el cálculo de los notebooks: mismos pronósticos, mismas alarmas y mismas
métricas (acierto del notebook 08, eventos detectados y falsas alarmas del notebook 07).

```
python -m monitoreo.verificar              # periodo de prueba completo (~5 min)
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

El dashboard tiene dos vistas:

- **Vista general** (`#/general`): la red completa para cloro, turbidez o pH.
  - Gráfico de la red: mediana de los 21 sensores, la banda donde está la mayoría (del 10 %
    al 90 %) y el sensor más extremo, en las últimas 72 h y el pronóstico de las próximas
    24 h. Una falla general mueve toda la banda; un problema local separa al sensor extremo.
  - Mapa de calor sensor × hora, de la fuente al extremo de la red: muestra cómo un evento
    se propaga por la red. Los valores fuera de norma van en rojo; al tocar un sensor se
    abre su detalle.
- **Por sensor** (`#/sensor/J224`): la red como tubería para elegir el sensor y sus gráficos
  en detalle (72 h observadas, pronóstico con margen de acierto, límites de la norma y
  probabilidad de evento).

Para trabajar en el frontend con recarga automática: `npm run dev` en `frontend/` y abrir
http://localhost:5173 (las llamadas a `/api` se redirigen al backend en el puerto 8001).

**Solo consola**, sin dashboard: `python -m monitoreo.ejecutar` en lugar del servicio.

### Alertas por Telegram

El servicio avisa por Telegram cuando se **abre** una alarma (tipo de evento sugerido, sensores y
sus valores de cloro, turbidez y pH), cuando se **cierra** (duración y sensores), cuando el
pronóstico de un sensor sale de la norma en las próximas 24 h (**riesgo**, una vez por
episodio) y con un **resumen diario**. Sin Telegram configurado, las alertas solo se escriben en
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
  **Authorize** permite probarlo con la clave. El dashboard (`/`, `/api/...`) y `/health` no la
  piden: son de solo lectura y los usa el navegador.
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

### API del servicio (puerto 8001)

| Ruta | Qué devuelve |
|---|---|
| `GET /health` | si el servicio está en pie (`ok` o `degradado` con el motivo), versión, y de cada modelo cargado su huella y la corrida de MLflow que lo generó (`run_id`, experimento y huella de los datos) |
| `POST /predict/contaminacion` | requiere `X-API-Key`. Con las lecturas de 15 min de toda la red de las últimas 98 h (mismo formato que `POST /lecturas` de la API de datos): probabilidad de evento, tipo sugerido, pronóstico a 24 h y nivel verde, amarillo o rojo por sensor y para la red. 422 con el detalle si faltan columnas, lecturas o datos. El nivel amarillo empieza en `UMBRAL_AMARILLO` (0,5 por defecto) |
| `GET /api/estado` | hora de los datos, conexión, alarma activa, modo de pronóstico, estado de las alertas |
| `GET /api/sensores` | estado actual de los 21 sensores: observado, pronóstico a 24 h, probabilidad de evento |
| `GET /api/sensores/{nodo}/serie?horas=72` | serie horaria para graficar (observado, pronóstico, probabilidad) |
| `GET /api/red/series?horas=72` | series de los 21 sensores a la vez (vista general) |
| `GET /api/alarmas` | alarmas de red, la más reciente primero |
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
- **Modo de pronóstico:** `combinado` (árboles para cloro, LSTM para turbidez, promedio
  para pH, como se eligió en el notebook 08) o `arboles` (sin TensorFlow).
