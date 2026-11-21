FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY telegram_keyword.py mcp_server.py ./
CMD ["python", "mcp_server.py"]
