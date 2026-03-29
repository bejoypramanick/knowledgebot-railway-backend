FROM rust:1.91-slim AS builder

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates g++ make pkg-config libssl-dev cmake \
    && rm -rf /var/lib/apt/lists/*

COPY kreuzberg-worker/Cargo.toml /app/Cargo.toml
COPY kreuzberg-worker/src /app/src

RUN cargo build --release

FROM ghcr.io/kreuzberg-dev/kreuzberg:latest

WORKDIR /app

COPY --from=builder /app/target/release/kreuzberg-worker /usr/local/bin/kreuzberg-worker

CMD ["kreuzberg-worker"]
