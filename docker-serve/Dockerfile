# 1. Use the official CPU base image
FROM quay.io/docling-project/docling-serve-cpu:latest

# Switch to root to create directories and move files
USER root

# Define build-time artifact directory (where models will be stored in image)
# This is used only during build, paths can be overridden at runtime via Railway env vars
ARG BUILD_MODELS_PATH=/opt/app-root/src/models

# Create the specific nested path for OCR
RUN mkdir -p ${BUILD_MODELS_PATH}/RapidOcr

# 2. Download all models and organize them in one layer
# We use 'mv' instead of 'cp' to avoid bloating the image size
RUN docling-tools models download --all -o ${BUILD_MODELS_PATH} && \
    mv ${BUILD_MODELS_PATH}/onnx ${BUILD_MODELS_PATH}/RapidOcr/ && \
    mv ${BUILD_MODELS_PATH}/paddle ${BUILD_MODELS_PATH}/RapidOcr/ && \
    mv ${BUILD_MODELS_PATH}/fonts ${BUILD_MODELS_PATH}/RapidOcr/

# Change ownership back to the default user for security
RUN chown -R 1001:0 ${BUILD_MODELS_PATH}

# Switch back to the non-root user provided by the base image
USER 1001

# The base image already has the entrypoint set to 'docling-serve run'
# If you want to run the RQ worker specifically, uncomment the line below:
# CMD ["docling-serve", "-vv", "rq-worker"]
