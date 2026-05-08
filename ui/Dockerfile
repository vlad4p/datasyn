FROM node:20-alpine

WORKDIR /app

ARG VITE_JUPYTER_URL=http://localhost:8888
ARG VITE_JUPYTER_TOKEN=
ENV VITE_JUPYTER_URL=$VITE_JUPYTER_URL
ENV VITE_JUPYTER_TOKEN=$VITE_JUPYTER_TOKEN

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

EXPOSE 8003

CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "8003"]
