#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "=== Merchant Website Booking Classifier - Setup ==="
echo ""

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
else
    echo "Virtual environment already exists."
fi

# Activate
source .venv/bin/activate

# Install dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browser
echo "Installing Chromium for Playwright..."
python -m playwright install chromium

echo ""
echo "=== Setup complete! ==="
echo ""
echo "To run the classifier:"
echo "  source .venv/bin/activate"
echo "  python run.py"
echo ""
echo "Make sure to place your input CSV at: data/input.csv"
echo "Or specify a path: python run.py --input /path/to/your.csv"
