1. Make the script executable with the command -> chmod +x /home/pi/mot_calibrator/mot_calibrator.py
2. Create the service -> sudo nano /etc/systemd/system/mot-calibrator.service
3. Use this to create the service ->
[Unit]
Description=MOT Calibration UI
After=network.target graphical.target
Wants=network.target
[Service]
Type=simple
User=cal
Group=cal
WorkingDirectory=/home/cal/Documents
ExecStart=/usr/bin/python3 /home/cal/Documents/MOTCal.py
Restart=always
RestartSec=2
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/cal/.Xauthority
StandardOutput=journal
StandardError=journal
[Install]
WantedBy=graphical.target
5. Reload and enable the service -> sudo systemctl daemon-reload <br>
                                    sudo systemctl enable mot-calibrator.service <br>
                                    sudo systemctl start mot-calibrator.service
6. To stop -> sudo systemctl stop mot-calibrator.service
7. Other helpful commands -> sudo systemctl set-default graphical.target sudo reboot (for setting target screen when changing between screens) <br>
&nbsp;&nbsp;&nbsp;&nbsp                             cd ~/LCD-show <br>
                             sudo ./LCD-hdmi <br>
                             sudo ./MHS35-show

NOTE: one thing I might be missing here is how to get esptool running in the venv, will look into what commands were used if any soon.
