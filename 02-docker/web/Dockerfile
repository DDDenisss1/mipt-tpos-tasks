FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir Flask==3.1.1 PyMySQL==1.1.1
COPY app.py .
EXPOSE 8000
CMD ["python", "app.py"]
