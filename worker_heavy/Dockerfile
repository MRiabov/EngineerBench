FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libgl1 \
    libglu1-mesa \
    libxrender1 \
    libxext6 \
    libfontconfig1 \
    libx11-6 \
    libegl1 \
    libosmesa6 \
    libglib2.0-0 \
    libsm6 \
    curl \
    dnsutils \
    libvulkan1 \
    vulkan-tools \
    libxcursor1 \
    libxinerama1 \
    libxft2 \
    libxrandr2 \
    libxi6 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Use CPU-only torch to save space
ENV UV_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu

# Copy from the cache instead of linking since it's a separate volume
ENV UV_LINK_MODE=copy
ENV LIBGL_ALWAYS_SOFTWARE=1
ENV PROBLEMOLOGIST_PHYSICS_GL_BACKEND=egl
ENV PROBLEMOLOGIST_RENDER_GL_BACKEND=osmesa
ENV MUJOCO_GL=egl
ENV PYOPENGL_PLATFORM=osmesa
ENV PYVISTA_OFF_SCREEN=true
ENV VTK_DEFAULT_OPENGL_WINDOW=vtkOSOpenGLRenderWindow
ENV PYGLET_HEADLESS=1

# Create non-root user
RUN useradd -m agent
RUN chown -R agent:agent /app

# Switch to non-root user
USER agent

# Install dependencies
RUN --mount=type=cache,target=/home/agent/.cache/uv,uid=1000 \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev --group cad --group rendering --group simulation --group temporal

# Copy source code
COPY --chown=agent:agent worker_heavy ./worker_heavy
COPY --chown=agent:agent worker_light ./worker_light
COPY --chown=agent:agent shared ./shared
COPY --chown=agent:agent config ./config
COPY --chown=agent:agent pyproject.toml uv.lock ./

# Install the project
RUN --mount=type=cache,target=/home/agent/.cache/uv,uid=1000 \
    uv sync --frozen --no-dev --group cad --group rendering --group simulation --group temporal

# Set Python path
ENV PYTHONPATH=/app

# Place executables in the path
ENV PATH="/app/.venv/bin:$PATH"

# Entrypoint
CMD ["/app/.venv/bin/uvicorn", "worker_heavy.app:app", "--host", "0.0.0.0", "--port", "8002"]
