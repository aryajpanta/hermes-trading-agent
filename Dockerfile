FROM node:20-alpine

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm ci --only=production && npm cache clean --force

# Copy application code
COPY . .

# Create data directories (will be persisted)
RUN mkdir -p data/trades data/strategy data/reviews data/market

EXPOSE 8080

CMD ["node", "src/index.js"]
