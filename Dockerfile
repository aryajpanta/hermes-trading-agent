# Use official Node.js LTS image
FROM node:22-alpine

# Create app directory
WORKDIR /app

# Copy package files and install dependencies
COPY package*.json ./
RUN npm ci --only=production && npm cache clean --force

# Copy application source
COPY . .

# Expose the port Railway assigns
EXPOSE ${PORT:-8080}

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:${PORT:-8080}/health || exit 1

# Start the trading agent
CMD ["node", "src/index.js"]
