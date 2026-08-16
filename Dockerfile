# =============================================================================
# Stage 1: Build Next.js web application
# =============================================================================
FROM node:20-bookworm-slim AS web-builder

WORKDIR /build/web

# Install dependencies first (cached layer)
COPY web/package.json web/package-lock.json ./
RUN npm ci

# Copy source
COPY web/ ./

# Bake public env vars into the Next.js build
ARG NEXT_PUBLIC_API_URL=""
ARG NEXT_PUBLIC_WS_URL=""
RUN echo "NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}" > .env.local && \
    echo "NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL}" >> .env.local

RUN npm run build

# =============================================================================
# Stage 2: Build Python dependencies (needs dev headers)
# =============================================================================
FROM python:3.12-slim-bookworm AS py-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libgphoto2-dev \
    libusb-1.0-0-dev \
    pkg-config \
    libraw-dev \
    libtiff-dev \
    libjpeg-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --prefix=/install \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r /tmp/requirements.txt

# =============================================================================
# Stage 3: Runtime — slim Debian with only runtime libs
# =============================================================================
FROM python:3.12-slim-bookworm AS runtime

# Runtime-only libraries (no -dev packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgphoto2-6 \
    gphoto2 \
    libusb-1.0-0 \
    libraw20 \
    libtiff6 \
    libjpeg62-turbo \
    libpng16-16 \
    libgl1 \
    libglib2.0-0 \
    curl \
    udev \
    ca-certificates \
    gnupg \
    psmisc \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20 (needed for next start)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy pre-built Python packages from builder
COPY --from=py-builder /install /usr/local

# Copy API source
COPY api/ /app/api/

# Copy only the Next.js build output (not source/full node_modules)
COPY --from=web-builder /build/web/.next /app/web/.next
COPY --from=web-builder /build/web/node_modules /app/web/node_modules
COPY --from=web-builder /build/web/package.json /app/web/package.json
# Create persistent data directories
RUN mkdir -p /app/api/media /app/api/data /app/api/models

# Seed colorchecker profiles into image (volume mount will shadow api/media,
# so we stash them separately and copy at startup via entrypoint)
COPY api/media/colorchecker /app/seed/colorchecker

# Copy entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 3000 8000

ENTRYPOINT ["/app/entrypoint.sh"]
