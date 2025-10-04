import socket, paramiko

HOST, PORT = "13.111.67.50", 22
USER, PASSWORD = "514028121", "<<<your password>>>"

sock = socket.create_connection((HOST, PORT), timeout=20)
sock.settimeout(30)

client = paramiko.SSHClient()
client.load_system_host_keys()
client.set_missing_host_key_policy(paramiko.RejectPolicy)

client.connect(
    HOST, port=PORT, username=USER, password=PASSWORD,
    look_for_keys=False, allow_agent=False,
    banner_timeout=60, auth_timeout=30, timeout=30,
    sock=sock,
    # if Paramiko tries modern pubkey sigs first and the server is picky:
    disabled_algorithms={"pubkeys": ["rsa-sha2-256","rsa-sha2-512","ssh-ed25519"]},
)

sftp = client.open_sftp()
print(sftp.listdir("."))
sftp.close()
client.close()
