FROM node:26-alpine AS dependencies
WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY apps/extension/package.json apps/extension/package.json
COPY packages/contracts/package.json packages/contracts/package.json
COPY packages/plugin-sdk/package.json packages/plugin-sdk/package.json
RUN npm ci --ignore-scripts

FROM node:26-alpine AS builder
WORKDIR /app
ARG NEXT_PUBLIC_OCDD_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_OCDD_ENABLE_DEMO=false
ENV NEXT_PUBLIC_OCDD_API_URL=${NEXT_PUBLIC_OCDD_API_URL} \
    NEXT_PUBLIC_OCDD_ENABLE_DEMO=${NEXT_PUBLIC_OCDD_ENABLE_DEMO} \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=dependencies /app/node_modules ./node_modules
COPY package.json package-lock.json ./
COPY apps/web ./apps/web
COPY packages/contracts ./packages/contracts
RUN npm --workspace @ocdd/contracts run build \
    && npm --workspace @ocdd/web run build

FROM node:26-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

RUN addgroup --system --gid 10001 nodejs \
    && adduser --system --uid 10001 --ingroup nodejs nextjs

COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/public ./apps/web/public

USER nextjs
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
