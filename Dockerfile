FROM python:3.12-slim

WORKDIR /app

# Dependências do sistema (Pillow precisa de libz)
RUN apt-get update && apt-get install -y \
    libzbar0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código
COPY . .

# Porta padrão
EXPOSE 8000

# Comando padrão: API server
CMD ["/bin/sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
