1. Make the script executable with the command -> chmod +x /home/pi/mot_calibrator/mot_calibrator.py
2. Create the service -> sudo nano /etc/systemd/system/mot-calibrator.service
3. Use this to create the service -> <br>
[Unit] <br>
Description=MOT Calibration UI <br>
After=network.target graphical.target <br>
Wants=network.target <br>
[Service] <br>
Type=simple <br>
User=cal <br>
Group=cal <br>
WorkingDirectory=/home/cal/Documents <br>
ExecStart=/usr/bin/python3 /home/cal/Documents/MOTCal.py <br>
Restart=always <br>
RestartSec=2 <br>
Environment=DISPLAY=:0 <br>
Environment=XAUTHORITY=/home/cal/.Xauthority <br>
StandardOutput=journal <br>
StandardError=journal <br>
[Install] <br>
WantedBy=graphical.target
5. Reload and enable the service -> sudo systemctl daemon-reload <br>
                                    sudo systemctl enable mot-calibrator.service <br>
                                    sudo systemctl start mot-calibrator.service
6. To stop -> sudo systemctl stop mot-calibrator.service
7. Other helpful commands -> sudo systemctl set-default graphical.target sudo reboot (for setting target screen when changing between screens) <br>
                             cd ~/LCD-show <br>
                             sudo ./LCD-hdmi <br>
                             sudo ./MHS35-show

NOTE: one thing I might be missing here is how to get esptool running in the venv, will look into what commands were used if any soon.
