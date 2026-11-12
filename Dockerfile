# Gunakan base image Python 3.10 yang ringan
FROM python:3.10-slim

# Install library sistem pendukung media, ffmpeg, dan OpenCV di Linux
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Tentukan folder kerja aplikasi di dalam container
WORKDIR /app

# Salin file requirements dan install seluruh dependensi Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Salin seluruh kode dan folder proyek VehiScan ke dalam container
COPY . .

# Buat direktori penyimpan upload jika belum ada
RUN mkdir -p uploads static/uploads data

# Expose port standar Hugging Face Spaces
EXPOSE 7860

# Perintah untuk menjalankan server FastAPI Uvicorn
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "7860"]
