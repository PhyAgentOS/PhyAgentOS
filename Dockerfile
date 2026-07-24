FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p PhyAgentOS && touch PhyAgentOS/__init__.py && \
    uv pip install --system --no-cache . && \
    rm -rf PhyAgentOS

# Copy the full source and install
COPY PhyAgentOS/ PhyAgentOS/
RUN uv pip install --system --no-cache .

# Create config directory
RUN mkdir -p /root/.PhyAgentOS

# Gateway default port
EXPOSE 18790

ENTRYPOINT ["PhyAgentOS"]
CMD ["status"]
