FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pricer ./pricer
COPY price_sheet.py sheet_layout.py server.py ./
ENV PYTHONUNBUFFERED=1
CMD ["python", "server.py"]
