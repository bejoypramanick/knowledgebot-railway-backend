# 1. Use the official CPU base image
FROM quay.io/docling-project/docling-serve-cpu:latest

# Switch to root to create directories and move files
USER root

# Define the central artifacts directory
ENV DOCLING_SERVE_ARTIFACTS_PATH=/opt/app-root/src/models
ENV OCR_ENGINE=rapidocr

# Create the specific nested path for OCR
RUN mkdir -p ${DOCLING_SERVE_ARTIFACTS_PATH}/RapidOcr

# 2. Download all models and organize them in one layer
# We use 'mv' instead of 'cp' to avoid bloating the image size
RUN docling-tools models download --all -o ${DOCLING_SERVE_ARTIFACTS_PATH} && \
    mv ${DOCLING_SERVE_ARTIFACTS_PATH}/onnx ${DOCLING_SERVE_ARTIFACTS_PATH}/RapidOcr/ && \
    mv ${DOCLING_SERVE_ARTIFACTS_PATH}/paddle ${DOCLING_SERVE_ARTIFACTS_PATH}/RapidOcr/ && \
    mv ${DOCLING_SERVE_ARTIFACTS_PATH}/fonts ${DOCLING_SERVE_ARTIFACTS_PATH}/RapidOcr/

# Change ownership back to the default user for security
RUN chown -R 1001:0 ${DOCLING_SERVE_ARTIFACTS_PATH}

# Switch back to the non-root user provided by the base image
USER 1001

# The base image already has the entrypoint set to 'docling-serve run'
# If you want to run the RQ worker specifically, uncomment the line below:
# CMD ["docling-serve", "-vv", "rq-worker"]
