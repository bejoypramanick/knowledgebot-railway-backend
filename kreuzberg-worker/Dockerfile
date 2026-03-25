FROM rust:1.86-slim AS builder

WORKDIR /app

COPY kreuzberg-worker/Cargo.toml /app/Cargo.toml
COPY kreuzberg-worker/src /app/src

RUN cargo build --release

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/target/release/kreuzberg-worker /usr/local/bin/kreuzberg-worker

CMD ["kreuzberg-worker"]
