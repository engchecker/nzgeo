FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 NZGEO_HOST=0.0.0.0 NZGEO_HOME=/tmp/nzgeo
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir --prefer-binary .
CMD ["python", "-c", "import os; from nzgeo.webapp import serve; serve(int(os.environ.get('PORT', '10000')), open_browser=False)"]
