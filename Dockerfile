# Servicio de monitoreo con el dashboard ya compilado (RNF-008).
# Se construye desde la carpeta que contiene los tres proyectos (ver docker-compose.yml), porque
# necesita el paquete calidad_agua de Modelo_calidad_agua.

# 1. dashboard (React): se compila a archivos estáticos
FROM node:22-slim AS dashboard
WORKDIR /app
COPY Monitoreo_calidad_agua/frontend/package.json Monitoreo_calidad_agua/frontend/package-lock.json ./
RUN npm ci
COPY Monitoreo_calidad_agua/frontend/ ./
RUN npm run build

# 2. servicio (FastAPI) con el paquete de modelos y TensorFlow (pronóstico combinado con la LSTM)
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TF_CPP_MIN_LOG_LEVEL=3
WORKDIR /app
# editable, como en la PC: el paquete lee hiperparametros.yaml de su carpeta; clima/ tiene el
# pronóstico de lluvia pasado que usa el servicio con los datos del emisor
COPY Modelo_calidad_agua/pyproject.toml Modelo_calidad_agua/README.md /modelo/
COPY Modelo_calidad_agua/calidad_agua /modelo/calidad_agua
COPY Modelo_calidad_agua/clima /modelo/clima
# mismas versiones que donde se entrenaron los modelos (los .joblib y .keras dependen de ellas)
RUN pip install --no-cache-dir "scikit-learn==1.9.1" "numpy==2.5.3" "pandas==3.0.6" "pyarrow==25.0.1" \
        "joblib==1.6.0" "tensorflow==2.21.0" "keras==3.15.1" \
    && pip install --no-cache-dir -e "/modelo[red]"
COPY Monitoreo_calidad_agua/backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY Monitoreo_calidad_agua/backend/monitoreo backend/monitoreo
COPY --from=dashboard /app/dist frontend/dist
WORKDIR /app/backend
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=4)"
CMD ["python", "-m", "monitoreo.servicio", "--host", "0.0.0.0"]
