FROM node:20-bookworm-slim AS frontend
WORKDIR /build
COPY package.json vite.config.js index.html ./
COPY src ./src
RUN npm install && npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY backend_main_react.py ./
COPY index.html ./
COPY package.json ./
COPY --from=frontend /build/dist ./dist
COPY data ./data
COPY generated ./generated
EXPOSE 8000
CMD ["uvicorn", "backend_main_react:app", "--host", "0.0.0.0", "--port", "8000"]
