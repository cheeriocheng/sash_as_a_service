# Sash as a Service | SaaS
As the usual awardee of a sash, women are conditioned to be judged, and to judge themselves through others' eyes. 
Sash as a Service is an invitation to make our own statement. This python script prints it out as a sash. 
<img width="788" height="470" alt="terminal" src="https://github.com/user-attachments/assets/6fd119a4-e6e6-4111-9bc4-22485ffa3edc" />

Futura Bold Oblique tributes to Barbara Kruger.

<img width="788" alt="horizontal" src="https://github.com/user-attachments/assets/79c2aad4-eb90-4de5-bece-63fd737da94f" />

Tested with Epson TM-T88V on MacOS 14


--
to run on clockwork DevTerm 

echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="04b8", ATTR{idProduct}=="0202", MODE="0666"' | sudo tee /etc/udev/rules.d/99-escpos.rules

sudo udevadm control --reload && sudo udevadm trigger
