# Container for any host (Fly.io, Railway, Hugging Face Spaces, a VM...).
#   docker build -t case-conference .
#   docker run -p 8000:8000 -e PORTKEY_API_KEY=... case-conference
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYDANTIC_AI_NO_BANNER=1
COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt
COPY . .
ENV HOST=0.0.0.0 PORT=8000 CC_PUBLIC_DEMO=1 CC_DAILY_BUDGET_USD=0.30 CC_GLOBAL_DAILY_BUDGET_USD=3.00
EXPOSE 8000
CMD ["python", "run.py", "--proxy-headers"]
