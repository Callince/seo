#!/bin/bash
# Restart SEO Dada service on DigitalOcean Droplet
echo "Restarting SEO Dada service..."
sudo systemctl restart seodada
sleep 3
echo "Checking status..."
sudo systemctl status seodada --no-pager
echo ""
echo "Recent logs:"
sudo journalctl -u seodada --no-pager -n 20
