FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CELLLOOP_SAMPLES_DIR=/samples
WORKDIR /app

# INSTALL_ML=1 adds BoTorch/PyTorch and impedance.py (larger image, used by the recommender when present)
ARG INSTALL_ML=0
COPY requirements.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && if [ "$INSTALL_ML" = "1" ]; then pip install --no-cache-dir -r requirements-ml.txt; fi

COPY app ./app
COPY --from=samples . /samples
RUN useradd --create-home appuser && mkdir -p /app/data && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
