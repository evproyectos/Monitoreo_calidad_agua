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
    motor.py           recibe lecturas, procesa cada hora cerrada, maneja las alarmas
    cliente_datos.py   consulta la API de datos
    servicio.py        API del servicio (FastAPI, puerto 8001) que además sirve el dashboard
    ejecutar.py        motor en vivo conectado a la API de datos, solo en consola
    verificar.py       comprueba que el motor en vivo da lo mismo que los notebooks
  requirements.txt
frontend/              dashboard en React (Vite + Recharts)
  src/
    App.jsx            página y navegación entre las dos vistas (#/general y #/sensor/J224)
    componentes/       Encabezado, VistaGeneral, RedSensores, DetalleSensor, Graficos, Alarmas
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
`CARPETA_MODELOS`.

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

- **Vista general** (`#/general`): los 21 sensores a la vez, de la fuente al extremo de la
  red, cada uno con su estado, sus valores actuales y una mini-gráfica de las últimas 48 h y
  el pronóstico de las próximas 24 h (cloro, turbidez o pH, todas en la misma escala).
- **Por sensor** (`#/sensor/J224`): la red como tubería para elegir el sensor y sus gráficos
  en detalle (72 h observadas, pronóstico con margen de acierto, límites de la norma y
  probabilidad de evento).

Para trabajar en el frontend con recarga automática: `npm run dev` en `frontend/` y abrir
http://localhost:5173 (las llamadas a `/api` se redirigen al backend en el puerto 8001).

**Solo consola**, sin dashboard: `python -m monitoreo.ejecutar` en lugar del servicio.

### API del servicio (puerto 8001)

| Ruta | Qué devuelve |
|---|---|
| `GET /api/estado` | hora de los datos, conexión, alarma activa, modo de pronóstico |
| `GET /api/sensores` | estado actual de los 21 sensores: observado, pronóstico a 24 h, probabilidad de evento |
| `GET /api/sensores/{nodo}/serie?horas=72` | serie horaria para graficar (observado, pronóstico, probabilidad) |
| `GET /api/red/series?horas=48` | series de los 21 sensores a la vez (vista general) |
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
