#!/bin/bash
echo "Restarting SEO Dada service to clear cache..."
sudo systemctl restart seodada
sleep 3
echo "Checking status..."
sudo systemctl status seodada --no-pager
echo "Service restarted successfully!"
