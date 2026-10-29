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
  requirements.txt
frontend/              dashboard en React (Vite + Recharts)
  src/
    App.jsx            página y navegación entre las dos vistas (#/general y #/sensor/J224)
    componentes/       Encabezado, VistaGeneral, GraficoRed, MapaCalor, RedSensores,
                       DetalleSensor, Graficos, Alarmas
    api.js             consultas periódicas al backend
    formato.js         etiquetas, norma, tolerancias, formato de números y fechas
    estilos.css        colores (modo claro y oscuro), tipografía y diseño
registros/             CSV de cada sesión del motor (no se versiona)
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

## Uso

**Verificación (sin API).** Reproduce el periodo de prueba a través del motor y
compara con el cálculo de los notebooks: mismos pronósticos, mismas alarmas y mismas
métricas (acierto del notebook 08, eventos detectados y falsas alarmas del notebook 07).

```
python -m monitoreo.verificar              # periodo de prueba completo (~5 min)
python -m monitoreo.verificar --dias 10    # más rápido
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
3. En PowerShell, guardar el token como variable de entorno del usuario (no va en el código ni
   en git) y sacar el *chat id*:

   ```
   setx TELEGRAM_TOKEN "el-token-del-bot"
   # abrir una terminal nueva para que tome la variable; desde backend/, con el venv activado:
   python -m monitoreo.alertas --chat-id
   setx TELEGRAM_CHAT_ID "el-chat-id"
   # otra terminal nueva:
   python -m monitoreo.alertas --prueba
   ```

Al arrancar, el servicio dice en la consola qué canal usa (`Alertas: telegram`) y `/api/estado`
informa cuántas alertas se enviaron y el último error, si hubo.

Opciones (variables de entorno): `ALERTAS_RIESGO=0` para no avisar del riesgo en 24 h,
`ALERTAS_RESUMEN_HORA` para la hora del resumen diario (7 por defecto; `-1` para no mandarlo),
`URL_DASHBOARD` para el enlace de los mensajes y `TELEGRAM_CHAT_ID` con varios chats separados
por coma para avisar a más de una persona. Las horas son las de los datos: con el emisor en
tiempo real coinciden con el reloj; con el emisor acelerado llegan muchos mensajes seguidos.

### API del servicio (puerto 8001)

| Ruta | Qué devuelve |
|---|---|
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
