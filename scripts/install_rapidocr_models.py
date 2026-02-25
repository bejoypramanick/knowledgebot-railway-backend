#!/usr/bin/env python3
"""
RapidOCR Model Installer for Docling

This script downloads and installs all required RapidOCR models for
docling-serve to work in offline mode (with DOCLING_SERVE_ARTIFACTS_PATH set)

Usage:
    python install_rapidocr_models.py [--data-path /data]
"""

import os
import sys
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

# ANSI Colors
GREEN = '\033[0;32m'
BLUE = '\033[0;34m'
YELLOW = '\033[1;33m'
RED = '\033[0;31m'
NC = '\033[0m'  # No Color


class RapidOCRInstaller:
    """Install RapidOCR models for docling"""

    # Model URLs - using GitHub raw content
    MODELS = {
        'det': {
            'url': 'https://raw.githubusercontent.com/RapidAI/RapidOCR/main/models/onnx/PP-OCRv4_det_infer/ch_PP-OCRv4_det_infer.onnx',
            'path': 'onnx/PP-OCRv4/det/ch_PP-OCRv4_det_infer.onnx',
            'name': 'Detection Model',
        },
        'rec': {
            'url': 'https://raw.githubusercontent.com/RapidAI/RapidOCR/main/models/onnx/PP-OCRv4_rec_infer/ch_PP-OCRv4_rec_infer.onnx',
            'path': 'onnx/PP-OCRv4/rec/ch_PP-OCRv4_rec_infer.onnx',
            'name': 'Recognition Model',
        },
        'cls': {
            'url': 'https://raw.githubusercontent.com/RapidAI/RapidOCR/main/models/onnx/ch_ppocr_mobile_v2.0_cls_infer.onnx',
            'path': 'onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_infer.onnx',
            'name': 'Classification Model',
        },
        'keys': {
            'url': 'https://raw.githubusercontent.com/RapidAI/RapidOCR/main/models/paddle_models/PP-OCRv4/ch_PP-OCRv4_rec_infer/ppocr_keys_v1.txt',
            'path': 'paddle/PP-OCRv4/rec/ch_PP-OCRv4_rec_infer/ppocr_keys_v1.txt',
            'name': 'Recognition Keys',
        },
        'font': {
            'url': 'https://raw.githubusercontent.com/PaddleOCR/PaddleOCR/release/2.7/doc/fonts/FZYTK.TTF',
            'path': 'fonts/FZYTK.TTF',
            'name': 'Font File',
            'optional': True,
        },
    }

    def __init__(self, data_path: str = '/data'):
        self.data_path = Path(data_path)
        self.rapidocr_path = self.data_path / 'RapidOcr'
        self.step = 0
        self.total_steps = len(self.MODELS)

    def print_header(self):
        """Print installation header"""
        print(f"{BLUE}{'='*50}{NC}")
        print(f"{BLUE}RapidOCR Model Installer for Docling{NC}")
        print(f"{BLUE}{'='*50}{NC}")
        print(f"{YELLOW}Target directory: {self.data_path}{NC}")
        print()

    def create_directories(self):
        """Create necessary directory structure"""
        print(f"{BLUE}Creating directory structure...{NC}")
        dirs = [
            self.rapidocr_path / 'onnx/PP-OCRv4/det',
            self.rapidocr_path / 'onnx/PP-OCRv4/rec',
            self.rapidocr_path / 'onnx/PP-OCRv4/cls',
            self.rapidocr_path / 'paddle/PP-OCRv4/rec/ch_PP-OCRv4_rec_infer',
            self.rapidocr_path / 'fonts',
        ]

        for dir_path in dirs:
            dir_path.mkdir(parents=True, exist_ok=True)

        print(f"{GREEN}✓ Directories created{NC}\n")

    def download_file(self, model_key: str) -> bool:
        """Download a single model file"""
        self.step += 1
        model = self.MODELS[model_key]
        url = model['url']
        rel_path = model['path']
        name = model['name']
        is_optional = model.get('optional', False)

        file_path = self.rapidocr_path / rel_path

        # Skip if already exists
        if file_path.exists():
            size = self._format_size(file_path.stat().st_size)
            print(f"{GREEN}✓ [{self.step}/{self.total_steps}] {name} - Already exists (Size: {size}){NC}")
            return True

        print(f"{BLUE}[{self.step}/{self.total_steps}] Downloading {name}...{NC}")
        print(f"  URL: {url}")

        try:
            # Create parent directory if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Download with progress
            self._download_with_progress(url, str(file_path))

            if file_path.exists():
                size = self._format_size(file_path.stat().st_size)
                print(f"{GREEN}✓ Downloaded - Size: {size}{NC}\n")
                return True
            else:
                raise Exception("File not created after download")

        except Exception as e:
            if is_optional:
                print(f"{YELLOW}⚠ Skipped (optional): {str(e)}{NC}\n")
                return True
            else:
                print(f"{RED}✗ Failed: {str(e)}{NC}\n")
                return False

    def _download_with_progress(self, url: str, filepath: str, chunk_size: int = 8192):
        """Download file with progress indicator"""
        try:
            response = urllib.request.urlopen(url, timeout=30)
            total_size = int(response.headers.get('content-length', 0))

            with open(filepath, 'wb') as f:
                downloaded = 0
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        bar_length = 30
                        filled = int(bar_length * downloaded / total_size)
                        bar = '█' * filled + '░' * (bar_length - filled)
                        print(f"\r  [{bar}] {percent:.1f}%", end='', flush=True)

            print()  # Newline after progress bar

        except urllib.error.URLError as e:
            raise Exception(f"Download failed: {str(e)}")

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format bytes to human readable size"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f}TB"

    def verify_installation(self):
        """Verify all models are installed"""
        print(f"\n{BLUE}Verification:{NC}")

        all_good = True
        for model_key, model in self.MODELS.items():
            rel_path = model['path']
            file_path = self.rapidocr_path / rel_path
            name = model['name']

            if file_path.exists():
                size = self._format_size(file_path.stat().st_size)
                print(f"{GREEN}✓ {name} (Size: {size}){NC}")
            else:
                is_optional = model.get('optional', False)
                if is_optional:
                    print(f"{YELLOW}⚠ {name} - Optional (not found){NC}")
                else:
                    print(f"{RED}✗ {name} - NOT FOUND{NC}")
                    all_good = False

        return all_good

    def print_next_steps(self, success: bool):
        """Print next steps"""
        print(f"\n{BLUE}{'='*50}{NC}")
        if success:
            print(f"{GREEN}Installation Complete!{NC}")
        else:
            print(f"{RED}Installation had some failures!{NC}")
        print(f"{BLUE}{'='*50}{NC}\n")

        print(f"{YELLOW}Next Steps:{NC}")
        print("1. Ensure DOCLING_SERVE_ARTIFACTS_PATH=/data is set on Railway")
        print("2. Restart docling-serve container")
        print("3. Models should now load without warnings")
        print()

        print(f"{YELLOW}Directory Structure:{NC}")
        print(f"  {self.rapidocr_path}/")
        print(f"  ├── onnx/")
        print(f"  │   └── PP-OCRv4/")
        print(f"  │       ├── det/")
        print(f"  │       ├── rec/")
        print(f"  │       └── cls/")
        print(f"  ├── paddle/")
        print(f"  │   └── PP-OCRv4/")
        print(f"  │       └── rec/")
        print(f"  └── fonts/")
        print()

    def install(self) -> bool:
        """Run full installation"""
        self.print_header()
        self.create_directories()

        for model_key in self.MODELS.keys():
            if not self.download_file(model_key):
                return False

        success = self.verify_installation()
        self.print_next_steps(success)

        return success


def main():
    parser = argparse.ArgumentParser(
        description='Install RapidOCR models for docling-serve'
    )
    parser.add_argument(
        '--data-path',
        default='/data',
        help='Path where models should be installed (default: /data)'
    )

    args = parser.parse_args()

    installer = RapidOCRInstaller(data_path=args.data_path)

    try:
        success = installer.install()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Installation cancelled by user{NC}")
        sys.exit(1)
    except Exception as e:
        print(f"{RED}Error: {str(e)}{NC}")
        sys.exit(1)


if __name__ == '__main__':
    main()
