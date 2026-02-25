# 1. Use the official CPU base image
FROM quay.io/docling-project/docling-serve-cpu:latest

# Switch to root to create directories and move files
USER root

# Define build-time artifact directory (where models will be stored in image)
# This is used only during build, paths can be overridden at runtime via Railway env vars
ARG BUILD_MODELS_PATH=/opt/app-root/src/models

# 2. Download all models to the parent folder
# All models (onnx, paddle, fonts, etc.) downloaded directly to BUILD_MODELS_PATH
RUN docling-tools models download --all -o ${BUILD_MODELS_PATH}

# Change ownership back to the default user for security
RUN chown -R 1001:0 ${BUILD_MODELS_PATH}

# Switch back to the non-root user provided by the base image
USER 1001

# The base image already has the entrypoint set to 'docling-serve run'
# If you want to run the RQ worker specifically, uncomment the line below:
# CMD ["docling-serve", "-vv", "rq-worker"]
