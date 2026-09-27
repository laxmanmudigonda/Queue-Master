FROM python:3.12-slim
WORKDIR /srv
COPY . .
RUN pip install --no-cache-dir . && useradd --create-home runner
USER runner
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
