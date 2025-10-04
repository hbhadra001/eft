import socket
HOST, PORT = "13.111.67.50", 22

sock = socket.create_connection((HOST, PORT), timeout=20)
sock.settimeout(20)
# Read up to 255 bytes to capture the SSH-2.0 banner
data = sock.recv(255)
print("BANNER BYTES:", data)
sock.close()
