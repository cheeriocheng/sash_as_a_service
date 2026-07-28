#cut paper 

from escpos.printer import Usb

p = Usb(0x04b8, 0x0202)
# p.text("hello\n")
p.cut() 