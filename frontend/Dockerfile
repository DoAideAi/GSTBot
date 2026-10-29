# GSTBot frontend: a Vite build served by nginx.
#
# The runtime image is nginx plus a directory of static files — no node, no
# node_modules, nothing with a CVE feed to track.

# ---------- build ----------
FROM node:22-alpine AS build

WORKDIR /app

# Dependencies first so a source edit does not reinstall them. `npm ci` rather
# than `npm install`: the lockfile is the input, and a build that silently
# resolves a different version is not reproducible.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build


# ---------- runtime ----------
FROM nginx:1.31-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
