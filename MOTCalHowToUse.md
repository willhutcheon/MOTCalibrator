To connect an MOT device to the calibrator, go to the settings page on the MOT and click admin. The password is 109077. Turn on debug mode. If debug mode is already on, turn it off and back on again. Wait until the calibrators UI indicates that the device has been connected. You can now select which calibration setting you would like to use on the connected device.

To flash a new device, open the command terminal and use these commands to get access to esptool:
source ~/esp-env/bin/activate
(esp-env) cal@MOT-CAL:~ $ python /home/cal/Documents/MOTCal.py
