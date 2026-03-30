FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set the working directory
WORKDIR /app

# Copy dependency files first for caching
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
RUN uv sync --frozen --no-install-project

# Copy the rest of the project files
COPY . .

# Expose the port (not really needed for pytest, but for the app later)
EXPOSE 8000

# Set the PATH to include the virtual environment's bin
ENV PATH="/app/.venv/bin:$PATH"

# Default command (overridden by docker-compose)
CMD ["python", "-m", "akeneo_mock_server"]
