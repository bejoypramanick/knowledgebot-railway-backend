#!/bin/bash

##############################################################################
# RapidOCR Model Installer for Docling
#
# This script downloads and installs all required RapidOCR models for
# docling-serve to work in offline mode (with DOCLING_SERVE_ARTIFACTS_PATH set)
#
# Usage: bash install_rapidocr_models.sh [DATA_PATH]
# Default DATA_PATH: /data
##############################################################################

set -e

# Configuration
DATA_PATH="${1:-.}"
RAPIDOCR_PATH="$DATA_PATH/RapidOcr"
ONNX_PATH="$RAPIDOCR_PATH/onnx/PP-OCRv4"
PADDLE_PATH="$RAPIDOCR_PATH/paddle/PP-OCRv4"
FONTS_PATH="$RAPIDOCR_PATH/fonts"

# GitHub raw content URL for RapidOCR models
GITHUB_BASE="https://raw.githubusercontent.com/RapidAI/RapidOCR/main/models"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}RapidOCR Model Installer for Docling${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}Target directory: $DATA_PATH${NC}"
echo ""

# Create directory structure
echo -e "${BLUE}[1/5] Creating directory structure...${NC}"
mkdir -p "$ONNX_PATH/det"
mkdir -p "$ONNX_PATH/rec"
mkdir -p "$ONNX_PATH/cls"
mkdir -p "$PADDLE_PATH/rec"
mkdir -p "$FONTS_PATH"
echo -e "${GREEN}✓ Directories created${NC}"

# Function to download file with retry
download_file() {
    local url="$1"
    local dest="$2"
    local filename=$(basename "$dest")

    if [ -f "$dest" ]; then
        echo -e "${GREEN}✓ $filename already exists${NC}"
        return 0
    fi

    echo -e "${YELLOW}  Downloading: $filename${NC}"

    # Try curl first, then wget
    if command -v curl &> /dev/null; then
        curl -L -f -o "$dest" "$url" 2>/dev/null || {
            echo -e "${RED}✗ Failed to download $filename${NC}"
            return 1
        }
    elif command -v wget &> /dev/null; then
        wget -q -O "$dest" "$url" || {
            echo -e "${RED}✗ Failed to download $filename${NC}"
            return 1
        }
    else
        echo -e "${RED}✗ Neither curl nor wget found. Please install one of them.${NC}"
        return 1
    fi

    echo -e "${GREEN}  ✓ Downloaded${NC}"
    return 0
}

# Download Detection Model
echo -e "${BLUE}[2/5] Downloading OCR Detection Model...${NC}"
download_file \
    "$GITHUB_BASE/onnx/PP-OCRv4_det_infer/ch_PP-OCRv4_det_infer.onnx" \
    "$ONNX_PATH/det/ch_PP-OCRv4_det_infer.onnx"

# Download Recognition Model
echo -e "${BLUE}[3/5] Downloading OCR Recognition Model...${NC}"
download_file \
    "$GITHUB_BASE/onnx/PP-OCRv4_rec_infer/ch_PP-OCRv4_rec_infer.onnx" \
    "$ONNX_PATH/rec/ch_PP-OCRv4_rec_infer.onnx"

# Download Classification Model
echo -e "${BLUE}[4/5] Downloading OCR Classification Model...${NC}"
download_file \
    "$GITHUB_BASE/onnx/ch_ppocr_mobile_v2.0_cls_infer.onnx" \
    "$ONNX_PATH/cls/ch_ppocr_mobile_v2.0_cls_infer.onnx"

# Download Recognition Keys (Paddle format)
echo -e "${BLUE}[5/5] Downloading OCR Keys and Fonts...${NC}"
download_file \
    "$GITHUB_BASE/paddle_models/PP-OCRv4/ch_PP-OCRv4_rec_infer/ppocr_keys_v1.txt" \
    "$PADDLE_PATH/rec/ch_PP-OCRv4_rec_infer/ppocr_keys_v1.txt"

# Download Font (if available)
download_file \
    "https://raw.githubusercontent.com/PaddleOCR/PaddleOCR/release/2.7/doc/fonts/FZYTK.TTF" \
    "$FONTS_PATH/FZYTK.TTF" || true

# Verify installations
echo ""
echo -e "${BLUE}Verification:${NC}"

verify_file() {
    local filepath="$1"
    local filename=$(basename "$filepath")

    if [ -f "$filepath" ]; then
        local size=$(du -h "$filepath" | cut -f1)
        echo -e "${GREEN}✓ $filename (Size: $size)${NC}"
    else
        echo -e "${RED}✗ $filename - NOT FOUND${NC}"
    fi
}

verify_file "$ONNX_PATH/det/ch_PP-OCRv4_det_infer.onnx"
verify_file "$ONNX_PATH/rec/ch_PP-OCRv4_rec_infer.onnx"
verify_file "$ONNX_PATH/cls/ch_ppocr_mobile_v2.0_cls_infer.onnx"
verify_file "$PADDLE_PATH/rec/ch_PP-OCRv4_rec_infer/ppocr_keys_v1.txt"
verify_file "$FONTS_PATH/FZYTK.TTF"

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Ensure DOCLING_SERVE_ARTIFACTS_PATH=/data is set"
echo "2. Restart docling-serve container"
echo "3. Models should now load without warnings"
echo ""
echo -e "${YELLOW}Directory Structure:${NC}"
tree -L 3 "$RAPIDOCR_PATH" 2>/dev/null || find "$RAPIDOCR_PATH" -type f | head -20
echo ""
