import paramiko

HOST = "13.111.67.50"
PORT = 22
USER = "514028121"
PASSWORD = "<<<your password>>>"

client = paramiko.SSHClient()
client.load_system_host_keys()
client.set_missing_host_key_policy(paramiko.RejectPolicy)  # use AutoAddPolicy() only for dev

client.connect(
    HOST,
    port=PORT,
    username=USER,
    password=PASSWORD,
    look_for_keys=False,
    allow_agent=False,
    banner_timeout=60,   # be generous; avoids banner timing issues
    auth_timeout=30,
    timeout=30,
    # This server presents an ssh-rsa host key; Paramiko usually handles it fine.
    # If you still get algo complaints, uncomment the next lines:
    # disabled_algorithms={"pubkeys": ["rsa-sha2-256","rsa-sha2-512","ssh-ed25519"]},
)

# Pin/verify host key fingerprint in prod (recommended)
# fp = client.get_transport().get_remote_server_key().get_fingerprint()
# print(":".join(f"{b:02x}" for b in fp))

sftp = client.open_sftp()
print("cwd:", sftp.getcwd() or "/")
print("listing:", sftp.listdir("."))      # list remote dir

# Example upload/download:
# sftp.put("local_file.txt", "remote_file.txt")
# sftp.get("remote_file.txt", "downloaded.txt")

sftp.close()
client.close()
