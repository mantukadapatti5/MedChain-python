FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

# --host 0.0.0.0 is required: Vite's dev server binds to localhost only by
# default, which is unreachable from outside the container (i.e. from the
# host browser via the 5173:5173 port mapping in docker-compose.yml).
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
