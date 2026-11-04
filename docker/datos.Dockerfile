# API de datos de los sensores y emisor de lecturas (proyecto Simulador_sensor, carpeta tiempo_real).
# Solo las librerías que necesitan la API y el emisor: no hace falta el simulador hidráulico.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" requests pandas numpy pyarrow scikit-learn
WORKDIR /app
COPY Simulador_sensor/simulador simulador
COPY Simulador_sensor/experimentos experimentos
COPY Simulador_sensor/tiempo_real tiempo_real
EXPOSE 8000
# tiempo_real.servicio atiende solo en 127.0.0.1; dentro de Docker tiene que ser 0.0.0.0
CMD ["python", "-c", "import uvicorn; from tiempo_real.servicio import crear_app; uvicorn.run(crear_app(False), host='0.0.0.0', port=8000, log_level='warning')"]
