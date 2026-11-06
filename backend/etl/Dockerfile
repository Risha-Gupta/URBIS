FROM python:3.12-slim
WORKDIR /etl
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY load_seed.py .
ENTRYPOINT ["python", "load_seed.py"]
