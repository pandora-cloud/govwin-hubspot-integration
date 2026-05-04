FROM python:3.14-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

# Copy source
COPY . .

CMD ["python", "-m", "pytest", "tests/", "-v", "--tb=short"]
