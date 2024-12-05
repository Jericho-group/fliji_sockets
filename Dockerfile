# --- Build Stage ---
FROM python:3.12-slim AS builder
WORKDIR /app

# Install system dependencies required for compiling
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc curl build-essential libc6-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install rustup and the latest stable Rust version
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Upgrade pip and install PDM
RUN pip install -U pip setuptools wheel
RUN pip install pdm

# Copy only the necessary files for installation
COPY pyproject.toml pdm.lock ./

# Install dependencies using PDM
RUN pdm install --prod --frozen-lockfile --no-editable

# --- Final Stage ---
FROM python:3.12-slim
WORKDIR /app

# Upgrade pip and install PDM
RUN pip install -U pip setuptools wheel
RUN pip install pdm==2.12.3

# Copy installed packages from the builder stage
COPY --from=builder /app/.venv /app/.venv

# Copy the rest of your application code
COPY . .

# Entry point redefined in docker-compose.yaml
ENTRYPOINT ["/app/entrypoint.sh"]
