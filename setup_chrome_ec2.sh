#!/bin/bash

# Script to install Chrome and dependencies on Amazon Linux 2/Amazon Linux 2023
# Run this script on your EC2 instance to fix Selenium Chrome issues

echo "========================================="
echo "Installing Chrome and dependencies for EC2"
echo "========================================="

# Update system
echo "Updating system packages..."
sudo yum update -y

# Install required dependencies
echo "Installing Chrome dependencies..."
sudo yum install -y \
    wget \
    curl \
    unzip \
    libX11 \
    libXcomposite \
    libXcursor \
    libXdamage \
    libXext \
    libXi \
    libXtst \
    cups-libs \
    libXScrnSaver \
    libXrandr \
    alsa-lib \
    pango \
    atk \
    at-spi2-atk \
    gtk3 \
    ipa-gothic-fonts \
    xorg-x11-fonts-100dpi \
    xorg-x11-fonts-75dpi \
    xorg-x11-utils \
    xorg-x11-fonts-cyrillic \
    xorg-x11-fonts-Type1 \
    xorg-x11-fonts-misc \
    mesa-libgbm \
    nss \
    nspr \
    dbus-libs \
    expat

# Download and install Google Chrome
echo "Downloading Google Chrome..."
cd /tmp
wget https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm

echo "Installing Google Chrome..."
sudo yum install -y ./google-chrome-stable_current_x86_64.rpm

# Verify installation
echo "Verifying Chrome installation..."
if command -v google-chrome &> /dev/null; then
    echo "Chrome installed successfully!"
    google-chrome --version
else
    echo "ERROR: Chrome installation failed!"
    exit 1
fi

# Clean up
echo "Cleaning up temporary files..."
rm -f /tmp/google-chrome-stable_current_x86_64.rpm

# Install chromedriver (optional, webdriver-manager should handle this)
echo "Installing ChromeDriver..."
CHROME_VERSION=$(google-chrome --version | grep -oP '\d+\.\d+\.\d+')
CHROMEDRIVER_VERSION=$(curl -s "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_${CHROME_VERSION%%.*}")

echo "Chrome version: $CHROME_VERSION"
echo "ChromeDriver version: $CHROMEDRIVER_VERSION"

wget "https://chromedriver.storage.googleapis.com/${CHROMEDRIVER_VERSION}/chromedriver_linux64.zip"
unzip chromedriver_linux64.zip
sudo mv chromedriver /usr/local/bin/
sudo chmod +x /usr/local/bin/chromedriver
rm chromedriver_linux64.zip

# Verify chromedriver
echo "Verifying ChromeDriver installation..."
if command -v chromedriver &> /dev/null; then
    echo "ChromeDriver installed successfully!"
    chromedriver --version
else
    echo "WARNING: ChromeDriver installation may have issues, but webdriver-manager should handle it"
fi

echo "========================================="
echo "Installation complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Restart your application: sudo systemctl restart seodada.service"
echo "2. Monitor logs: sudo journalctl -fu seodada.service"
echo ""
echo "If you still encounter issues, check:"
echo "  - Chrome version: google-chrome --version"
echo "  - Chrome process: ps aux | grep chrome"
echo "  - Display: echo \$DISPLAY (should be empty for headless)"
