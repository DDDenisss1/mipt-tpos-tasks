FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir PyMySQL==1.1.1
COPY filler.py .
CMD ["python", "filler.py"]
