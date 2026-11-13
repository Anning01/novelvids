# 前端镜像：Vue 3 + Vite 构建，Nginx 托管静态资源并反向代理后端
# 从仓库根目录构建，以包含首页使用的共享提示词。
FROM node:22-alpine AS builder

WORKDIR /app/web

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY release.json /app/release.json
COPY web/ ./
COPY prompts/home_inspirations.json /app/prompts/home_inspirations.json
RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/web/dist /usr/share/nginx/html

EXPOSE 80
