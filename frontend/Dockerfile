# ── base: dependencias ───────────────────────────────────────
FROM node:22-alpine AS base
WORKDIR /app
COPY package*.json ./
RUN npm install

# ── dev: servidor de Astro con recarga, código por volumen ───
FROM base AS dev
ENV NODE_ENV=development
CMD ["npm", "run", "dev"]

# ── build: compila el bundle de servidor ─────────────────────
FROM base AS build
COPY . .
RUN npm run build

# ── prod: solo el bundle y las dependencias de ejecución ─────
FROM node:22-alpine AS prod
WORKDIR /app
ENV NODE_ENV=production
COPY package*.json ./
RUN npm install --omit=dev && npm cache clean --force
COPY --from=build /app/dist ./dist
USER node
CMD ["node", "./dist/server/entry.mjs"]
