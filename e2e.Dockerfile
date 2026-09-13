FROM mcr.microsoft.com/playwright:v1.49.1-noble

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY playwright.config.ts ./
COPY e2e ./e2e

CMD ["npx", "playwright", "test"]
