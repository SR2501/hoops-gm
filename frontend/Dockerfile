# Frontend image — the Vite dev server.
#
# Deliberately not a production nginx build. This is a local-first tool for one
# user (ADR-001); the dev server is what actually gets used, and shipping the
# thing that gets used is better than shipping a second, untested path.
FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Bind 0.0.0.0 inside the container so the loopback-bound published port in
# docker-compose.yml can reach it. Access is restricted by that mapping.
ENV DEV_SERVER_HOST=0.0.0.0

EXPOSE 5173

CMD ["npm", "run", "dev"]
