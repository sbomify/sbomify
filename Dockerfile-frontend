FROM oven/bun:1.2.1

# Set UTF-8 locale
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# Increase memory limit for Node.js
ENV NODE_OPTIONS="--max-old-space-size=4096"

# Enable Vite build reporting
ENV VITE_BUILD_REPORT=true

# Disable minification
ENV VITE_DISABLE_MINIFY=true

WORKDIR /js-build

# Copy base JS files first for dependency installation
COPY bun.lock package.json ./

RUN bun install

# Copy all configuration files
COPY tsconfig*.json ./
COPY vite.config.ts ./
COPY .eslintrc.* ./
COPY .prettierrc* ./
COPY .dockerignore ./

# Copy source files
COPY core/js/ core/js/
COPY sboms/js/ sboms/js/
COPY teams/js/ teams/js/

# Add timeout to build command to prevent infinite hangs
RUN timeout 15m bun run build --debug || (echo "Build timed out after 15 minutes" && exit 1)

# Move built files to a volume mount point
RUN mkdir -p /build-output && \
    cp -r static/* /build-output/

VOLUME /build-output
CMD ["sh", "-c", "tail -f /dev/null"]  # Keep container running