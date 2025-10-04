import socket, paramiko

HOST = "partner.host"
PORT = 22
USERNAME = "user"
PASSWORD = "your-password"

# Low-level socket first (better control over timeouts)
sock = socket.create_connection((HOST, PORT), timeout=20)
sock.settimeout(20)

t = paramiko.Transport(sock)

# If the server only presents an ssh-rsa (SHA-1) *host key*:
sec = t.get_security_options()
sec.key_types = ['ssh-rsa']  # legacy host-key algo (remove when server upgrades)

# If your logs later complain about kex/cipher/mac, add minimally:
# sec.kex = ['diffie-hellman-group14-sha1']
# sec.ciphers = ['aes128-ctr','aes256-ctr']      # add CBC only if absolutely necessary
# sec.macs = ['hmac-sha2-256','hmac-sha1']

# Older / load-balanced servers can be slow to send the banner:
t.banner_timeout = 60      # <-- important for "Error reading SSH protocol banner"
t.start_client(timeout=20)

# OPTIONAL: verify/pin host key fingerprint here in prod

# Some servers say "password" but expect keyboard-interactive (PAM). Try password first:
try:
    t.auth_password(USERNAME, PASSWORD)
except paramiko.ssh_exception.SSHException:
    # Fall back to keyboard-interactive
    def ki_handler(title, instructions, prompts):
        return [PASSWORD for _ in prompts]
    t.auth_interactive(USERNAME, ki_handler)

# Keep the session alive (middleboxes can drop idle SSH)
t.set_keepalive(30)

sftp = paramiko.SFTPClient.from_transport(t)
print(sftp.listdir("."))
sftp.close()
t.close()
